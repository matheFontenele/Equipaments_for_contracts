import pandas as pd
import numpy as np
import streamlit as st

from utils.text_processing import normalizar, valor_seguro_para_texto, MAPPINGS
from core.database import RELATORIO_BANCO_PATH, buscar_dados_por_orgao
from services.locking_service import remover_itens_travados

def construir_dicionario_mestre(df_banco):
    dict_map = {}
    if df_banco is None or df_banco.empty:
        return dict_map

    for _, row in df_banco.iterrows():
        # Dados do Contrato
        contrato_id = row.get('contract_id')
        contrato_nome = str(row.get('contract_name', '')).strip().upper()
        
        # Dados do Item
        item_id = row.get('contract_item_id')
        item_nome = str(row.get('contract_item_alias', '')).strip()

        if pd.isna(contrato_nome) or contrato_nome == "":
            continue
            
        c_norm = normalizar(contrato_nome)
        
        # 1. Cria o nó do Contrato se não existir
        if c_norm not in dict_map:
            dict_map[c_norm] = {
                "id": contrato_id,
                "nome_original": contrato_nome,
                "itens": {}
            }
            
        # 2. Adiciona o Item (se existir) atrelado ao Contrato
        if pd.notna(item_nome) and item_nome != "":
            i_norm = normalizar(item_nome)
            dict_map[c_norm]["itens"][i_norm] = {
                "id": item_id,
                "apelido_original": item_nome,
                "quantidade_total": row.get('quantity'),
                "quantidade_disponivel": row.get('available_quantity')
            }
            
    return dict_map

def obter_itens_do_contrato(contrato_bruto):
    """Retorna os nomes dos itens (apelidos) disponíveis para o dropdown do Streamlit."""
    dict_mestre = st.session_state.get("dict_mestre", {})
    if not dict_mestre or pd.isna(contrato_bruto) or str(contrato_bruto).strip() == "":
        return []

    c_norm = normalizar(contrato_bruto)
    chave_contrato = next((key for key in dict_mestre.keys() if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key)), None)
    
    if not chave_contrato:
        return []

    return sorted({item_info["apelido_original"] for item_info in dict_mestre[chave_contrato]["itens"].values()})

def aplicar_automacao_no_dataframe(df_aba):
    """
    Valida as escolhas do usuário/IA e preenche as colunas oficiais de ID do banco de dados 
    (CONTRACT_ID e CONTRACT_ITEM_ID) em tempo real.
    """
    dict_mestre = st.session_state.get("dict_mestre", {})
    if df_aba is None or df_aba.empty or not dict_mestre:
        return df_aba

    df_aba = df_aba.copy()

    def validar_e_preencher(row):
        contrato_atual = row.get("CONTRATO")
        item_atual = row.get("ITEM_DO_CONTRATO")

        # Sem contrato? Tudo nulo.
        if pd.isna(contrato_atual) or str(contrato_atual).strip() == "":
            return pd.Series([None, None, True])

        c_norm = normalizar(contrato_atual)
        chave_contrato = next((key for key in dict_mestre.keys() if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key)), None)
        
        # Contrato digitado não existe no banco? Falha.
        if not chave_contrato:
            return pd.Series([None, None, True])
            
        contract_id = dict_mestre[chave_contrato]["id"]

        # Tem contrato mas não tem item? Retorna só o ID do contrato.
        if pd.isna(item_atual) or str(item_atual).strip() == "" or str(item_atual) == '⬇ selecione um item':
            return pd.Series([contract_id, None, False])

        i_norm = normalizar(item_atual)
        
        # Item válido? Retorna ID do Contrato e ID do Item.
        if i_norm in dict_mestre[chave_contrato]["itens"]:
            item_id = dict_mestre[chave_contrato]["itens"][i_norm]["id"]
            return pd.Series([contract_id, item_id, False])
            
        # Falhou na validação do item
        return pd.Series([contract_id, None, True])

    resultados = df_aba.apply(validar_e_preencher, axis=1)
    df_aba["CONTRACT_ID"] = resultados[0]
    df_aba["CONTRACT_ITEM_ID"] = resultados[1]

    # Limpa as células onde a validação falhou (erros_mask = True)
    erros_mask = resultados[2] == True
    if erros_mask.sum() > 0:
        df_aba.loc[erros_mask, "ITEM_DO_CONTRATO"] = None
        df_aba.loc[erros_mask, "CONTRACT_ITEM_ID"] = None

    return df_aba

def montar_colunas_base(df_bruto, aba):
    df_montado = pd.DataFrame()
    df_montado['CLIENTE_ID'] = df_bruto['id_cliente'].apply(valor_seguro_para_texto)
    df_montado['CLIENTE_NOME'] = df_bruto['nome_cliente'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_ID'] = df_bruto['id_equipamento'].apply(valor_seguro_para_texto)
    df_montado['TOMBO'] = df_bruto['tombo'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_NOME'] = df_bruto['nome_equipamentos'].apply(valor_seguro_para_texto)
    df_montado['ORGAO_ID'] = df_bruto['orgao_id'].apply(valor_seguro_para_texto)

    # Substituímos as colunas legadas pelo CONTRACT_ITEM_ID
    colunas_restantes = ["CONTRACT_ID", "CONTRATO", "CONTRACT_ITEM_ID", "ITEM_DO_CONTRATO", "TIPO_EQUIPAMENTO", "IS_EXTRA_KIT"]
    for col in colunas_restantes:
        df_montado[col] = None

    if aba in st.session_state and not st.session_state[aba].empty:
        df_existente = st.session_state[aba]
        if 'EQUIPAMENTO_ID' in df_existente.columns:
            map_contrato = df_existente.dropna(subset=['CONTRATO']).set_index('EQUIPAMENTO_ID')['CONTRATO'].to_dict()
            map_item = df_existente.dropna(subset=['ITEM_DO_CONTRATO']).set_index('EQUIPAMENTO_ID')['ITEM_DO_CONTRATO'].to_dict()
            df_montado['CONTRATO'] = df_montado['EQUIPAMENTO_ID'].map(map_contrato).replace({np.nan: None})
            df_montado['ITEM_DO_CONTRATO'] = df_montado['EQUIPAMENTO_ID'].map(map_item).replace({np.nan: None})

    return df_montado

def construir_tabela_organizacao(df_bruto, aba):
    df_montado = montar_colunas_base(df_bruto, aba)
    df_montado = aplicar_automacao_no_dataframe(df_montado)
    df_montado = remover_itens_travados(df_montado, aba)
    return df_montado

def sincronizar_todas_as_abas(engine_legado):
    """
    Busca os dados de equipamentos do banco legado e monta as abas do Streamlit.
    """
    lista_dfs_brutos = []
    for aba, lista_ids in MAPPINGS.items():
        df_bruto = buscar_dados_por_orgao(engine_legado, lista_ids)
        df_bruto['aba_origem'] = aba
        lista_dfs_brutos.append(df_bruto)
        st.session_state[aba] = construir_tabela_organizacao(df_bruto, aba)

    if lista_dfs_brutos:
        df_relatorio = pd.concat(lista_dfs_brutos, ignore_index=True)
        st.session_state["df_relatorio"] = df_relatorio
        RELATORIO_BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
        df_relatorio.to_csv(RELATORIO_BANCO_PATH, index=False)