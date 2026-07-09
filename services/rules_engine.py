import pandas as pd
import difflib
from utils.text_processing import normalizar

class MotorDeRegras:
    def __init__(self, opcoes_contratos, dict_mestre):
        self.opcoes_contratos = opcoes_contratos
        self.dict_mestre = dict_mestre
        
        # 🧠 O CÉREBRO: Registe aqui as suas regras por ordem de prioridade.
        # O motor vai executar uma por uma de cima para baixo.
        self.regras = [
            self._regra_contrato_por_similaridade,
            self._regra_contrato_mte
        ]

    def processar_linha(self, row):
        """Função principal que o Pandas vai chamar para cada linha da tabela."""
        contrato_atual = row.get('CONTRATO')
        item_atual = row.get('ITEM_DO_CONTRATO')
        cliente = str(row.get('CLIENTE_NOME', '')).upper()
        equip_nome = str(row.get('EQUIPAMENTO_NOME', '')).upper()

        # Passa a linha por todas as regras registadas
        for regra in self.regras:
            # Se a linha já tem contrato e item preenchidos, não perde tempo, salta fora.
            if pd.notna(contrato_atual) and str(contrato_atual).strip() != "" and \
               pd.notna(item_atual) and str(item_atual).strip() != "":
                break
            
            # Executa a regra atual
            contrato_atual, item_atual = regra(cliente, equip_nome, contrato_atual, item_atual)

        return pd.Series([contrato_atual, item_atual])

    # =======================================================================
    # 📚 BIBLIOTECA DE REGRAS (Adicione novas regras abaixo)
    # =======================================================================

    def _regra_contrato_mte(self, cliente, equip_nome, contrato, item):
        """Se o cliente tem MTE no nome, procura o contrato do MTE."""
        if pd.isna(contrato) or contrato == "":
            if "MTE" in cliente:
                for c in self.opcoes_contratos:
                    if "MTE" in str(c).upper():
                        contrato = c
                        break
        return contrato, item

    def _regra_contrato_por_similaridade(self, cliente, equip_nome, contrato, item):
        """Atrela automaticamente contratos que tenham o nome muito similar ao do cliente"""
        # Só tenta preencher se o contrato estiver vazio
        if pd.isna(contrato) or str(contrato).strip() == "":
            cliente_limpo = str(cliente).upper().strip()
            
            melhor_match = None
            maior_pontuacao = 0.65

            for c in self.opcoes_contratos:
                # Ignoramos opções vazias que usamos para limpar a tela
                if not c or str(c).strip() == "":
                    continue
                    
                contrato_limpo = str(c).upper().strip()

                # TESTE 1: Substring perfeita
                if cliente_limpo in contrato_limpo or contrato_limpo in cliente_limpo:
                    return c, item

                # TESTE 2: Similaridade por erro de digitação
                similaridade = difflib.SequenceMatcher(None, cliente_limpo, contrato_limpo).ratio()
                if similaridade > maior_pontuacao:
                    maior_pontuacao = similaridade
                    melhor_match = c

            if melhor_match:
                contrato = melhor_match

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