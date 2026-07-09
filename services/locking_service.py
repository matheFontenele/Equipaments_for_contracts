import os
import glob
import pandas as pd
import streamlit as st
from datetime import datetime
from utils.text_processing import slugify_arquivo, valor_seguro_para_texto

PASTA_LOCKS = "locks_parquet"

def montar_nome_parquet(aba, contrato_texto, contract_id, cliente_nome, cliente_id):
    slug_org = slugify_arquivo(aba, 20)
    slug_contrato = slugify_arquivo(contrato_texto, 40)
    slug_cliente = slugify_arquivo(cliente_nome, 30)
    return os.path.join(PASTA_LOCKS, f"{slug_org}__C{contract_id}-{slug_contrato}__CLI{cliente_id}-{slug_cliente}.parquet")

def invalidar_cache_travados(aba):
    chave = f"_ids_travados_{aba}"
    if chave in st.session_state:
        del st.session_state[chave]

def listar_arquivos_travados(aba=None):
    arquivos = sorted(glob.glob(os.path.join(PASTA_LOCKS, "*.parquet")))
    if aba:
        prefixo = slugify_arquivo(aba, 20) + "__"
        arquivos = [a for a in arquivos if os.path.basename(a).startswith(prefixo)]
    return arquivos

def obter_ids_travados(aba):
    chave = f"_ids_travados_{aba}"
    if chave not in st.session_state:
        ids = set()
        for caminho in listar_arquivos_travados(aba):
            try:
                df_tmp = pd.read_parquet(caminho, columns=["EQUIPAMENTO_ID"])
                ids.update(df_tmp["EQUIPAMENTO_ID"].astype(str).tolist())
            except Exception:
                continue
        st.session_state[chave] = ids
    return st.session_state[chave]

def remover_itens_travados(df, aba):
    if df is None or df.empty:
        return df
    ids_travados = obter_ids_travados(aba)
    if not ids_travados:
        return df
    return df[~df["EQUIPAMENTO_ID"].astype(str).isin(ids_travados)].reset_index(drop=True)

def travar_grupo(aba, contrato_texto, df_grupo_atual):
    if df_grupo_atual.empty:
        return 0

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_travado = 0

    for cliente_id, df_cliente in df_grupo_atual.groupby("CLIENTE_ID"):
        if df_cliente.empty:
            continue
        cliente_nome = df_cliente["CLIENTE_NOME"].iloc[0]
        contract_id = valor_seguro_para_texto(df_cliente["CONTRACT_ID"].iloc[0]) or "SEMID"

        df_para_salvar = df_cliente.copy()
        df_para_salvar["ORGAO"] = aba
        df_para_salvar["TRAVADO_EM"] = agora

        caminho = montar_nome_parquet(aba, contrato_texto, contract_id, cliente_nome, cliente_id)
        df_para_salvar.to_parquet(caminho, index=False)
        total_travado += len(df_cliente)

    ids_travados = set(df_grupo_atual["EQUIPAMENTO_ID"].astype(str))
    st.session_state[aba] = st.session_state[aba][~st.session_state[aba]["EQUIPAMENTO_ID"].astype(str).isin(ids_travados)].reset_index(drop=True)

    invalidar_cache_travados(aba)
    return total_travado

def destravar_arquivo(caminho, aba):
    try:
        df_travado = pd.read_parquet(caminho)
    except Exception as e:
        st.error(f"Erro ao ler arquivo travado: {e}")
        return

    df_travado = df_travado.drop(columns=[c for c in ["ORGAO", "TRAVADO_EM"] if c in df_travado.columns])
    st.session_state[aba] = pd.concat([st.session_state[aba], df_travado], ignore_index=True)
    os.remove(caminho)
    invalidar_cache_travados(aba)