import os
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path

_dir_core = os.path.dirname(os.path.abspath(__file__))
_caminho_env = os.path.abspath(os.path.join(_dir_core, '..', '.env'))
load_dotenv(_caminho_env, override=False)

BASE_DIR = Path(_dir_core).parent
DOCS_DIR = BASE_DIR / "docs"
RELATORIO_BANCO_PATH = DOCS_DIR / "relatorio_banco.csv"
LEGACY_RELATORIO_BANCO_PATH = BASE_DIR / "relatorio_banco.csv"

# =======================================================================
# 🗄️ CONEXÕES DE BANCO DE DADOS
# =======================================================================

@st.cache_resource
def obter_conexao_legado():
    """Conexão com o banco antigo (Origem dos Equipamentos)"""
    db_host = os.getenv("DB_LEGADO_HOST")
    db_port = os.getenv("DB_LEGADO_PORT")
    db_name = os.getenv("DB_LEGADO_DATABASE")
    db_user = os.getenv("DB_LEGADO_USERNAME")
    db_pass = os.getenv("DB_LEGADO_PASSWORD")

    URL_CONEXAO = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    return create_engine(URL_CONEXAO, pool_pre_ping=True)

@st.cache_resource
def obter_conexao_novo():
    """Conexão com o banco novo (Origem dos Contratos e Itens)"""
    db_host = os.environ["DB_NOVO_HOST"]
    db_port = os.environ["DB_NOVO_PORT"]
    db_name = os.environ["DB_NOVO_DATABASE"]
    db_user = os.environ["DB_NOVO_USERNAME"]
    db_pass = os.environ["DB_NOVO_PASSWORD"]

    URL_CONEXAO = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    return create_engine(URL_CONEXAO, pool_pre_ping=True)


def configuracao_relatorio():
    """Descreve de onde o botão "Atualizar Relatório Base" lê os equipamentos.

    Se ``DB_RELATORIO_HOST`` estiver definido, a leitura usa essa conexão
    (ex.: banco legado da máquina de desenvolvimento exposto na rede local).
    Caso contrário, mantém o comportamento original: ``DB_LEGADO_*``.
    """
    prefixo = "DB_RELATORIO" if os.getenv("DB_RELATORIO_HOST") else "DB_LEGADO"
    origem = (
        "base externa configurada em DB_RELATORIO_*"
        if prefixo == "DB_RELATORIO"
        else "banco legado do próprio servidor (DB_LEGADO_*)"
    )
    return {
        "prefixo": prefixo,
        "origem": origem,
        "host": os.getenv(f"{prefixo}_HOST"),
        "port": os.getenv(f"{prefixo}_PORT"),
        "database": os.getenv(f"{prefixo}_DATABASE"),
        "username": os.getenv(f"{prefixo}_USERNAME"),
        "password": os.getenv(f"{prefixo}_PASSWORD"),
    }


@st.cache_resource
def obter_conexao_relatorio():
    """Conexão usada para montar o Relatório Base (equipamentos alugados)."""
    cfg = configuracao_relatorio()
    faltando = [campo for campo in ("host", "port", "database", "username") if not cfg[campo]]
    if faltando:
        raise RuntimeError(
            f"Configuração incompleta do Relatório Base ({cfg['prefixo']}_*): "
            f"faltam {', '.join(faltando)}"
        )

    url = (
        f"mysql+pymysql://{quote_plus(str(cfg['username']))}:"
        f"{quote_plus(str(cfg['password'] or ''))}@"
        f"{cfg['host']}:{cfg['port']}/{cfg['database']}"
    )
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 8})


def testar_conexao_relatorio():
    """Abre a conexão do Relatório Base e executa ``SELECT 1``."""
    engine = obter_conexao_relatorio()
    with engine.connect() as conexao:
        conexao.execute(text("SELECT 1"))
    return configuracao_relatorio()


# =======================================================================
# 📂 FUNÇÕES DE CARREGAMENTO (ARQUIVOS)
# =======================================================================
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

# =======================================================================
# 🔍 FUNÇÕES DE CONSULTA (QUERIES)
# =======================================================================

def buscar_dados_por_orgao(engine_legado, lista_ids):
    """Busca a base de equipamentos ativos no banco LEGADO usando CTE para maior performance"""
    lista_ids_str = ", ".join(str(i) for i in lista_ids)
    
    query = f"""
        SELECT 
            cli.id AS id_cliente, 
            cli.nome_razao_social AS nome_cliente, 
            alq.id AS id_equipamento, 
            alq.numero AS tombo, 
            alq.nome AS nome_equipamentos, 
            mov.orgao_id AS orgao_id,
            mov.data AS data 
        FROM aluguel_equipamentos alq
        INNER JOIN aluguel_movimento_itens movi ON movi.equipamento_id = alq.id
        INNER JOIN aluguel_movimento mov       ON movi.movimento_id = mov.id
        INNER JOIN aluguel_clientes cli        ON mov.cliente_id = cli.id
        WHERE alq.deleted_at IS NULL 
        AND mov.deleted_at IS NULL
        AND movi.deleted_at IS NULL
        AND alq.situacao_id = 1 
        AND mov.orgao_id IN ({lista_ids_str})
        AND mov.id = (
            SELECT mov2.id
            FROM aluguel_movimento_itens movi2
            INNER JOIN aluguel_movimento mov2 ON movi2.movimento_id = mov2.id
            WHERE movi2.equipamento_id = alq.id
                AND mov2.deleted_at IS NULL
                AND movi2.deleted_at IS NULL
            ORDER BY mov2.data DESC, mov2.id DESC
            LIMIT 1
        )
    """
    return pd.read_sql(query, con=engine_legado)

def carregar_contratos_do_banco(engine_novo):
    """Busca os contratos e itens diretamente do banco NOVO"""
    query = """
        SELECT
            cus.id AS customer_id,
            cus.alias AS cutomer_name,
            con.id AS contract_id,
            con.name AS contract_name,
            con.organization_id AS contract_organization_id,
            coi.id AS contract_item_id,
            coi.alias AS contract_item_alias,
            coi.quantity,
            coi.available_quantity
        FROM contract_items coi
        INNER JOIN event_additives ev ON coi.event_additive_id = ev.id
        INNER JOIN contract_events cov ON ev.event_id = cov.id
        INNER JOIN contracts con ON cov.contract_id = con.id
        INNER JOIN customers cus ON con.customer_id = cus.id
    """
    return pd.read_sql(query, con=engine_novo)
