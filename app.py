import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import os
import re
import glob
import unicodedata
import numpy as np
import hashlib
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÕES INICIAIS
# ==============================================================================
st.set_page_config(page_title="Painel de Equipamentos Alugados", layout="wide")

ARQUIVO_CSV_RELATORIO = "relatorio_banco.csv"
PASTA_LOCKS = "locks_parquet"
os.makedirs(PASTA_LOCKS, exist_ok=True)

@st.cache_resource
def obter_conexao_banco():
    HOST_NOVO = os.getenv("DB_HOST_NEW", "localhost")
    config_legado = {
        "host": HOST_NOVO, "port": "3307", "db": "aluguel_legado",
        "user": "root", "pass": "root"
    }
    URL_CONEXAO = f"mysql+pymysql://{config_legado['user']}:{config_legado['pass']}@{config_legado['host']}:{config_legado['port']}/{config_legado['db']}"
    return create_engine(URL_CONEXAO, pool_pre_ping=True)

def carregar_planilha_local(nome_base):
    if os.path.exists(f"{nome_base}.xlsx"):
        return pd.read_excel(f"{nome_base}.xlsx")
    elif os.path.exists(f"{nome_base}.csv"):
        return pd.read_csv(f"{nome_base}.csv")
    else:
        return pd.DataFrame()

# ==============================================================================
# MAPEAMENTO DE ÓRGÃOS
# ==============================================================================
MAPPING_ALUCOM = {1115, 1327, 1329, 1363, 1365, 1366, 1367, 1370, 1353, 1373, 1377}
MAPPING_IP = {1311, 1346, 1349, 1350, 1364, 1368, 1371}
MAPPING_MOREIA = {1122, 1326, 1328, 1358, 1369}
MAPPING_AS = {1378}

MAPPINGS = {
    'ALUCOM': MAPPING_ALUCOM,
    'IP SERVIÇOS': MAPPING_IP,
    'MOREIA': MAPPING_MOREIA,
    'AS SISTEMAS': MAPPING_AS
}
nomes_abas_memoria = list(MAPPINGS.keys())

# ==============================================================================
# NORMALIZAÇÃO DE TEXTO E CHAVES
# ==============================================================================
def normalizar(texto):
    if pd.isna(texto) or str(texto).strip() == "":
        return ""
    texto_norm = unicodedata.normalize("NFD", str(texto))
    texto_norm = "".join([c for c in texto_norm if unicodedata.category(c) != "Mn"])
    return " ".join(texto_norm.split()).upper()

def valor_seguro_para_texto(valor):
    if pd.isna(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)

def slugify_key(texto):
    """Gera uma chave curta e segura para usar como key de widgets do Streamlit."""
    return hashlib.md5(str(texto).encode('utf-8')).hexdigest()[:12]

def slugify_arquivo(texto, max_len=40):
    """Gera um trecho seguro de nome de arquivo (sem acentos/espaços/caracteres especiais)."""
    texto_norm = normalizar(texto)
    texto_norm = texto_norm.replace(" ", "-")
    texto_norm = re.sub(r'[^A-Z0-9\-]', '', texto_norm)
    return texto_norm[:max_len].strip('-') or "SEMNOME"

# ==============================================================================
# 🧠 ARQUITETURA SUPER DICIONÁRIO: CONTRATOS -> ITENS
# ==============================================================================
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
            
        c_norm = normalizar(c_bruto)
        c_id = valor_seguro_para_texto(row.get(col_c_id))
        dict_map[c_norm] = {"id": c_id, "itens": {}}

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
        
        chave_contrato = None
        for key in dict_map.keys():
            if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key):
                chave_contrato = key
                break
                
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
    """Retorna a lista de APELIDOS (texto original) que pertencem só ao contrato informado."""
    dict_mestre = st.session_state.get("dict_mestre", {})
    if not dict_mestre or pd.isna(contrato_bruto) or str(contrato_bruto).strip() == "":
        return []

    c_norm = normalizar(contrato_bruto)
    chave_contrato = None
    for key in dict_mestre.keys():
        if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key):
            chave_contrato = key
            break

    if not chave_contrato:
        return []

    apelidos = sorted({
        item_info["apelido_original"]
        for item_info in dict_mestre[chave_contrato]["itens"].values()
    })
    return apelidos

