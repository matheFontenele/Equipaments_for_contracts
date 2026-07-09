import streamlit as st
import pandas as pd
import numpy as np
from utils.text_processing import normalizar, limpar_filtro, slugify_key
from services.dictionary_service import obter_itens_do_contrato, aplicar_automacao_no_dataframe
from services.locking_service import obter_ids_travados, travar_grupo

def renderizar_aba_organizacao(nome_memoria, configuracao_colunas_base):
    df_aba_atual = st.session_state[nome_memoria]
    qtd_travados = len(obter_ids_travados(nome_memoria))

    if qtd_travados > 0:
        st.info(f"🔒 {qtd_travados} equipamento(s) já travado(s) — veja a aba 'Itens Travados'.")

    if df_aba_atual.empty:
        st.success("✅ Nenhum item pendente de edição nesta organização.")
        return

    # Painel de Filtros de pesquisa rápida
    chave_filtro = f"filtro_{nome_memoria}"
    col_filtro, col_limpar = st.columns([5, 1])
    with col_filtro:
        termo_busca = st.text_input("🔍 Filtrar por cliente (nome, ID ou tombo)", key=chave_filtro, placeholder="Digite parte do nome, ID do cliente ou tombo...")
    with col_limpar:
        st.markdown("<div style='height: 1.7em'></div>", unsafe_allow_html=True)
        st.button("🧹 Limpar", key=f"btn_limpar_{nome_memoria}", use_container_width=True, on_click=limpar_filtro, args=(chave_filtro,))

    if termo_busca:
        termo_norm = normalizar(termo_busca)
        mask_filtro = (
            df_aba_atual['CLIENTE_NOME'].apply(normalizar).str.contains(termo_norm, na=False, regex=False) |
            df_aba_atual['CLIENTE_ID'].astype(str).str.contains(termo_busca, na=False, regex=False) |
            df_aba_atual['TOMBO'].astype(str).str.contains(termo_busca, na=False, regex=False)
        )
        df_visivel = df_aba_atual[mask_filtro]
        st.caption(f"🔎 Mostrando {len(df_visivel)} de {len(df_aba_atual)} equipamento(s) para o filtro '{termo_busca}'.")
    else:
        df_visivel = df_aba_atual

    if df_visivel.empty:
        st.warning("Nenhum equipamento encontrado para este filtro.")
        return

    df_visivel = df_visivel.copy()
    SEM_CONTRATO = "🔓 (SEM CONTRATO DEFINIDO)"
    contratos_agrupados = df_visivel['CONTRATO'].replace(r'^\s*$', np.nan, regex=True)
    df_visivel['_GRUPO_CONTRATO'] = contratos_agrupados.fillna(SEM_CONTRATO)

    grupos_ordenados = sorted(df_visivel['_GRUPO_CONTRATO'].unique().tolist(), key=lambda g: (g == SEM_CONTRATO, g))
    partes_editadas = []
    algo_mudou = False

    for grupo in grupos_ordenados:
        df_grupo = df_visivel[df_visivel['_GRUPO_CONTRATO'] == grupo].drop(columns=['_GRUPO_CONTRATO'])
        opcoes_item_grupo = [] if grupo == SEM_CONTRATO else obter_itens_do_contrato(grupo)
        titulo_grupo = SEM_CONTRATO if grupo == SEM_CONTRATO else f"📄 {grupo}"

        with st.expander(f"{titulo_grupo}  —  {len(df_grupo)} equipamento(s)", expanded=True):
            config_grupo = dict(configuracao_colunas_base)
            config_grupo["ITEM_DO_CONTRATO"] = st.column_config.SelectboxColumn("ITEM_DO_CONTRATO", options=opcoes_item_grupo)

            df_editado_grupo = st.data_editor(df_grupo, key=f"editor_{nome_memoria}_{slugify_key(grupo)}", num_rows="fixed", use_container_width=True, column_config=config_grupo)

            if not df_editado_grupo.equals(df_grupo):
                algo_mudou = True

            partes_editadas.append(df_editado_grupo)

            incompletos = df_editado_grupo["ITEM_DO_CONTRATO"].isna().sum()
            col_btn, col_msg = st.columns([1, 4])
            with col_btn:
                clicou_travar = st.button("🔒 Salvar e Travar", key=f"lock_{nome_memoria}_{slugify_key(grupo)}", disabled=not (len(df_editado_grupo) > 0), type="primary")
            with col_msg:
                if grupo == SEM_CONTRATO:
                    st.caption("ℹ️ Grupo sem contrato — o salvamento em Parquet está liberado.")
                elif incompletos > 0:
                    st.caption(f"ℹ️ {incompletos} equipamento(s) sem ITEM_DO_CONTRATO.")
                else:
                    st.caption("✅ Grupo completo — pronto para ser travado.")

            if clicou_travar:
                contrato_arquivo = "SEM CONTRATO" if grupo == SEM_CONTRATO else grupo
                qtd_travada = travar_grupo(nome_memoria, contrato_arquivo, df_editado_grupo)
                st.success(f"🔒 {qtd_travada} equipamento(s) travado(s) e salvos em Parquet!")
                st.rerun()

    if algo_mudou:
        df_editado_completo = pd.concat(partes_editadas).sort_index()
        df_aba_atual.loc[df_editado_completo.index, df_editado_completo.columns] = df_editado_completo
        st.session_state[nome_memoria] = aplicar_automacao_no_dataframe(df_aba_atual)
        st.rerun()