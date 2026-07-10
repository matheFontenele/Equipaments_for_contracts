import pandas as pd
import difflib
from utils.text_processing import normalizar
from core.config import IS_KIT, DE_PARA_CLIENTES, CLIENTES_IGNORADOS, SUBSTITUICOES_TERMOS, CONTRATOS_POLI_MONO

class MotorDeRegras:
    def __init__(self, opcoes_contratos, dict_mestre):
        self.opcoes_contratos = opcoes_contratos
        self.dict_mestre = dict_mestre
        
        # 🧠 O CÉREBRO
        self.regras = [
            self._regra_de_para_explicito,         # 1º: Valida se está forçado no DE/PARA
            self._regra_contrato_mte,              # 2º: Regra estática do MTE
            self._regra_contrato_mt,               # 3º: Regra estática do MT
            self._regra_contrato_por_similaridade, # 4º: O motor analítico inteligente
            self._regra_item_detran_ma ,           # 5º: Regras de Itens (rodam após o contrato estar preenchido)
            self._regra_itens_poli_mono            # 6º: Triagem de Itens POICROMATICAS E MONOCROMATICAS
        ] 

    def processar_linha(self, row):
        """Função principal que o Pandas vai chamar para cada linha da tabela."""
        contrato_atual = row.get('CONTRATO')
        item_atual = row.get('ITEM_DO_CONTRATO')
        cliente = str(row.get('CLIENTE_NOME', '')).upper()
        equip_nome = str(row.get('EQUIPAMENTO_NOME', '')).upper()

        if pd.isna(contrato_atual) or str(contrato_atual).strip() == "":
            
            # 1. 🛡️ ESCUDO DE KITS
            for cat in IS_KIT:
                if str(cat).upper() in equip_nome:
                    # É um kit periférico! Retorna o estado atual vazio e sai do motor.
                    return pd.Series([contrato_atual, item_atual])
                    
            # 2. 🚫 ESCUDO DA BLACKLIST (CLIENTES IGNORADOS)
            cliente_tratado = cliente.strip()
            for ignorado in CLIENTES_IGNORADOS:
                # Se o cliente bater com algum nome da nossa blacklist
                if ignorado in cliente_tratado or cliente_tratado in ignorado:
                    # Ejeta do motor imediatamente, mantendo o contrato em branco
                    return pd.Series([contrato_atual, item_atual])

        # Passa a linha pelas regras de associação automática caso não tenha sido bloqueada
        for regra in self.regras:
            if pd.notna(contrato_atual) and str(contrato_atual).strip() != "" and \
               pd.notna(item_atual) and str(item_atual).strip() != "":
                break
            
            # Executa a regra atual
            contrato_atual, item_atual = regra(cliente, equip_nome, contrato_atual, item_atual)

        return pd.Series([contrato_atual, item_atual])

    # =======================================================================
    # 📚 BIBLIOTECA DE REGRAS
    # =======================================================================

    def _regra_de_para_explicito(self, cliente, equip_nome, contrato, item):
        """Regra de Curto-Circuito: Atrela um contrato forçado caso mapeado na UI"""
        if pd.isna(contrato) or str(contrato).strip() == "":
            cliente_tratado = cliente.strip()
            for chave_suja, contrato_correto in DE_PARA_CLIENTES.items():
                if chave_suja in cliente_tratado or cliente_tratado in chave_suja:
                    # Valida se o contrato mapeado existe na lista de opções ativas
                    for opcao in self.opcoes_contratos:
                        if str(opcao).upper().strip() == contrato_correto.upper().strip():
                            return opcao, item
        return contrato, item

    def _regra_contrato_mte(self, cliente, equip_nome, contrato, item):
        """Se o cliente tem MTE no nome, procura o contrato do MTE."""
        if pd.isna(contrato) or contrato == "":
            if "MTE" in cliente:
                for c in self.opcoes_contratos:
                    if "MTE" in str(c).upper():
                        contrato = c
                        break
        return contrato, item

    def _regra_contrato_mt(self, cliente, equip_nome, contrato, item):
        """Se o cliente é o Ministério dos Transportes, atrela o contrato MT blindando contra a sigla MTE."""
        if pd.isna(contrato) or contrato == "":
            if "MINISTERIO DOS TRANSPORTE" in cliente or "MINISTÉRIO DOS TRANSPORTE" in cliente:
                for c in self.opcoes_contratos:
                    c_limpo = str(c).upper().strip()
                    # Procura o contrato "MT" exato, evitando esbarrar no "MTE"
                    if c_limpo == "MT" or c_limpo.startswith("MT -") or c_limpo.startswith("MT "):
                        contrato = c
                        break
        return contrato, item

    def _regra_contrato_por_similaridade(self, cliente, equip_nome, contrato, item):
        """Atrela contratos buscando interseção forte de palavras-chave (Anti Falso-Positivo)"""
        if pd.isna(contrato) or str(contrato).strip() == "":
            
            cliente_limpo = str(cliente).upper()
            
            for termo_original, substituto in SUBSTITUICOES_TERMOS.items():
                cliente_limpo = cliente_limpo.replace(termo_original, substituto)
                
            cliente_limpo = cliente_limpo.replace('-', ' ').replace('/', ' ')
            
            #  FILTRO DE ISOLAMENTO DE CONTRATOS RESTRITOS
            opcoes_permitidas = []
            for c in self.opcoes_contratos:
                if not c or str(c).strip() == "":
                    continue
                
                c_upper = str(c).upper().strip()
                # Se for o contrato MT, esconde ele da lista a menos que o cliente seja de TRANSPORTE
                if c_upper == "MT" or c_upper.startswith("MT -") or c_upper.startswith("MT "):
                    if "TRANSPORTE" not in cliente_limpo:
                        continue # Pula este contrato, deixando-o invisível para este cliente
                
                opcoes_permitidas.append(c)

            # 1. TESTE RÁPIDO: Substring Exata (Agora itera sobre opcoes_permitidas)
            for c in opcoes_permitidas:
                contrato_limpo = str(c).upper().replace('-', ' ').replace('/', ' ')
                if contrato_limpo in cliente_limpo:
                    return c, item

            # 2. TESTE DE COBERTURA: Compara as fatias de palavras
            palavras_cliente = set(cliente_limpo.split())
            stop_words = {"DE", "DA", "DO", "DAS", "DOS", "SECRETARIA", "DEPARTAMENTO", "ESTADUAL", "MUNICIPAL", "CONTRATO", "SEC", "ADM", "P", "M"}
            palavras_chave_cliente = palavras_cliente - stop_words

            melhor_match = None
            maior_score = 0.0

            # (Agora itera sobre opcoes_permitidas aqui também)
            for c in opcoes_permitidas:
                contrato_limpo = str(c).upper().replace('-', ' ').replace('/', ' ')
                palavras_contrato = set(contrato_limpo.split())
                palavras_chave_contrato = palavras_contrato - stop_words
                
                if not palavras_chave_contrato:
                    continue

                intersecao = palavras_chave_cliente.intersection(palavras_chave_contrato)
                
                # Porcentagem de aderência (Evita que o DETRAN CASCAVEL puxe o DETRAN MA)
                score_cobertura = len(intersecao) / len(palavras_chave_contrato)
                
                if score_cobertura == 1.0:
                    return c, item
                    
                if score_cobertura > 0.7 and score_cobertura > maior_score:
                    maior_score = score_cobertura
                    melhor_match = c

            if melhor_match:
                return melhor_match, item

        return contrato, item

    def _regra_item_detran_ma(self, cliente, equip_nome, contrato, item):
            """Regra Específica: Triagem de Itens para o DETRAN MA (NOTEBOOK vs MICRO)"""
            # Só executa se o contrato já estiver preenchido e pertencer ao DETRAN MA
            if pd.notna(contrato) and str(contrato).strip() != "":
                if "DETRAN MA" in str(contrato).upper():
                    
                    # Só tenta preencher o item se ele ainda estiver vazio
                    if pd.isna(item) or str(item).strip() == "":
                        
                        # Puxa a lista de itens oficiais desse contrato no dicionário
                        itens_possiveis = self._obter_itens_do_contrato(contrato)
                        
                        if "NOTEBOOK" in equip_nome:
                            # Busca o item oficial que representa o Notebook
                            item_sugerido = next((i for i in itens_possiveis if "NOTEBOOK" in str(i).upper()), None)
                        else:
                            # Se não tem a palavra NOTEBOOK, o fallback absoluto é MICRO
                            item_sugerido = next((i for i in itens_possiveis if "MICRO" in str(i).upper()), None)
                        
                        if item_sugerido:
                            item = item_sugerido
                            
            return contrato, item
   
    def _regra_itens_poli_mono(self, cliente, equip_nome, contrato, item):
        """Regra Escalável: Triagem MONO vs COLOR e Formato A3 vs A4 baseada em Nomes de Contrato"""
        if pd.notna(contrato) and str(contrato).strip() != "":
            contrato_upper = str(contrato).upper()
            
            # 1. Varre a lista do config e verifica se o nome bate com a nossa regra
            pertence_a_regra = any(str(nome).upper() in contrato_upper for nome in CONTRATOS_POLI_MONO)
            
            if pertence_a_regra:
                if pd.isna(item) or str(item).strip() == "":
                    itens_possiveis = self._obter_itens_do_contrato(contrato)
                    item_sugerido = None
                    
                    # Identifica se é uma máquina A3 (se não for, assumimos A4/Padrão)
                    is_a3 = "A3" in equip_nome
                    
                    # ==========================================
                    # LÓGICA PARA MONOCROMÁTICAS
                    # ==========================================
                    if "MONO" in equip_nome:
                        if is_a3:
                            item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i) and "A3" in normalizar(i)), None)
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i)), None)
                        else:
                            item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i) and "A4" in normalizar(i)), None)
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if "MONO" in normalizar(i) and "A3" not in normalizar(i)), None)
                                
                    # ==========================================
                    # LÓGICA PARA POLICROMÁTICAS (COLOR)
                    # ==========================================
                    # Se o equipamento tiver a palavra COLOR (pega colorido/a) OU POLI (pega policromático/a)
                    elif "COLOR" in equip_nome or "POLI" in equip_nome or "JATO DE TINTA" in equip_nome:
                        if is_a3:
                            # O item do contrato pode ser Poli ou Color. Qualquer um serve!
                            item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i)) and "A3" in normalizar(i)), None)
                            
                            if not item_sugerido:
                                item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i))), None)
                        else:
                            # Tenta achar com a flag A4 explícita
                            item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i)) and "A4" in normalizar(i)), None)
                            
                            if not item_sugerido:
                                # Se não achar a flag A4, aceita qualquer Jato de Tinta, Color ou Poli (desde que não seja A3)
                                item_sugerido = next((i for i in itens_possiveis if ("POLI" in normalizar(i) or "COLOR" in normalizar(i) or "JATO DE TINTA" in normalizar(i)) and "A3" not in normalizar(i)), None)
                    
                    # Se encontrou o item perfeito na matriz (Cor + Tamanho), aplica!
                    if item_sugerido:
                        item = item_sugerido
                        
        return contrato, item
   # =======================================================================
    # 🔧 MÉTODOS AUXILIARES
    # =======================================================================
    def _obter_itens_do_contrato(self, contrato_texto):
        """Busca rápida no dict_mestre para saber os itens que um contrato possui."""
        if not self.dict_mestre or pd.isna(contrato_texto):
            return []
        c_norm = normalizar(contrato_texto)
        chave = next((k for k in self.dict_mestre.keys() if k.startswith(c_norm) or c_norm.startswith(k)), None)
        if not chave:
            return []
        return [dados["apelido_original"] for dados in self.dict_mestre[chave]["itens"].values()]
