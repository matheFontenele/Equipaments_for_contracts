import pandas as pd
import re
from rapidfuzz import fuzz
from utils.text_processing import normalizar, tokens_municipio
from core.config import IS_KIT, DE_PARA_CLIENTES, CLIENTES_IGNORADOS, SUBSTITUICOES_TERMOS, CONTRATOS_POLI_MONO

class MotorDeRegras:
    def __init__(self, opcoes_contratos, dict_mestre):
        self.opcoes_contratos = opcoes_contratos
        self.dict_mestre = dict_mestre
        # True quando o contrato da linha veio de um DE/PARA explícito.
        # Nesse caso o vínculo é determinístico e não deve ser descartado
        # pelo escudo de kits.
        self._vinculo_explicito = False

        # Índice de municípios presentes nos contratos (criado sob demanda)
        self._municipios_conhecidos = None
        
        # 🧠 O CÉREBRO
        self.regras = [
            self._regra_de_para_explicito,         
            self._regra_contrato_mte,              
            self._regra_contrato_mt,               
            self._regra_contrato_por_similaridade, 
            self._regra_item_detran_ma,            
            self._regra_itens_poli_mono,
            self._regra_itens_micro_notebook,           
            self._regra_item_por_similaridade,
            self._regra_item_unico_fallback  
        ] 

    def _vazio(self, valor):
        """Ajudante Blindado: Detecta se o campo está vazio, seja NaN, None ou a string 'None'."""
        if pd.isna(valor):
            return True
        val_str = str(valor).strip().upper()
        return val_str in ["", "NONE", "NAN", "<NA>"]

    def processar_linha(self, row):
        contrato_atual = row.get('CONTRATO')
        item_atual = row.get('ITEM_DO_CONTRATO')
        cliente = str(row.get('CLIENTE_NOME', '')).upper()
        equip_nome = str(row.get('EQUIPAMENTO_NOME', '')).upper()

        # 1. 🚫 ESCUDO DA BLACKLIST
        cliente_tratado = cliente.strip()
        for ignorado in CLIENTES_IGNORADOS:
            if ignorado in cliente_tratado or cliente_tratado in ignorado:
                return pd.Series([None, None])

        self._vinculo_explicito = False

        # 2. MOTOR DE REGRAS
        for regra in self.regras:
            # Se já tem os dois, para de tentar regras novas!
            if not self._vazio(contrato_atual) and not self._vazio(item_atual):
                break
            
            # Passa a bola para a regra tentar preencher
            contrato_atual, item_atual = regra(cliente, equip_nome, contrato_atual, item_atual)

        # 3. 🛡️ ESCUDO DE KITS (Pós-Processamento)
        is_kit = any(str(cat).upper() in equip_nome for cat in IS_KIT)
        
        if is_kit:
            # Se a IA achou um item oficial faturável no contrato, concedemos o salvo-conduto.
            if not self._vazio(item_atual):
                pass 
            elif self._vinculo_explicito:
                # Cliente mapeado por DE/PARA explícito: mantém o contrato mesmo
                # sendo kit sem item previsto. O item fica vazio para escolha manual.
                pass
            else:
                # É kit e não tem item oficial? Ejeta!
                return pd.Series([None, None])

        return pd.Series([contrato_atual, item_atual])

    # =======================================================================
    # 📚 BIBLIOTECA DE REGRAS
    # =======================================================================

    def _regra_de_para_explicito(self, cliente, equip_nome, contrato, item):
        if self._vazio(contrato):
            # Comparação sem acentos/caixa: evita que "ALCANTARA" (sem acento)
            # deixe de casar com "ALCÂNTARA" em qualquer uma das pontas.
            cliente_norm = normalizar(cliente)
            if not cliente_norm:
                return contrato, item

            for chave_suja, contrato_correto in DE_PARA_CLIENTES.items():
                chave_norm = normalizar(chave_suja)
                if not chave_norm:
                    continue

                if chave_norm in cliente_norm or cliente_norm in chave_norm:
                    alvo_norm = normalizar(contrato_correto)
                    for opcao in self.opcoes_contratos:
                        if self._vazio(opcao):
                            continue
                        if normalizar(opcao) == alvo_norm:
                            # Vínculo determinístico: protegido do escudo de kits.
                            self._vinculo_explicito = True
                            return opcao, item
        return contrato, item
    
    def _regra_contrato_mte(self, cliente, equip_nome, contrato, item):
        if self._vazio(contrato):
            if "MTE" in cliente:
                for c in self.opcoes_contratos:
                    if "MTE" in str(c).upper():
                        return c, item
        return contrato, item
    
    def _regra_contrato_mt(self, cliente, equip_nome, contrato, item):
        if self._vazio(contrato):
            if "MINISTERIO DOS TRANSPORTE" in cliente or "MINISTÉRIO DOS TRANSPORTE" in cliente:
                for c in self.opcoes_contratos:
                    c_limpo = str(c).upper().strip()
                    if c_limpo == "MT" or c_limpo.startswith("MT -") or c_limpo.startswith("MT "):
                        return c, item
        return contrato, item
    
    def _texto_chave(self, valor):
        """Texto normalizado (sem acento/pontuação) para comparação de contratos."""
        return " ".join(re.sub(r"[^A-Z0-9 ]", " ", normalizar(valor)).split())

    def _indice_municipios(self):
        """Tokens de município que aparecem nos contratos do dicionário mestre."""
        if self._municipios_conhecidos is None:
            conhecidos = set()
            for info in self.dict_mestre.values():
                conhecidos.update(info.get("municipios") or ())
            self._municipios_conhecidos = conhecidos
        return self._municipios_conhecidos

    def _municipios_do_cliente(self, cliente):
        """Município citado no próprio nome do cliente do equipamento.

        Ex.: 'P M DE BATURITE - GABINETE DO PREFEITO' -> {'BATURITE'}
        """
        tokens = tokens_municipio(cliente)
        if tokens:
            return tokens
        # Sem marcador municipal no início, ainda detecta a menção a um
        # município que existe no banco (ex.: 'SECRETARIA DE SAUDE CAUCAIA').
        # Nomes de empresa/consórcio/UFSC tendem a não colidir com municípios;
        # e a guarda só descarta contratos cujo município divergir.
        palavras = set(re.sub(r"[^A-Z0-9 ]", " ", normalizar(cliente)).split())
        return palavras & self._indice_municipios()

    def _contrato_do_mesmo_municipio(self, contrato, municipios_cliente):
        """False apenas quando ambos os lados têm município e eles divergem."""
        if not municipios_cliente:
            return True
        info = self.dict_mestre.get(normalizar(contrato)) or {}
        municipios_contrato = info.get("municipios") or set()
        if not municipios_contrato:
            return True
        return bool(municipios_contrato & municipios_cliente)

    def _regra_contrato_por_similaridade(self, cliente, equip_nome, contrato, item):
        if self._vazio(contrato):
            cliente_limpo = str(cliente).upper().strip()
            
            # Limpa o cliente com os De-Para de termos
            for termo_original, substituto in SUBSTITUICOES_TERMOS.items():
                cliente_limpo = cliente_limpo.replace(termo_original, substituto)
                
            # Comparação sem acento/pontuação: "ASSISTENCIA" casa com
            # "ASSISTÊNCIA" e "INFRAESTRUTURA," casa com "INFRAESTRUTURA".
            cliente_limpo = self._texto_chave(cliente_limpo)
            
            # =================================================================
            # 🛡️ FILTRO MT (BLINDAGEM ABSOLUTA)
            # =================================================================
            opcoes_permitidas = []
            for c in self.opcoes_contratos:
                if self._vazio(c): continue
                c_upper = str(c).upper().strip()
                
                # Se o contrato for o MT, ele NÃO pode ser avaliado pela IA 
                # a menos que o cliente seja explicitamente o Ministério.
                # Isso mata o falso positivo de siglas como "SMTT" ou "MATO GROSSO" (MT)
                if c_upper == "MT" or c_upper.startswith("MT -") or c_upper.startswith("MT "):
                    if not ("MINIST" in cliente_limpo and "TRANSPORT" in cliente_limpo):
                        continue 
                        
                opcoes_permitidas.append(c)

            # =================================================================
            # 🏛️ GUARDA DE MUNICÍPIO
            # Nomes genéricos (GABINETE DO PREFEITO, CONTROLADORIA GERAL,
            # SECRETARIA DE ASSISTÊNCIA SOCIAL...) existem em vários
            # municípios. Se o cliente cita um município conhecido, só aceita
            # contratos do mesmo município (ou sem município identificável).
            # =================================================================
            municipios_cliente = self._municipios_do_cliente(cliente)
            if municipios_cliente:
                opcoes_permitidas = [
                    c for c in opcoes_permitidas
                    if self._contrato_do_mesmo_municipio(c, municipios_cliente)
                ]

            # =================================================================
            # 1. TESTE RÁPIDO: Substring Exata Bidirecional
            # =================================================================
            for c in opcoes_permitidas:
                contrato_limpo = self._texto_chave(c)
                
                if contrato_limpo and contrato_limpo in cliente_limpo:
                    return c, item
                    
                if len(cliente_limpo) >= 4 and cliente_limpo in contrato_limpo:
                    return c, item

            # =================================================================
            # 2. TESTE DE COBERTURA: Fatias de palavras com Cobertura Reversa
            # =================================================================
            palavras_cliente = set(cliente_limpo.split())
            stop_words = {"DE", "DA", "DO", "DAS", "DOS", "SECRETARIA", "DEPARTAMENTO", "ESTADUAL", "MUNICIPAL", "PREFEITURA", "PREF", "MUNICIPIO", "CONTRATO", "SEC", "ADM", "P", "M"}
            palavras_chave_cliente = {p for p in palavras_cliente - stop_words
                                      if not p.isdigit() and len(p) > 1}

            melhor_match = None
            maior_score = 0.0

            for c in opcoes_permitidas:
                contrato_limpo = self._texto_chave(c)
                palavras_contrato = set(contrato_limpo.split())
                palavras_chave_contrato = {p for p in palavras_contrato - stop_words
                                           if not p.isdigit() and len(p) > 1}
                
                if not palavras_chave_contrato: continue
                
                intersecao = palavras_chave_cliente.intersection(palavras_chave_contrato)
                
                score_cobertura = len(intersecao) / len(palavras_chave_contrato)
                score_reverso = len(intersecao) / len(palavras_chave_cliente) if palavras_chave_cliente else 0
                
                if score_reverso >= 0.99 and len(intersecao) >= 2:
                    score_cobertura = 1.0
                
                if score_cobertura == 1.0:
                    return c, item
                    
                if score_cobertura > 0.7 and score_cobertura > maior_score:
                    maior_score = score_cobertura
                    melhor_match = c

            if melhor_match:
                return melhor_match, item
                
        return contrato, item
    
    def _regra_item_detran_ma(self, cliente, equip_nome, contrato, item):
        if not self._vazio(contrato) and "DETRAN MA" in str(contrato).upper():
            if self._vazio(item):
                itens_possiveis = self._obter_itens_do_contrato(contrato)
                if "NOTEBOOK" in equip_nome:
                    item_sugerido = next((i for i in itens_possiveis if "NOTEBOOK" in str(i).upper()), None)
                else:
                    item_sugerido = next((i for i in itens_possiveis if "MICRO" in str(i).upper()), None)
                if item_sugerido: return contrato, item_sugerido
        return contrato, item
    
    def _regra_itens_poli_mono(self, cliente, equip_nome, contrato, item):
        if not self._vazio(contrato):
            palavras_impressao = ["MULTIFUNCIONAL", "IMPRESSORA", "MONO", "COLOR", "POLI", "JATO DE TINTA", "LASER"]
            pertence_a_regra = any(p in equip_nome for p in palavras_impressao)
            
            if pertence_a_regra:
                if self._vazio(item):
                    itens_possiveis = self._obter_itens_do_contrato(contrato)
                    item_sugerido = None
                    is_a3 = "A3" in equip_nome
                    
                    if "MONO" in equip_nome:
                        if is_a3:
                            item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i) and "A3" in normalizar(i)), None)
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i)), None)
                        else:
                            item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i) and "A4" in normalizar(i)), None)
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i) and "A3" not in normalizar(i)), None)
                    elif "COLOR" in equip_nome or "POLI" in equip_nome or "JATO DE TINTA" in equip_nome:
                        if is_a3:
                            item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i)) and "A3" in normalizar(i)), None)
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i))), None)
                        else:
                            item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i)) and "A4" in normalizar(i)), None)
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i)) and "A3" not in normalizar(i)), None)
                    
                    if item_sugerido:
                        return contrato, item_sugerido
        return contrato, item
    
    def _regra_itens_micro_notebook(self, cliente, equip_nome, contrato, item):
        """Regra Escalável: Triagem inteligente para famílias de Computadores e Notebooks."""
        if not self._vazio(contrato):
            
            # Palavras-chave que definem as famílias
            palavras_micro = ["THINKCENTRE", "MICRO", "COMPUTADOR", "DESKTOP", "PC", "CPU"]
            palavras_note = ["NOTEBOOK", "LAPTOP"]
            
            is_micro = any(p in equip_nome for p in palavras_micro)
            is_note = any(p in equip_nome for p in palavras_note)
            
            if is_micro or is_note:
                if self._vazio(item):
                    itens_possiveis = self._obter_itens_do_contrato(contrato)
                    item_sugerido = None
                    
                    if is_note:
                        # Varre os itens oficiais buscando algum que represente Notebook
                        item_sugerido = next((i for i in itens_possiveis if any(p in normalizar(i) for p in palavras_note)), None)
                    
                    elif is_micro:
                        # Varre os itens oficiais buscando algum que represente Micro/Desktop
                        item_sugerido = next((i for i in itens_possiveis if any(p in normalizar(i) for p in palavras_micro)), None)
                    
                    if item_sugerido:
                        return contrato, item_sugerido
                        
        return contrato, item
    
    def _regra_item_por_similaridade(self, cliente, equip_nome, contrato, item):
        if not self._vazio(contrato):
            if self._vazio(item):
                itens_oficiais = self._obter_itens_do_contrato(contrato)
                
                if itens_oficiais:
                    melhor_score = 0
                    melhor_match = None
                    
                    # Limpeza cirúrgica mantendo letras e números (I5, 700, A03, 32GB, 128GB)
                    equip_limpo = re.sub(r'[^A-Z0-9\s]', ' ', equip_nome.upper())
                    equip_expandido = f" {equip_limpo} "
                    sinonimos = {
                        " MICRO ": " MICROCOMPUTADOR PC DESKTOP ",
                        " PC ": " MICROCOMPUTADOR DESKTOP ",
                        " NOTE ": " NOTEBOOK LAPTOP ",
                        " TV ": " SMART TV TELEVISAO ",
                        " IMP ": " IMPRESSORA ",
                        " CELULAR ": " CELULAR SMARTPHONE ",
                        " SMARTPHONE ": " CELULAR SMARTPHONE "
                    }
                    
                    for abrev, expansao in sinonimos.items():
                        if abrev in equip_expandido:
                            # Adiciona a expansão na string base para a matemática do RapidFuzz cruzar os dados
                            equip_expandido = equip_expandido.replace(abrev, f" {expansao} ")
                            
                    equip_expandido = equip_expandido.strip()

                    for item_oficial in itens_oficiais:
                        # Limpa também o item do banco mantendo os números
                        item_limpo = re.sub(r'[^A-Z0-9\s]', ' ', str(item_oficial).upper()).strip()
                        
                        # O token_set_ratio isola as palavras em comum. '
                        # Ele vai capturar o "A03" e "32GB" perfeitamente e jogar a nota lá pra cima!
                        score = fuzz.token_set_ratio(equip_expandido, item_limpo)
                        
                        if score > melhor_score:
                            melhor_score = score
                            melhor_match = item_oficial
                            
                    # Ajustado para 65: captura perfeitamente as palavras exatas em comum
                    if melhor_score >= 65:
                        return contrato, melhor_match
                        
        return contrato, item
    
    def _regra_item_unico_fallback(self, cliente, equip_nome, contrato, item):
        """Regra Fallback: Se o contrato possui apenas 1 item no banco, atrela automaticamente."""
        # Só executa se o contrato está preenchido e o item sobreviveu vazio até aqui
        if not self._vazio(contrato) and self._vazio(item):
            itens_oficiais = self._obter_itens_do_contrato(contrato)
            
            # Se a lista de itens desse contrato tiver exatamente o tamanho 1
            if len(itens_oficiais) == 1:
                # Preenche com o único item existente!
                return contrato, itens_oficiais[0]
                
        return contrato, item
    # =======================================================================
    # 🔧 MÉTODOS AUXILIARES
    # =======================================================================
    def _obter_itens_do_contrato(self, contrato_texto):
        if not self.dict_mestre or self._vazio(contrato_texto):
            return []
            
        c_norm = normalizar(contrato_texto)
        chave = None
        
        if c_norm in self.dict_mestre:
            chave = c_norm
        else:
            chave = next((k for k in self.dict_mestre.keys() if k.startswith(c_norm + " ") or c_norm.startswith(k + " ")), None)
            
        if not chave:
            return []
            
        return [dados["apelido_original"] for dados in self.dict_mestre[chave]["itens"].values()]