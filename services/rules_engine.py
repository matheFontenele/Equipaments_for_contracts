import pandas as pd
import re
from rapidfuzz import fuzz
from utils.text_processing import normalizar
from core.config import IS_KIT, DE_PARA_CLIENTES, CLIENTES_IGNORADOS, SUBSTITUICOES_TERMOS, CONTRATOS_POLI_MONO

class MotorDeRegras:
    def __init__(self, opcoes_contratos, dict_mestre):
        self.opcoes_contratos = opcoes_contratos
        self.dict_mestre = dict_mestre
        
        # 🧠 O CÉREBRO
        self.regras = [
            self._regra_de_para_explicito,         
            self._regra_contrato_mte,              
            self._regra_contrato_mt,               
            self._regra_contrato_por_similaridade, 
            self._regra_item_detran_ma,            
            self._regra_itens_poli_mono,           
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
            else:
                # É kit e não tem item oficial? Ejeta!
                return pd.Series([None, None])

        return pd.Series([contrato_atual, item_atual])

    # =======================================================================
    # 📚 BIBLIOTECA DE REGRAS
    # =======================================================================

    def _regra_de_para_explicito(self, cliente, equip_nome, contrato, item):
        if self._vazio(contrato):
            cliente_tratado = cliente.strip()
            for chave_suja, contrato_correto in DE_PARA_CLIENTES.items():
                if chave_suja in cliente_tratado or cliente_tratado in chave_suja:
                    for opcao in self.opcoes_contratos:
                        if str(opcao).upper().strip() == contrato_correto.upper().strip():
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

    def _regra_contrato_por_similaridade(self, cliente, equip_nome, contrato, item):
        if self._vazio(contrato):
            cliente_limpo = str(cliente).upper().strip()
            
            # Limpa o cliente com os De-Para de termos
            for termo_original, substituto in SUBSTITUICOES_TERMOS.items():
                cliente_limpo = cliente_limpo.replace(termo_original, substituto)
                
            cliente_limpo = cliente_limpo.replace('-', ' ').replace('/', ' ').strip()
            
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
            # 1. TESTE RÁPIDO: Substring Exata Bidirecional
            # =================================================================
            for c in opcoes_permitidas:
                contrato_limpo = str(c).upper().replace('-', ' ').replace('/', ' ').strip()
                
                if contrato_limpo in cliente_limpo:
                    return c, item
                    
                if len(cliente_limpo) >= 4 and cliente_limpo in contrato_limpo:
                    return c, item

            # =================================================================
            # 2. TESTE DE COBERTURA: Fatias de palavras com Cobertura Reversa
            # =================================================================
            palavras_cliente = set(cliente_limpo.split())
            stop_words = {"DE", "DA", "DO", "DAS", "DOS", "SECRETARIA", "DEPARTAMENTO", "ESTADUAL", "MUNICIPAL", "CONTRATO", "SEC", "ADM", "P", "M"}
            palavras_chave_cliente = palavras_cliente - stop_words

            melhor_match = None
            maior_score = 0.0

            for c in opcoes_permitidas:
                contrato_limpo = str(c).upper().replace('-', ' ').replace('/', ' ')
                palavras_contrato = set(contrato_limpo.split())
                palavras_chave_contrato = palavras_contrato - stop_words
                
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

    def _regra_item_por_similaridade(self, cliente, equip_nome, contrato, item):
        if not self._vazio(contrato):
            if self._vazio(item):
                itens_oficiais = self._obter_itens_do_contrato(contrato)
                
                if itens_oficiais:
                    melhor_score = 0
                    melhor_match = None
                    
                    # Limpeza cirúrgica mantendo números (I5, 700)
                    equip_limpo = re.sub(r'[^A-Z0-9\s]', ' ', equip_nome.upper())
                    equip_expandido = f" {equip_limpo} "
                    
                    sinonimos = {
                        " MICRO ": " MICROCOMPUTADOR ",
                        " PC ": " MICROCOMPUTADOR ",
                        " NOTE ": " NOTEBOOK ",
                        " TV ": " SMART TV ",
                        " IMP ": " IMPRESSORA "
                    }
                    for abrev, completo in sinonimos.items():
                        equip_expandido = equip_expandido.replace(abrev, completo)
                    equip_expandido = equip_expandido.strip()

                    for item_oficial in itens_oficiais:
                        # Limpa também o item do banco mantendo números
                        item_limpo = re.sub(r'[^A-Z0-9\s]', ' ', str(item_oficial).upper()).strip()
                        
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