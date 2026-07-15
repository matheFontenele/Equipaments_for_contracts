import streamlit as st
import pandas as pd
from core.database import obter_conexao_legado, obter_conexao_novo, carregar_contratos_do_banco, obter_caminho_relatorio_banco
from utils.text_processing import MAPPINGS, nomes_abas_memoria
from services.dictionary_service import construir_dicionario_mestre
from components.organization_tab import renderizar_aba_organizacao
from components.parquet_tab import renderizar_arquivos_parquet

st.set_page_config(page_title="Painel de Equipamentos Alugados", layout="wide")

# =======================================================================
# 🔌 INICIALIZAÇÃO DE CONEXÕES COM O BANCO
# =======================================================================
engine_legado = obter_conexao_legado()
engine_novo = obter_conexao_novo()

# =======================================================================
# 🧠 CONSTRUÇÃO DO ESTADO DA SESSÃO E CÉREBRO
# =======================================================================
if "df_contratos_banco" not in st.session_state:
    # Executa a query no banco novo e salva em memória
    st.session_state["df_contratos_banco"] = carregar_contratos_do_banco(engine_novo)

if "dict_mestre" not in st.session_state:
    # Cria a árvore de relacionamentos de altíssima performance
    st.session_state["dict_mestre"] = construir_dicionario_mestre(st.session_state["df_contratos_banco"])

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

# =======================================================================
# 🔄 MENU LATERAL (SIDEBAR)
# =======================================================================
st.sidebar.header("🔄 Sincronizar Banco")
if st.sidebar.button("⚙️ Atualizar Relatório Base", type="secondary"):
    with st.sidebar.status("Executando consultas de equipamentos no Legado...", expanded=True) as status:
        try:
            from services.dictionary_service import sincronizar_todas_as_abas
            # Passamos o motor legado para varrer a base de máquinas!
            sincronizar_todas_as_abas(engine_legado)
            status.update(label="Sincronização concluída!", state="complete", expanded=False)
            st.rerun()
        except Exception as e:
            status.update(label="Falha na sincronização", state="error", expanded=True)
            st.sidebar.error(f"Erro: {e}")

# =======================================================================
# ⚙️ CONFIGURAÇÃO DE UI E COLUNAS DA TABELA
# =======================================================================
opcoes_contratos = []
if "dict_mestre" in st.session_state and st.session_state["dict_mestre"]:
    # Busca dinamicamente todos os nomes reais de contrato disponíveis no dicionário
    opcoes_contratos = sorted([dados["nome_original"] for dados in st.session_state["dict_mestre"].values()])

# Atualizado com as colunas reais e oficiais para o Script de Migração
configuracao_colunas_base = {
    "CONTRATO": st.column_config.SelectboxColumn("CONTRATO", options=opcoes_contratos),
    "CLIENTE_ID": st.column_config.TextColumn("CLIENTE_ID", disabled=True),
    "CLIENTE_NOME": st.column_config.TextColumn("CLIENTE_NOME", disabled=True),
    "EQUIPAMENTO_ID": st.column_config.TextColumn("EQUIPAMENTO_ID", disabled=True),
    "TOMBO": st.column_config.TextColumn("TOMBO", disabled=True),
    "EQUIPAMENTO_NOME": st.column_config.TextColumn("EQUIPAMENTO_NOME", disabled=True),
    "CONTRACT_ID": st.column_config.TextColumn("CONTRACT_ID", disabled=True),
    "CONTRACT_ITEM_ID": st.column_config.TextColumn("CONTRACT_ITEM_ID", disabled=True),
    "TIPO_EQUIPAMENTO": st.column_config.TextColumn("TIPO_EQUIPAMENTO", disabled=True)
}

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
        renderizar_aba_organizacao(nome_memoria, configuracao_colunas_base, opcoes_contratos)

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