# ==============================================================================
# 🔒 CAMADA DE TRAVAMENTO (PARQUET) — usada pelo script de migração depois
# ==============================================================================
def montar_nome_parquet(aba, contrato_texto, contract_id, cliente_nome, cliente_id):
    """
    Nome do arquivo identifica: organização (aba), contrato e cliente.
    Ex: ALUCOM__C197-GOVERNO-MUNICIPAL-DE-URUOCA__CLI868-PMURUOCASECEDU.parquet
    """
    slug_org = slugify_arquivo(aba, 20)
    slug_contrato = slugify_arquivo(contrato_texto, 40)
    slug_cliente = slugify_arquivo(cliente_nome, 30)
    nome = f"{slug_org}__C{contract_id}-{slug_contrato}__CLI{cliente_id}-{slug_cliente}.parquet"
    return os.path.join(PASTA_LOCKS, nome)

def invalidar_cache_travados(aba):
    chave = f"_ids_travados_{aba}"
    if chave in st.session_state:
        del st.session_state[chave]

def listar_arquivos_travados(aba=None):
    """Lista os parquets travados, opcionalmente filtrando por organização."""
    arquivos = sorted(glob.glob(os.path.join(PASTA_LOCKS, "*.parquet")))
    if aba:
        prefixo = slugify_arquivo(aba, 20) + "__"
        arquivos = [a for a in arquivos if os.path.basename(a).startswith(prefixo)]
    return arquivos

def obter_ids_travados(aba):
    """Set de EQUIPAMENTO_ID já travados para uma organização (com cache em sessão)."""
    chave = f"_ids_travados_{aba}"
    if chave not in st.session_state:
        ids = set()
        for caminho in listar_arquivos_travados(aba):
            try:
                # Lê só a coluna necessária — rápido mesmo com muitos arquivos/linhas
                df_tmp = pd.read_parquet(caminho, columns=["EQUIPAMENTO_ID"])
                ids.update(df_tmp["EQUIPAMENTO_ID"].astype(str).tolist())
            except Exception:
                continue
        st.session_state[chave] = ids
    return st.session_state[chave]

def remover_itens_travados(df, aba):
    """Filtra fora do dataframe qualquer equipamento já travado em parquet."""
    if df is None or df.empty:
        return df
    ids_travados = obter_ids_travados(aba)
    if not ids_travados:
        return df
    return df[~df["EQUIPAMENTO_ID"].astype(str).isin(ids_travados)].reset_index(drop=True)

def travar_grupo(aba, contrato_texto, df_grupo_atual):
    """
    Salva os equipamentos deste grupo (um contrato inteiro) em parquet — um
    arquivo por CLIENTE_ID presente no grupo — e remove esses itens da
    tabela editável em memória.
    """
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

    # Remove os itens travados da tabela editável em memória
    ids_travados = set(df_grupo_atual["EQUIPAMENTO_ID"].astype(str))
    st.session_state[aba] = st.session_state[aba][
        ~st.session_state[aba]["EQUIPAMENTO_ID"].astype(str).isin(ids_travados)
    ].reset_index(drop=True)

    invalidar_cache_travados(aba)
    return total_travado

def destravar_arquivo(caminho, aba):
    """Lê o parquet, devolve as linhas para a tabela editável e apaga o arquivo."""
    try:
        df_travado = pd.read_parquet(caminho)
    except Exception as e:
        st.error(f"Erro ao ler arquivo travado: {e}")
        return

    colunas_controle = ["ORGAO", "TRAVADO_EM"]
    df_travado = df_travado.drop(columns=[c for c in colunas_controle if c in df_travado.columns])

    st.session_state[aba] = pd.concat([st.session_state[aba], df_travado], ignore_index=True)
    os.remove(caminho)
    invalidar_cache_travados(aba)

# ==============================================================================
# BUSCA NO BANCO
# ==============================================================================
def buscar_dados_por_orgao(engine, lista_ids):
    lista_ids_str = ", ".join(str(i) for i in lista_ids)
    query = f"""
    SELECT
        alc.id AS id_cliente,
        alc.nome_razao_social AS nome_cliente,
        alq.id AS id_equipamento,
        alq.numero AS tombo,
        alq.nome AS nome_equipamentos,
        am.orgao_id AS orgao_id
    FROM aluguel_equipamentos alq
    INNER JOIN aluguel_movimento_itens ami ON alq.id = ami.equipamento_id
    INNER JOIN aluguel_movimento am ON ami.movimento_id = am.id
    INNER JOIN aluguel_clientes alc ON am.cliente_id = alc.id
    WHERE alq.situacao_id = 1 
      AND am.orgao_id IN ({lista_ids_str}) 
      AND am.deleted_at IS NULL
      AND ami.deleted_at IS NULL 
      AND alc.deleted_at IS NULL
    """
    return pd.read_sql(query, con=engine)

