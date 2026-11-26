import streamlit as st
import pandas as pd
from core.database import (
    configuracao_relatorio,
    obter_conexao_novo,
    obter_conexao_relatorio,
    carregar_contratos_do_banco,
    obter_caminho_relatorio_banco,
    testar_conexao_relatorio,
)
from utils.text_processing import MAPPINGS, nomes_abas_memoria
from services.dictionary_service import construir_dicionarios_por_aba
from components.organization_tab import renderizar_aba_organizacao
from components.parquet_tab import renderizar_arquivos_parquet

st.set_page_config(page_title="Painel de Equipamentos Alugados", layout="wide")

# =======================================================================
# 🔌 INICIALIZAÇÃO DE CONEXÕES COM O BANCO
# =======================================================================
engine_novo = obter_conexao_novo()

# =======================================================================
# 🧠 CONSTRUÇÃO DO ESTADO DA SESSÃO E CÉREBRO
# =======================================================================
if "df_contratos_banco" not in st.session_state:
    # Executa a query no banco novo e salva em memória
    try:
        st.session_state["df_contratos_banco"] = carregar_contratos_do_banco(engine_novo)
    except Exception as e:
        st.session_state["df_contratos_banco"] = pd.DataFrame()
        st.error(
            "Não foi possível conectar ao Banco Novo. "
            "Verifique se o MySQL está no ar e se as variáveis DB_NOVO_* apontam "
            f"para o host/porta corretos.\n\nDetalhe: {e}"
        )

def _dict_mestre_por_aba_atual(dict_atual):
    """True quando o dicionário já está no formato {aba: {contrato: dados}}."""
    if not isinstance(dict_atual, dict) or not dict_atual:
        return True
    if set(dict_atual.keys()) != set(MAPPINGS.keys()):
        return False
    return not any("nome_original" in valor for valor in dict_atual.values())


# Bump ao mudar a lógica de casamento de contratos: força a reconstrução do
# dicionário e das abas em sessões que ficaram abertas durante a atualização.
REVISAO_CASAMENTO_CONTRATOS = 2

if (
    "dict_mestre" not in st.session_state
    or not _dict_mestre_por_aba_atual(st.session_state.get("dict_mestre"))
    or st.session_state.get("_revisao_casamento_contratos")
    != REVISAO_CASAMENTO_CONTRATOS
):
    # Um dicionário de contratos por aba: cada empresa só usa os próprios
    # contratos (ver utils.text_processing.ABA_POR_ORGAO).
    st.session_state["dict_mestre"] = construir_dicionarios_por_aba(
        st.session_state["df_contratos_banco"]
    )
    st.session_state["_revisao_casamento_contratos"] = REVISAO_CASAMENTO_CONTRATOS
    # Remonta as abas com o novo dicionário (contratos de outra aba caem).
    st.session_state.pop("df_relatorio", None)
    for _aba in nomes_abas_memoria:
        st.session_state.pop(_aba, None)

# Orquestração do Relatório Base local (Equipamentos do Legado)
if "df_relatorio" not in st.session_state:
    caminho_relatorio = obter_caminho_relatorio_banco()
    if caminho_relatorio.exists():
        st.session_state["df_relatorio"] = pd.read_csv(caminho_relatorio)
        from services.dictionary_service import construir_tabela_organizacao
        # Puxa o motor auxiliar de inicialização de tabelas estruturadas
        for aba, lista_ids in MAPPINGS.items():
            df_f = st.session_state["df_relatorio"][st.session_state["df_relatorio"]['orgao_id'].isin(lista_ids)].copy()
            st.session_state[aba] = construir_tabela_organizacao(df_f, aba)
    else:
        st.session_state["df_relatorio"] = pd.DataFrame()
        for aba in nomes_abas_memoria:
            st.session_state[aba] = pd.DataFrame()

# Sessões abertas durante a atualização já têm as abas montadas sem as colunas
# de classificação. Adiciona as colunas vazias sem descartar o trabalho da tela.
for _aba in nomes_abas_memoria:
    _df_aba = st.session_state.get(_aba)
    if isinstance(_df_aba, pd.DataFrame) and not _df_aba.empty:
        for _col in ("IS_KIT", "IS_AVULSO"):
            if _col not in _df_aba.columns:
                st.session_state[_aba][_col] = None

# =======================================================================
# 🔄 MENU LATERAL (SIDEBAR)
# =======================================================================
st.sidebar.header("🔄 Sincronizar Banco")
cfg_relatorio = configuracao_relatorio()
st.sidebar.caption(
    "Base do relatório: "
    f"`{cfg_relatorio['host']}:{cfg_relatorio['port']}/{cfg_relatorio['database']}`  \n"
    f"Origem: {cfg_relatorio['origem']}"
)

