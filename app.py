import streamlit as st
import pandas as pd
from core.database import obter_conexao_banco, carregar_planilha_local, obter_caminho_relatorio_banco
from utils.text_processing import MAPPINGS, nomes_abas_memoria
from services.dictionary_service import construir_dicionario_mestre
from services.locking_service import obter_ids_travados
from components.organization_tab import renderizar_aba_organizacao
from components.parquet_tab import renderizar_arquivos_parquet

st.set_page_config(page_title="Painel de Equipamentos Alugados", layout="wide")

# Inicialização segura do Estado da Sessão
if "df_contratos" not in st.session_state:
    st.session_state["df_contratos"] = carregar_planilha_local("Contratos")
if "itens_de_contratos" not in st.session_state:
    st.session_state["itens_de_contratos"] = carregar_planilha_local("itens_de_contratos")
if "dict_mestre" not in st.session_state:
    if not st.session_state["df_contratos"].empty and not st.session_state["itens_de_contratos"].empty:
        st.session_state["dict_mestre"] = construir_dicionario_mestre(st.session_state["df_contratos"], st.session_state["itens_de_contratos"])

# Orquestração do Relatório Base local
if "df_relatorio" not in st.session_state:
    caminho_relatorio = obter_caminho_relatorio_banco()
    if caminho_relatorio.exists():
        st.session_state["df_relatorio"] = pd.read_csv(caminho_relatorio)
        from services.dictionary_service import construir_tabela_organizacao
        from core.database import buscar_dados_por_orgao
        # Puxa o motor auxiliar de inicialização de tabelas estruturadas
        for aba, lista_ids in MAPPINGS.items():
            df_f = st.session_state["df_relatorio"][st.session_state["df_relatorio"]['orgao_id'].isin(lista_ids)].copy()
            st.session_state[aba] = construir_tabela_organizacao(df_f, aba)
    else:
        st.session_state["df_relatorio"] = pd.DataFrame()
        for aba in nomes_abas_memoria:
            st.session_state[aba] = pd.DataFrame()

# Barra Lateral Centralizada
st.sidebar.header("🔄 Sincronizar Banco")
if st.sidebar.button("⚙️ Atualizar Relatório Base", type="secondary"):
    with st.sidebar.status("Executando consultas por organização...", expanded=True) as status:
        try:
            from services.dictionary_service import sincronizar_todas_as_abas
            sincronizar_todas_as_abas(obter_conexao_banco())
            status.update(label="Sincronização concluída!", state="complete", expanded=False)
            st.rerun()
        except Exception as e:
            status.update(label="Falha na sincronização", state="error", expanded=True)
            st.sidebar.error(f"Erro: {e}")

# Opções de dropdown para os editores de células
opcoes_contratos = []
if not st.session_state["df_contratos"].empty:
    col_c = "CONTRATOS" if "CONTRATOS" in st.session_state["df_contratos"].columns else st.session_state["df_contratos"].columns[0]
    opcoes_contratos = st.session_state["df_contratos"][col_c].dropna().astype(str).unique().tolist()

configuracao_colunas_base = {
    "CONTRATO": st.column_config.SelectboxColumn("CONTRATO", options=opcoes_contratos),
    "CLIENTE_ID": st.column_config.TextColumn("CLIENTE_ID", disabled=True),
    "CLIENTE_NOME": st.column_config.TextColumn("CLIENTE_NOME", disabled=True),
    "EQUIPAMENTO_ID": st.column_config.TextColumn("EQUIPAMENTO_ID", disabled=True),
    "TOMBO": st.column_config.TextColumn("TOMBO", disabled=True),
    "EQUIPAMENTO_NOME": st.column_config.TextColumn("EQUIPAMENTO_NOME", disabled=True),
    "CONTRACT_ID": st.column_config.TextColumn("CONTRACT_ID", disabled=True),
    "DESCRICAO_ITEM": st.column_config.TextColumn("DESCRICAO_ITEM", disabled=True),
    "QUANTIDADE_ITEM_NO_CONTRATO": st.column_config.TextColumn("QUANTIDADE_ITEM_NO_CONTRATO", disabled=True),
    "ID_EVENTO": st.column_config.TextColumn("ID_EVENTO", disabled=True),
    "TIPO_EQUIPAMENTO": st.column_config.TextColumn("TIPO_EQUIPAMENTO", disabled=True)
}

# Interface Visual Unificada (Tabs)
st.title("🖥️ Painel de Automação de Equipamentos")
abas_ui = st.tabs([
    '🏗️ ALUCOM', '🌐 IP SERVIÇOS', '🦈 MOREIA', '🏢 AS SISTEMAS', 
    '📄 Contratos', '📦 Itens de Contrato', '🖥️ View Relatório Banco', '🔐 Itens Travados'
])

# Renderização das Abas de Organização
for idx_ui, nome_memoria in enumerate(nomes_abas_memoria):
    with abas_ui[idx_ui]:
        renderizar_aba_organizacao(nome_memoria, configuracao_colunas_base, opcoes_contratos)

# Renderização das Abas de Dados Brutos e Parquet
with abas_ui[4]:
    st.dataframe(st.session_state["df_contratos"], use_container_width=True, height=700)

with abas_ui[5]:
    st.dataframe(st.session_state["itens_de_contratos"], use_container_width=True, height=700)

with abas_ui[6]:
    st.dataframe(st.session_state["df_relatorio"], use_container_width=True, height=700)

with abas_ui[7]:
    renderizar_arquivos_parquet()
