import pandas as pd
import numpy as np
import streamlit as st

from utils.text_processing import (
    normalizar,
    valor_seguro_para_texto,
    tokens_municipio,
    MAPPINGS,
    aba_da_organizacao,
)
from core.database import RELATORIO_BANCO_PATH, buscar_dados_por_orgao
from services.locking_service import remover_itens_travados

def construir_dicionario_mestre(df_banco, aba=None):
    """Monta o dicionário contrato → itens.

    Com ``aba`` definida, considera apenas os contratos da empresa daquela aba
    (``contracts.organization_id``). Contratos cujo órgão não pertence a nenhum
    MAPPING continuam valendo para todas as abas, para não sumirem do sistema.
    """
    dict_map = {}
    if df_banco is None or df_banco.empty:
        return dict_map

    if aba is not None and "contract_organization_id" in df_banco.columns:
        abas_do_contrato = df_banco["contract_organization_id"].map(aba_da_organizacao)
        df_banco = df_banco[(abas_do_contrato == aba) | abas_do_contrato.isna()]

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
                "municipios": set(),
                "itens": {}
            }

        # Município do cliente do contrato: evita casar, por exemplo, o
        # "GABINETE DO PREFEITO" de Maranguape com o cliente de Baturité.
        dict_map[c_norm]["municipios"].update(
            tokens_municipio(row.get("cutomer_name"))
        )
            
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

def construir_dicionarios_por_aba(df_banco):
    """Um dicionário de contratos por aba — evita que um contrato de outra
    empresa seja usado e que homônimos ("GABINETE DO PREFEITO" em ALUCOM e
    MOREIA) colidam na mesma chave."""
    return {aba: construir_dicionario_mestre(df_banco, aba) for aba in MAPPINGS}

def obter_itens_do_contrato(aba, contrato_bruto, dict_mestre=None):
    """Retorna os nomes dos itens (apelidos) disponíveis para o dropdown do Streamlit."""
    if dict_mestre is None:
        dict_mestre = st.session_state.get("dict_mestre", {}).get(aba, {})
    if not dict_mestre or pd.isna(contrato_bruto) or str(contrato_bruto).strip() == "":
        return []

    c_norm = normalizar(contrato_bruto)
    chave_contrato = next((key for key in dict_mestre.keys() if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key)), None)
    
    if not chave_contrato:
        return []

    return sorted({item_info["apelido_original"] for item_info in dict_mestre[chave_contrato]["itens"].values()})

# Colunas de classificação preenchidas pelo usuário na tabela.
COLUNAS_FLAGS = ("IS_EXTRA_KIT", "IS_AVULSO")
# Flags que são zeradas ("Não") quando um item de contrato é escolhido.
FLAGS_ZERADAS_COM_ITEM = ("IS_EXTRA_KIT", "IS_AVULSO")

def _flag_para_bool(valor):
    """Converte o valor da célula (checkbox/Sim/Não/vazio) em True/False/None."""
    if valor is None:
        return None
    if isinstance(valor, (bool, np.bool_)):
        return bool(valor)
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(valor, (int, float)):
        return bool(valor) if int(valor) in (0, 1) else None
    texto = str(valor).strip().upper()
    if texto in {"SIM", "S", "TRUE", "1", "YES"}:
        return True
    if texto in {"NAO", "NÃO", "N", "FALSE", "0", "NO"}:
        return False
    return None

def _serie_flag(serie):
    return serie.map(_flag_para_bool) if serie is not None else None

def _serie_preenchida(serie):
    if serie is None:
        return None
    return serie.notna() & (serie.astype(str).str.strip() != "")

def aplicar_regras_flags(df_novo, df_anterior=None):
    """Regras de IS_EXTRA_KIT / IS_AVULSO.

    1. Ao escolher um item de contrato, ``IS_EXTRA_KIT`` e ``IS_AVULSO``
       passam para "Não" (False).
    2. Se depois o usuário mudar ``IS_EXTRA_KIT`` ou ``IS_AVULSO`` para "Não"
       (vindo de "Sim"/vazio), o item de contrato é apagado:
       ``ITEM_DO_CONTRATO`` e ``CONTRACT_ITEM_ID`` recebem ``None``.

    ``df_anterior`` é o estado da tabela antes da edição; sem ele (carga
    inicial/batch) só a regra 1 é aplicada a linhas ainda sem valor.
    """
    if df_novo is None or df_novo.empty:
        return df_novo

    df_novo = df_novo.copy()
    for col in COLUNAS_FLAGS:
        if col not in df_novo.columns:
            df_novo[col] = None

    anterior = None
    if df_anterior is not None and not df_anterior.empty:
        anterior = df_anterior.reindex(df_novo.index)

    # Regra 2: usuário mudou uma flag para "Não" -> apaga item e ID oficial.
    if anterior is not None:
        for col in FLAGS_ZERADAS_COM_ITEM:
            if col not in anterior.columns:
                continue
            antes = _serie_flag(anterior[col])
            agora = _serie_flag(df_novo[col])
            virou_nao = (agora == False) & (antes != False)
            if virou_nao.any():
                df_novo.loc[virou_nao, "ITEM_DO_CONTRATO"] = None
                df_novo.loc[virou_nao, "CONTRACT_ITEM_ID"] = None

    # Regra 1 (evento): item passou de vazio para preenchido.
    item_agora = _serie_preenchida(df_novo["ITEM_DO_CONTRATO"])
    item_antes = _serie_preenchida(anterior.get("ITEM_DO_CONTRATO")) if anterior is not None else None
    if item_antes is not None:
        setou_item = item_agora & ~item_antes
    else:
        # Sem estado anterior, só define o "Não" onde a flag ainda não existe.
        setou_item = item_agora
        for col in FLAGS_ZERADAS_COM_ITEM:
            setou_item = setou_item & df_novo[col].isna()

    if setou_item.any():
        for col in FLAGS_ZERADAS_COM_ITEM:
            df_novo.loc[setou_item, col] = False

    return df_novo

