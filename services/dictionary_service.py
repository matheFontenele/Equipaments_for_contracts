import pandas as pd
import numpy as np
import streamlit as st

from utils.text_processing import normalizar, valor_seguro_para_texto, MAPPINGS
from core.database import RELATORIO_BANCO_PATH, buscar_dados_por_orgao
from services.locking_service import remover_itens_travados

def construir_dicionario_mestre(df_contratos, df_itens):
    dict_map = {}
    if df_contratos.empty:
        return dict_map

    col_c_nome = "CONTRATOS" if "CONTRATOS" in df_contratos.columns else df_contratos.columns[0]
    col_c_id = "CONTRACT_ID" if "CONTRACT_ID" in df_contratos.columns else df_contratos.columns[0]

    for _, row in df_contratos.iterrows():
        c_bruto = row.get(col_c_nome)
        if pd.isna(c_bruto) or str(c_bruto).strip() == "":
            continue
        dict_map[normalizar(c_bruto)] = {"id": valor_seguro_para_texto(row.get(col_c_id)), "itens": {}}

    if df_itens.empty:
        return dict_map

    col_id_item = df_itens.columns[0]
    col_cont_item = "CONTRATO" if "CONTRATO" in df_itens.columns else df_itens.columns[2]
    col_apelido = "APELIDO" if "APELIDO" in df_itens.columns else df_itens.columns[3]
    col_desc = "DESCRICAO" if "DESCRICAO" in df_itens.columns else df_itens.columns[4]
    col_qtd = "QUANTIDADE" if "QUANTIDADE" in df_itens.columns else df_itens.columns[5]

    for _, row in df_itens.iterrows():
        c_bruto = row.get(col_cont_item)
        i_bruto = row.get(col_apelido)
        if pd.isna(c_bruto) or pd.isna(i_bruto) or str(c_bruto).strip() == "" or str(i_bruto).strip() == "":
            continue

        c_norm = normalizar(c_bruto)
        i_norm = normalizar(i_bruto)
        
        chave_contrato = next((key for key in dict_map.keys() if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key)), None)
                
        if chave_contrato:
            id_evento_raw = pd.to_numeric(row.get(col_id_item), errors='coerce')
            id_evento = int(id_evento_raw) if pd.notna(id_evento_raw) else 0

            if i_norm not in dict_map[chave_contrato]["itens"] or id_evento > dict_map[chave_contrato]["itens"][i_norm]["evento"]:
                dict_map[chave_contrato]["itens"][i_norm] = {
                    "evento": id_evento,
                    "descricao": valor_seguro_para_texto(row.get(col_desc)),
                    "quantidade": valor_seguro_para_texto(row.get(col_qtd)),
                    "apelido_original": str(i_bruto).strip()
                }
    return dict_map

def obter_itens_do_contrato(contrato_bruto):
    dict_mestre = st.session_state.get("dict_mestre", {})
    if not dict_mestre or pd.isna(contrato_bruto) or str(contrato_bruto).strip() == "":
        return []

    c_norm = normalizar(contrato_bruto)
    chave_contrato = next((key for key in dict_mestre.keys() if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key)), None)
    if not chave_contrato:
        return []

    return sorted({item_info["apelido_original"] for item_info in dict_mestre[chave_contrato]["itens"].values()})

def aplicar_automacao_no_dataframe(df_aba):
    dict_mestre = st.session_state.get("dict_mestre", {})
    if df_aba is None or df_aba.empty or not dict_mestre:
        return df_aba

    df_aba = df_aba.copy()

    def validar_e_preencher(row):
        contrato_atual = row.get("CONTRATO")
        item_atual = row.get("ITEM_DO_CONTRATO")

        if pd.isna(contrato_atual) or str(contrato_atual).strip() == "":
            return pd.Series([None, None, None, None, True])

        c_norm = normalizar(contrato_atual)
        chave_contrato = next((key for key in dict_mestre.keys() if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key)), None)
        if not chave_contrato:
            return pd.Series([None, None, None, None, True])
            
        contract_id = dict_mestre[chave_contrato]["id"]

        if pd.isna(item_atual) or str(item_atual).strip() == "" or str(item_atual) == '⬇ selecione um item':
            return pd.Series([contract_id, None, None, None, False])

        i_norm = normalizar(item_atual)
        if i_norm in dict_mestre[chave_contrato]["itens"]:
            dados = dict_mestre[chave_contrato]["itens"][i_norm]
            return pd.Series([contract_id, dados["descricao"], dados["quantidade"], str(dados["evento"]), False])
            
        return pd.Series([contract_id, None, None, None, True])

    resultados = df_aba.apply(validar_e_preencher, axis=1)
    df_aba["CONTRACT_ID"] = resultados[0]
    df_aba["DESCRICAO_ITEM"] = resultados[1]
    df_aba["QUANTIDADE_ITEM_NO_CONTRATO"] = resultados[2]
    df_aba["ID_EVENTO"] = resultados[3]

    erros_mask = resultados[4] == True
    if erros_mask.sum() > 0:
        for col in ["ITEM_DO_CONTRATO", "DESCRICAO_ITEM", "QUANTIDADE_ITEM_NO_CONTRATO", "ID_EVENTO"]:
            df_aba.loc[erros_mask, col] = None

    return df_aba

def montar_colunas_base(df_bruto, aba):
    df_montado = pd.DataFrame()
    df_montado['CLIENTE_ID'] = df_bruto['id_cliente'].apply(valor_seguro_para_texto)
    df_montado['CLIENTE_NOME'] = df_bruto['nome_cliente'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_ID'] = df_bruto['id_equipamento'].apply(valor_seguro_para_texto)
    df_montado['TOMBO'] = df_bruto['tombo'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_NOME'] = df_bruto['nome_equipamentos'].apply(valor_seguro_para_texto)
    df_montado['ORGAO_ID'] = df_bruto['orgao_id'].apply(valor_seguro_para_texto)

    colunas_restantes = ["CONTRACT_ID", "CONTRATO", "ITEM_DO_CONTRATO", "DESCRICAO_ITEM",
                         "QUANTIDADE_ITEM_NO_CONTRATO", "ID_EVENTO", "TIPO_EQUIPAMENTO"]
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

def sincronizar_todas_as_abas(engine):
    lista_dfs_brutos = []
    for aba, lista_ids in MAPPINGS.items():
        df_bruto = buscar_dados_por_orgao(engine, lista_ids)
        df_bruto['aba_origem'] = aba
        lista_dfs_brutos.append(df_bruto)
        st.session_state[aba] = construir_tabela_organizacao(df_bruto, aba)

    if lista_dfs_brutos:
        df_relatorio = pd.concat(lista_dfs_brutos, ignore_index=True)
        st.session_state["df_relatorio"] = df_relatorio
        RELATORIO_BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
        df_relatorio.to_csv(RELATORIO_BANCO_PATH, index=False)