if st.sidebar.button("⚙️ Atualizar Relatório Base", type="secondary"):
    with st.sidebar.status("Consultando equipamentos na base do relatório...", expanded=True) as status:
        try:
            from services.dictionary_service import sincronizar_todas_as_abas
            # Valida a conexão antes para devolver um erro legível (host/porta).
            testar_conexao_relatorio()
            sincronizar_todas_as_abas(obter_conexao_relatorio())
            status.update(label="Sincronização concluída!", state="complete", expanded=False)
            st.rerun()
        except Exception as e:
            status.update(label="Falha na sincronização", state="error", expanded=True)
            st.sidebar.error(
                "Erro ao ler a base do relatório em "
                f"{cfg_relatorio['host']}:{cfg_relatorio['port']}: {e}"
            )

if st.sidebar.button("🔌 Testar conexão da base"):
    try:
        testar_conexao_relatorio()
        st.sidebar.success(
            f"Conexão OK com {cfg_relatorio['host']}:{cfg_relatorio['port']}"
        )
    except Exception as e:
        st.sidebar.error(
            "Falha ao conectar em "
            f"{cfg_relatorio['host']}:{cfg_relatorio['port']}: {e}"
        )

# =======================================================================
# ⚙️ CONFIGURAÇÃO DE UI E COLUNAS DA TABELA
# =======================================================================
# Cada aba só oferece os contratos da própria empresa; sem isso, um cliente
# com nome homônimo em outra aba herdava o contrato errado.
def _opcoes_contratos_da_aba(aba):
    dict_aba = st.session_state.get("dict_mestre", {}).get(aba) or {}
    return sorted({dados["nome_original"] for dados in dict_aba.values()})


# Atualizado com as colunas reais e oficiais para o Script de Migração
def _configuracao_colunas(aba):
    configuracao = {
        "CONTRATO": st.column_config.SelectboxColumn(
            "CONTRATO", options=_opcoes_contratos_da_aba(aba)
        ),
        "CLIENTE_ID": st.column_config.TextColumn("CLIENTE_ID", disabled=True),
        "CLIENTE_NOME": st.column_config.TextColumn("CLIENTE_NOME", disabled=True),
        "EQUIPAMENTO_ID": st.column_config.TextColumn("EQUIPAMENTO_ID", disabled=True),
        "TOMBO": st.column_config.TextColumn("TOMBO", disabled=True),
        "EQUIPAMENTO_NOME": st.column_config.TextColumn("EQUIPAMENTO_NOME", disabled=True),
        "CONTRACT_ID": st.column_config.TextColumn("CONTRACT_ID", disabled=True),
        "CONTRACT_ITEM_ID": st.column_config.TextColumn("CONTRACT_ITEM_ID", disabled=True),
        "IS_EXTRA_KIT": st.column_config.CheckboxColumn(
            "IS_EXTRA_KIT",
            help="Item extra/kit fora do escopo do contrato.",
        ),
        "IS_KIT": st.column_config.CheckboxColumn(
            "IS_KIT",
            help="Marca o equipamento como kit.",
        ),
        "IS_AVULSO": st.column_config.CheckboxColumn(
            "IS_AVULSO",
            help="Marca o equipamento como avulso.",
        ),
    }
    return configuracao

# =======================================================================
# 🖥️ RENDERIZAÇÃO DA PÁGINA (TABS)
# =======================================================================
st.title("🖥️ Painel de Automação de Equipamentos")

# Interfaces enxugadas: a aba de "Itens" e "Contratos" virou uma só de "Contratos e Itens" (View Banco Novo)
abas_ui = st.tabs([
    '🏗️ ALUCOM', '🌐 IP SERVIÇOS', '🦈 MOREIA', '🏢 AS SISTEMAS', 
    '📄 Contratos e Itens (Banco Novo)', '🖥️ View Equipamentos (Banco Legado)', '🔐 Itens Travados'
])

# Renderização das Abas de Organização (0 a 3)
for idx_ui, nome_memoria in enumerate(nomes_abas_memoria):
    with abas_ui[idx_ui]:
        renderizar_aba_organizacao(
            nome_memoria,
            _configuracao_colunas(nome_memoria),
            _opcoes_contratos_da_aba(nome_memoria),
        )

# Tab 4: Tabela com o resultado da Query do banco novo
with abas_ui[4]:
    st.info("💡 Dados carregados dinamicamente via JOIN do Banco Novo.")
    st.dataframe(st.session_state["df_contratos_banco"], width="stretch", height=700)

# Tab 5: Base de Equipamentos e Órgãos (Banco Legado)
with abas_ui[5]:
    st.info("💡 Snapshot local (CSV) de equipamentos puxado do Banco Legado.")
    st.dataframe(st.session_state["df_relatorio"], width="stretch", height=700)

# Tab 6: Gestor de Arquivos Parquet Travados
with abas_ui[6]:
    renderizar_arquivos_parquet()