import pandas as pd
from rapidfuzz import fuzz
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
            self._regra_contrato_por_similaridade, # 4º: Motor de Contratos Inteligente
            self._regra_item_detran_ma,            # 5º: Regras específicas de Itens
            self._regra_itens_poli_mono,           # 6º: Triagem Impressoras
            self._regra_item_por_similaridade      # 7º: NOVO! Motor Universal de Itens via IA
        ] 

    def processar_linha(self, row):
        contrato_atual = row.get('CONTRATO')
        item_atual = row.get('ITEM_DO_CONTRATO')
        cliente = str(row.get('CLIENTE_NOME', '')).upper()
        equip_nome = str(row.get('EQUIPAMENTO_NOME', '')).upper()

        # =================================================================
        # 1. 🚫 ESCUDO DA BLACKLIST (Entrada)
        # =================================================================
        cliente_tratado = cliente.strip()
        for ignorado in CLIENTES_IGNORADOS:
            if ignorado in cliente_tratado or cliente_tratado in ignorado:
                return pd.Series([None, None])

        # =================================================================
        # 2. MOTOR DE REGRAS (Tenta descobrir Contrato e Item)
        # =================================================================
        for regra in self.regras:
            if pd.notna(contrato_atual) and str(contrato_atual).strip() != "" and \
               pd.notna(item_atual) and str(item_atual).strip() != "":
                break
            contrato_atual, item_atual = regra(cliente, equip_nome, contrato_atual, item_atual)

        # =================================================================
        # 3. 🛡️ ESCUDO DE KITS (Saída / Pós-Processamento)
        # =================================================================
        # Se depois de passar por todas as regras o equipamento ainda for suspeito de ser KIT...
        is_kit = any(str(cat).upper() in equip_nome for cat in IS_KIT)
        
        if is_kit:
            # Se o nosso motor universal de itens (RapidFuzz) conseguiu achar um item 
            # oficial no contrato, nós damos o SALVO-CONDUTO!
            if pd.notna(item_atual) and str(item_atual).strip() != "":
                pass 
            else:
                # É kit (ex: teclado) e não achou item oficial faturável no contrato? Ejeta!
                return pd.Series([None, None])

        return pd.Series([contrato_atual, item_atual])

    # =======================================================================
    # 📚 BIBLIOTECA DE REGRAS
    # =======================================================================

    # ... [MANTENHA AQUI AS REGRAS QUE VOCÊ JÁ TEM: _regra_de_para_explicito, MTE, MT, Similaridade, Detran_MA, Poli_Mono] ...
    
    # Adicione a nova regra UNIVERSAL de itens logo abaixo da regra das Mono/Poli:

    def _regra_item_por_similaridade(self, cliente, equip_nome, contrato, item):
        """Regra Universal: Associa o equipamento ao item do contrato via IA (Fuzzy Matching)"""
        # Só tenta preencher se o contrato já estiver preenchido e o item ainda vazio
        if pd.notna(contrato) and str(contrato).strip() != "":
            if pd.isna(item) or str(item).strip() == "":
                
                # Puxa os itens oficiais que existem cadastrados para este contrato
                itens_oficiais = self._obter_itens_do_contrato(contrato)
                
                if itens_oficiais:
                    melhor_score = 0
                    melhor_match = None
                    
                    for item_oficial in itens_oficiais:
                        # fuzz.token_set_ratio: Acha a palavra-chave mesmo misturada em outras
                        # Ex: "NOBREAK SMS 1.5KVA NS" vai dar match perfeito com "NOBREAK 1,5 KVA"
                        score = fuzz.token_set_ratio(equip_nome, str(item_oficial).upper())
                        
                        if score > melhor_score:
                            melhor_score = score
                            melhor_match = item_oficial
                            
                    # Se a similaridade for boa (acima de 70%), ele preenche a tela automaticamente!
                    if melhor_score >= 70:
                        item = melhor_match
                        
        return contrato, item

    # =======================================================================
    # 🔧 MÉTODOS AUXILIARES
    # =======================================================================
    def _obter_itens_do_contrato(self, contrato_texto):
        """Busca rápida no dict_mestre para saber os itens que um contrato possui."""
        if not self.dict_mestre or pd.isna(contrato_texto):
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