# ==============================================================================
# COLUNAS BASE E CONVERSÕES
# ==============================================================================
def montar_colunas_base(df_bruto, aba):
    df_montado = pd.DataFrame()
    df_montado['CLIENTE_ID'] = df_bruto['id_cliente'].apply(valor_seguro_para_texto)
    df_montado['CLIENTE_NOME'] = df_bruto['nome_cliente'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_ID'] = df_bruto['id_equipamento'].apply(valor_seguro_para_texto)
    df_montado['TOMBO'] = df_bruto['tombo'].apply(valor_seguro_para_texto)
    df_montado['EQUIPAMENTO_NOME'] = df_bruto['nome_equipamentos'].apply(valor_seguro_para_texto)

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

# ==============================================================================
# AUTOMAÇÃO (Instantânea usando o Super Dicionário)
# ==============================================================================
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
        
        chave_contrato = None
        for key in dict_mestre.keys():
            if key == c_norm or key.startswith(c_norm) or c_norm.startswith(key):
                chave_contrato = key
                break
                
        if not chave_contrato:
            return pd.Series([None, None, None, None, True])
            
        contract_id = dict_mestre[chave_contrato]["id"]

        if pd.isna(item_atual) or str(item_atual).strip() == "" or str(item_atual) == '⬇ selecione um item':
            return pd.Series([contract_id, None, None, None, False])

        i_norm = normalizar(item_atual)
        
        if i_norm in dict_mestre[chave_contrato]["itens"]:
            dados = dict_mestre[chave_contrato]["itens"][i_norm]
            return pd.Series([
                contract_id,
                dados["descricao"], 
                dados["quantidade"], 
                str(dados["evento"]), 
                False
            ])
            
        return pd.Series([contract_id, None, None, None, True])

    resultados = df_aba.apply(validar_e_preencher, axis=1)
    
    df_aba["CONTRACT_ID"] = resultados[0]
    df_aba["DESCRICAO_ITEM"] = resultados[1]
    df_aba["QUANTIDADE_ITEM_NO_CONTRATO"] = resultados[2]
    df_aba["ID_EVENTO"] = resultados[3]

    erros_mask = resultados[4] == True
    if erros_mask.sum() > 0:
        df_aba.loc[erros_mask, "ITEM_DO_CONTRATO"] = None
        df_aba.loc[erros_mask, "DESCRICAO_ITEM"] = None
        df_aba.loc[erros_mask, "QUANTIDADE_ITEM_NO_CONTRATO"] = None
        df_aba.loc[erros_mask, "ID_EVENTO"] = None

    return df_aba

def construir_tabela_organizacao(df_bruto, aba):
    df_montado = montar_colunas_base(df_bruto, aba)
    df_montado = aplicar_automacao_no_dataframe(df_montado)
    df_montado = remover_itens_travados(df_montado, aba)  # ← exclui o que já está travado
    return df_montado

# ==============================================================================
# SINCRONIZAÇÃO COMPLETA
# ==============================================================================
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
        df_relatorio.to_csv(ARQUIVO_CSV_RELATORIO, index=False)

# ==============================================================================
# INICIALIZAÇÃO DO ESTADO DA SESSÃO
# ==============================================================================
if "df_contratos" not in st.session_state:
    st.session_state["df_contratos"] = carregar_planilha_local("Contratos")
    
if "itens_de_contratos" not in st.session_state:
    st.session_state["itens_de_contratos"] = carregar_planilha_local("itens_de_contratos")

if "dict_mestre" not in st.session_state:
    if not st.session_state["df_contratos"].empty and not st.session_state["itens_de_contratos"].empty:
        st.session_state["dict_mestre"] = construir_dicionario_mestre(
            st.session_state["df_contratos"], 
            st.session_state["itens_de_contratos"]
        )

if "df_relatorio" not in st.session_state:
    if os.path.exists(ARQUIVO_CSV_RELATORIO):
        st.session_state["df_relatorio"] = pd.read_csv(ARQUIVO_CSV_RELATORIO)
        for aba, lista_ids in MAPPINGS.items():
            df_filtrado = st.session_state["df_relatorio"][
                st.session_state["df_relatorio"]['orgao_id'].isin(lista_ids)
            ].copy()
            st.session_state[aba] = construir_tabela_organizacao(df_filtrado, aba)
    else:
        st.session_state["df_relatorio"] = pd.DataFrame()
        for aba in nomes_abas_memoria:
            st.session_state[aba] = pd.DataFrame()

# ==============================================================================
# BARRA LATERAL
# ==============================================================================
st.sidebar.header("🔄 Sincronizar Banco")
if st.sidebar.button("⚙️ Atualizar Relatório Base", type="secondary"):
    with st.sidebar.status("Executando consultas por organização...", expanded=True) as status:
        try:
            engine = obter_conexao_banco()
            sincronizar_todas_as_abas(engine)
            status.update(label="Sincronização concluída!", state="complete", expanded=False)
            st.rerun()
        except Exception as e:
            status.update(label="Falha na sincronização", state="error", expanded=True)
            st.sidebar.error(f"Erro detalhado: {e}")

if st.session_state["df_contratos"].empty or st.session_state["itens_de_contratos"].empty:
    st.sidebar.markdown("---")
    st.sidebar.error("⚠️ Faltam arquivos base locais!")

st.sidebar.markdown("---")
st.sidebar.subheader("🔒 Itens Travados")
for aba in nomes_abas_memoria:
    qtd = len(listar_arquivos_travados(aba))
    if qtd > 0:
        st.sidebar.caption(f"{aba}: {qtd} contrato(s) travado(s)")

# ==============================================================================
# INTERFACE PRINCIPAL
# ==============================================================================
st.title("🖥️ Painel de Automação de Equipamentos")

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

# ----------------- ABAS -----------------
abas_ui = st.tabs([
    '🏗️ ALUCOM', '🌐 IP SERVIÇOS', '🦈 MOREIA', '🏢 AS SISTEMAS', 
    '📄 Contratos', '📦 Itens de Contrato', '🖥️ View Relatório Banco',
    '🔐 Itens Travados'
], key="aba_principal", on_change="rerun")

for idx_ui, nome_memoria in enumerate(nomes_abas_memoria):
    if not abas_ui[idx_ui].open:
        continue

    with abas_ui[idx_ui]:
        df_aba_atual = st.session_state[nome_memoria]
        qtd_travados = len(obter_ids_travados(nome_memoria))

        if qtd_travados > 0:
            st.info(f"🔒 {qtd_travados} equipamento(s) já travado(s) — veja a aba 'Itens Travados'.")

        if df_aba_atual.empty:
            st.success("✅ Nenhum item pendente de edição nesta organização.")
            continue

        df_aba_atual = df_aba_atual.copy()
        SEM_CONTRATO = "🔓 (SEM CONTRATO DEFINIDO)"
        contratos_agrupados = df_aba_atual['CONTRATO'].replace(r'^\s*$', np.nan, regex=True)
        df_aba_atual['_GRUPO_CONTRATO'] = contratos_agrupados.fillna(SEM_CONTRATO)

        grupos = df_aba_atual['_GRUPO_CONTRATO'].unique().tolist()
        grupos_ordenados = sorted(grupos, key=lambda g: (g == SEM_CONTRATO, g))

        partes_editadas = []
        algo_mudou = False

        for grupo in grupos_ordenados:
            df_grupo = df_aba_atual[df_aba_atual['_GRUPO_CONTRATO'] == grupo].drop(columns=['_GRUPO_CONTRATO'])

            if grupo == SEM_CONTRATO:
                opcoes_item_grupo = []
                titulo_grupo = SEM_CONTRATO
            else:
                opcoes_item_grupo = obter_itens_do_contrato(grupo)
                titulo_grupo = f"📄 {grupo}"

            with st.expander(f"{titulo_grupo}  —  {len(df_grupo)} equipamento(s)", expanded=True):
                config_grupo = dict(configuracao_colunas_base)
                config_grupo["ITEM_DO_CONTRATO"] = st.column_config.SelectboxColumn(
                    "ITEM_DO_CONTRATO", options=opcoes_item_grupo
                )

                df_editado_grupo = st.data_editor(
                    df_grupo,
                    key=f"editor_{nome_memoria}_{slugify_key(grupo)}",
                    num_rows="fixed",
                    use_container_width=True,
                    column_config=config_grupo
                )

                if not df_editado_grupo.equals(df_grupo):
                    algo_mudou = True

                partes_editadas.append(df_editado_grupo)

                # ------------------------------------------------------------
                # 🔒 BOTÃO DE TRAVAMENTO
                # ------------------------------------------------------------
                incompletos = df_editado_grupo["ITEM_DO_CONTRATO"].isna().sum()
                pode_travar = len(df_editado_grupo) > 0

                col_btn, col_msg = st.columns([1, 4])
                with col_btn:
                    clicou_travar = st.button(
                        "🔒 Salvar e Travar",
                        key=f"lock_{nome_memoria}_{slugify_key(grupo)}",
                        disabled=not pode_travar,
                        type="primary"
                    )
                with col_msg:
                    if grupo == SEM_CONTRATO:
                        st.caption("ℹ️ Grupo sem contrato — o salvamento em Parquet está liberado.")
                    elif incompletos > 0:
                        st.caption(f"ℹ️ {incompletos} equipamento(s) sem ITEM_DO_CONTRATO.")
                    else:
                        st.caption("✅ Grupo completo — pronto para ser travado e exportado em Parquet.")

                if clicou_travar:
                    contrato_arquivo = "SEM CONTRATO" if grupo == SEM_CONTRATO else grupo
                    qtd_travada = travar_grupo(nome_memoria, contrato_arquivo, df_editado_grupo)
                    st.success(f"🔒 {qtd_travada} equipamento(s) travado(s) e salvos em Parquet!")
                    st.rerun()

        if algo_mudou:
            df_recombinado = pd.concat(partes_editadas).sort_index()
            df_atualizado = aplicar_automacao_no_dataframe(df_recombinado)
            st.session_state[nome_memoria] = df_atualizado
            st.rerun()

if abas_ui[4].open:
    with abas_ui[4]:
        st.dataframe(st.session_state["df_contratos"], use_container_width=True, height=700)

if abas_ui[5].open:
    with abas_ui[5]:
        st.dataframe(st.session_state["itens_de_contratos"], use_container_width=True, height=700)

if abas_ui[6].open:
    with abas_ui[6]:
        st.dataframe(st.session_state["df_relatorio"], use_container_width=True, height=700)

# ==============================================================================
# 🔐 ABA DE GERENCIAMENTO DOS ARQUIVOS PARQUET
# ==============================================================================
def renderizar_arquivos_parquet():

    # Coleta metadados físicos de todos os arquivos sem ler seus dataframes internos
    arquivos_dados = []
    for aba in nomes_abas_memoria: # Varre todas as organizações diretamente (Filtro removido)
        arquivos = listar_arquivos_travados(aba)
        for caminho in arquivos:
            nome_arquivo = os.path.basename(caminho)
            tamanho_kb = os.path.getsize(caminho) / 1024
            data_mod = datetime.fromtimestamp(os.path.getmtime(caminho)).strftime('%d/%m/%Y %H:%M:%S')
            
            arquivos_dados.append({
                "Organização": aba,
                "Nome do Arquivo": nome_arquivo,
                "Tamanho (KB)": round(tamanho_kb, 2),
                "Atualizado em": data_mod,
                "caminho_completo": caminho
            })

    if arquivos_dados:
        df_arquivos_parquet = pd.DataFrame(arquivos_dados)
        st.subheader("🔓 Painel de Itens Salvos")
        st.caption("Selecione abaixo o lote que deseja reabrir para edição na tabela principal.")
        st.caption("Lotes são salvos por ORGANIZAÇÃO - CLIENTE - CONTRATO.")
        
        # Controle unificado de ações para evitar poluição visual de botões repetidos
        col_sel, col_btn = st.columns([4, 1])
        with col_sel:
            arquivo_selecionado = st.selectbox(
                "Escolha o lote para destravar:",
                options=df_arquivos_parquet["Nome do Arquivo"].tolist(),
                key="sb_destravar_parquet"
            )
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)  # Alinhamento vertical com o selectbox
            if st.button("🔓 Destravar Lote", type="secondary", use_container_width=True):
                linha_arq = df_arquivos_parquet[df_arquivos_parquet["Nome do Arquivo"] == arquivo_selecionado].iloc[0]
                destravar_arquivo(linha_arq["caminho_completo"], linha_arq["Organização"])
                st.rerun()
    else:
        st.info("Nenhum arquivo Parquet encontrado no diretório local. Selecione um contrato em uma das abas de organização e clique em '🔒 Salvar e Travar' para gerar os lotes.")

# Renderiza somente quando a aba correspondente estiver ativa.
if abas_ui[7].open:
    with abas_ui[7]:
        renderizar_arquivos_parquet()
