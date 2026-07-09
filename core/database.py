import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from dotenv import load_dotenv
from pathlib import Path

_dir_core = os.path.dirname(os.path.abspath(__file__))
_caminho_env = os.path.abspath(os.path.join(_dir_core, '..', '.env'))
load_dotenv(_caminho_env, override=True)

BASE_DIR = Path(_dir_core).parent
DOCS_DIR = BASE_DIR / "docs"
RELATORIO_BANCO_PATH = DOCS_DIR / "relatorio_banco.csv"
LEGACY_RELATORIO_BANCO_PATH = BASE_DIR / "relatorio_banco.csv"

@st.cache_resource
def obter_conexao_banco():
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "3307")
    db_name = os.getenv("DB_DATABASE", "aluguel_legado")
    db_user = os.getenv("DB_USERNAME", "root")
    db_pass = os.getenv("DB_PASSWORD", "root")

    URL_CONEXAO = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    return create_engine(URL_CONEXAO, pool_pre_ping=True)

def carregar_planilha_local(nome_base):
    caminhos = [
        DOCS_DIR / f"{nome_base}.xlsx",
        DOCS_DIR / f"{nome_base}.csv",
        BASE_DIR / f"{nome_base}.xlsx",
        BASE_DIR / f"{nome_base}.csv",
    ]

    for caminho in caminhos:
        if not caminho.exists():
            continue
        if caminho.suffix.lower() == ".xlsx":
            return pd.read_excel(caminho)
        if caminho.suffix.lower() == ".csv":
            return pd.read_csv(caminho)

    return pd.DataFrame()

def obter_caminho_relatorio_banco():
    if RELATORIO_BANCO_PATH.exists():
        return RELATORIO_BANCO_PATH
    return LEGACY_RELATORIO_BANCO_PATH

def buscar_dados_por_orgao(engine, lista_ids):
    lista_ids_str = ", ".join(str(i) for i in lista_ids)
    query = f"""
        SELECT
        alc.id AS id_cliente,
        alc.nome_razao_social AS nome_cliente,
        alq.id AS id_equipamento,
        alq.numero AS tombo,
        alq.nome AS nome_equipamentos,
        am.orgao_id,
        alq.deleted_at
    FROM aluguel_equipamentos alq
    INNER JOIN (
        SELECT
            ami.equipamento_id,
            MAX(am.id) AS ultimo_movimento
        FROM aluguel_movimento_itens ami
        INNER JOIN aluguel_movimento am
            ON am.id = ami.movimento_id
        WHERE am.deleted_at IS NULL
        AND ami.deleted_at IS NULL
        GROUP BY ami.equipamento_id
    ) ult
        ON ult.equipamento_id = alq.id
    INNER JOIN aluguel_movimento am
        ON am.id = ult.ultimo_movimento
    INNER JOIN aluguel_movimento_itens ami
        ON ami.movimento_id = am.id
    AND ami.equipamento_id = alq.id
    INNER JOIN aluguel_clientes alc
        ON alc.id = am.cliente_id
    WHERE alq.situacao_id = 1
    AND am.orgao_id IN ({lista_ids_str})
    AND am.deleted_at IS NULL
    AND ami.deleted_at IS NULL
    AND alc.deleted_at IS NULL;
    """
    return pd.read_sql(query, con=engine)