def aplicar_automacao_no_dataframe(df_aba, aba, dict_mestre=None, df_anterior=None):
    """
    Valida as escolhas do usuário/IA e preenche as colunas oficiais de ID do banco de dados 
    (CONTRACT_ID e CONTRACT_ITEM_ID) em tempo real, usando apenas os contratos
    da aba informada.
    """
    if dict_mestre is None:
        dict_mestre = st.session_state.get("dict_mestre", {}).get(aba, {})
    if df_aba is None or df_aba.empty:
        return df_aba
    if not dict_mestre:
        return aplicar_regras_flags(df_aba, df_anterior)

    # Regras de IS_EXTRA_KIT/IS_AVULSO antes da validação: podem
    # limpar ITEM_DO_CONTRATO (e o CONTRACT_ITEM_ID é recalculado abaixo).
    df_aba = aplicar_regras_flags(df_aba, df_anterior)

    def validar_e_preencher(row):
        contrato_atual = row.get("CONTRATO")
        item_atual = row.get("ITEM_DO_CONTRATO")

        if pd.isna(contrato_atual) or str(contrato_atual).strip() == "":
            return pd.Series([None, None, True])

        c_norm = normalizar(contrato_atual)
        
        chave_contrato = None
        if c_norm in dict_mestre:
            chave_contrato = c_norm
        else:
            chave_contrato = next((key for key in dict_mestre.keys() if key.startswith(c_norm + " ") or c_norm.startswith(key + " ")), None)
        
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

    erros_mask = resultados[2] == True
    if erros_mask.sum() > 0:
        df_aba.loc[erros_mask, "ITEM_DO_CONTRATO"] = None
        df_aba.loc[erros_mask, "CONTRACT_ITEM_ID"] = None

    return df_aba

def montar_colunas_base(df_bruto, aba, existente=None):
    df_montado = pd.DataFrame()
    df_montado['CLIENTE_ID'] = df_bruto['id_cliente'].apply(valor_seguro_para_texto)
    df_montado['CLIENTE_NOME'] = df_bruto['nome_cliente'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_ID'] = df_bruto['id_equipamento'].apply(valor_seguro_para_texto)
    df_montado['TOMBO'] = df_bruto['tombo'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_NOME'] = df_bruto['nome_equipamentos'].apply(valor_seguro_para_texto)
    df_montado['ORGAO_ID'] = df_bruto['orgao_id'].apply(valor_seguro_para_texto)

    # Substituímos as colunas legadas pelo CONTRACT_ITEM_ID
    colunas_restantes = ["CONTRACT_ID", "CONTRATO", "CONTRACT_ITEM_ID", "ITEM_DO_CONTRATO", *COLUNAS_FLAGS]
    for col in colunas_restantes:
        df_montado[col] = None

    if existente is None:
        existente = st.session_state.get(aba)
    if existente is not None and not existente.empty:
        df_existente = existente
        if 'EQUIPAMENTO_ID' in df_existente.columns:
            map_contrato = df_existente.dropna(subset=['CONTRATO']).set_index('EQUIPAMENTO_ID')['CONTRATO'].to_dict()
            map_item = df_existente.dropna(subset=['ITEM_DO_CONTRATO']).set_index('EQUIPAMENTO_ID')['ITEM_DO_CONTRATO'].to_dict()
            df_montado['CONTRATO'] = df_montado['EQUIPAMENTO_ID'].map(map_contrato).replace({np.nan: None})
            df_montado['ITEM_DO_CONTRATO'] = df_montado['EQUIPAMENTO_ID'].map(map_item).replace({np.nan: None})
            for col in COLUNAS_FLAGS:
                if col not in df_existente.columns:
                    continue
                mapa_flag = (
                    df_existente.dropna(subset=[col])
                    .set_index('EQUIPAMENTO_ID')[col]
                    .to_dict()
                )
                if mapa_flag:
                    df_montado[col] = df_montado['EQUIPAMENTO_ID'].map(mapa_flag).replace({np.nan: None})

    return df_montado

def construir_tabela_organizacao(df_bruto, aba, dict_mestre=None, existente=None,
                                 ids_travados=None):
    df_montado = montar_colunas_base(df_bruto, aba, existente=existente)
    df_montado = aplicar_automacao_no_dataframe(df_montado, aba, dict_mestre=dict_mestre)
    df_montado = remover_itens_travados(df_montado, aba, ids_travados=ids_travados)
    return df_montado

def sincronizar_todas_as_abas(engine_relatorio, dicts_por_aba=None):
    """
    Busca os dados de equipamentos na fonte do Relatório Base e monta as abas.
    """
    if dicts_por_aba is None:
        dicts_por_aba = st.session_state.get("dict_mestre") or {}
    lista_dfs_brutos = []
    for aba, lista_ids in MAPPINGS.items():
        df_bruto = buscar_dados_por_orgao(engine_relatorio, lista_ids)
        df_bruto['aba_origem'] = aba
        lista_dfs_brutos.append(df_bruto)
        st.session_state[aba] = construir_tabela_organizacao(
            df_bruto, aba, dict_mestre=dicts_por_aba.get(aba)
        )

    if lista_dfs_brutos:
        df_relatorio = pd.concat(lista_dfs_brutos, ignore_index=True)
        st.session_state["df_relatorio"] = df_relatorio
        RELATORIO_BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
        df_relatorio.to_csv(RELATORIO_BANCO_PATH, index=False)