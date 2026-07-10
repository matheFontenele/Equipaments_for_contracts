import streamlit as st
import pandas as pd
import numpy as np
from utils.text_processing import normalizar, limpar_filtro, slugify_key
from services.dictionary_service import obter_itens_do_contrato, aplicar_automacao_no_dataframe
from services.locking_service import obter_ids_travados, travar_grupo
from services.rules_engine import MotorDeRegras

def renderizar_aba_organizacao(nome_memoria, configuracao_colunas_base, opcoes_contratos):
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
    else:
        df_visivel = df_aba_atual

    if df_visivel.empty:
        st.warning("Nenhum equipamento encontrado para este filtro.")
        return

    # ----------------------------------------------------------------
    # 🔍 SEPARAÇÃO COMPONENTE: ITENS REGULARES VS ITENS EXTRAS
    # ----------------------------------------------------------------
    if "IS_EXTRA_KIT" in df_visivel.columns:
        df_extras = df_visivel[df_visivel["IS_EXTRA_KIT"] == True].copy()
        df_visivel = df_visivel[df_visivel["IS_EXTRA_KIT"] != True].copy()
    else:
        df_extras = pd.DataFrame()

    if termo_busca and not df_visivel.empty:
        st.caption(f"🔎 Mostrando {len(df_visivel)} equipamento(s) regulares para o filtro '{termo_busca}'.")

    # ----------------------------------------------------------------
    # AGRUPAMENTO E RENDERIZAÇÃO DA LISTAGEM PADRÃO
    # ----------------------------------------------------------------
    partes_editadas = []
    algo_mudou = False

    if not df_visivel.empty:
        df_visivel = df_visivel.copy()
        SEM_CONTRATO = "🔓 (SEM CONTRATO DEFINIDO)"
        contratos_agrupados = df_visivel['CONTRATO'].replace(r'^\s*$', np.nan, regex=True)
        df_visivel['_GRUPO_CONTRATO'] = contratos_agrupados.fillna(SEM_CONTRATO)

        grupos_ordenados = sorted(df_visivel['_GRUPO_CONTRATO'].unique().tolist(), key=lambda g: (g == SEM_CONTRATO, g))

        for grupo in grupos_ordenados:
            df_grupo = df_visivel[df_visivel['_GRUPO_CONTRATO'] == grupo].drop(columns=['_GRUPO_CONTRATO'])
            
            # Adicionamos a opção vazia ("") no dropdown dos itens
            opcoes_item_grupo = [""] if grupo == SEM_CONTRATO else [""] + obter_itens_do_contrato(grupo)
            titulo_grupo = SEM_CONTRATO if grupo == SEM_CONTRATO else f"📄 {grupo}"

            with st.expander(f"{titulo_grupo}  —  {len(df_grupo)} equipamento(s)", expanded=True):
                config_grupo = dict(configuracao_colunas_base)
                config_grupo["ITEM_DO_CONTRATO"] = st.column_config.SelectboxColumn("ITEM_DO_CONTRATO", options=opcoes_item_grupo)

                df_editado_grupo = st.data_editor(df_grupo, key=f"editor_{nome_memoria}_{slugify_key(grupo)}", num_rows="fixed", use_container_width=True, column_config=config_grupo)

                if not df_editado_grupo.equals(df_grupo):
                    algo_mudou = True

                partes_editadas.append(df_editado_grupo)

                # ------------------------------------------------------------
                # 🤖 BOTÕES DE AÇÃO (IA e TRAVAMENTO)
                # ------------------------------------------------------------
                incompletos = df_editado_grupo["ITEM_DO_CONTRATO"].isna().sum()
                pode_travar = len(df_editado_grupo) > 0

                col_btn_ia, col_btn_lock, col_msg = st.columns([1.5, 1.5, 3])
                
                with col_btn_ia:
                    if incompletos > 0:
                        clicou_ia = st.button("🪄 Auto-Preencher", key=f"ia_{nome_memoria}_{slugify_key(grupo)}", use_container_width=True)
                    else:
                        clicou_ia = False

                with col_btn_lock:
                    clicou_travar = st.button("🔒 Salvar e Travar", key=f"lock_{nome_memoria}_{slugify_key(grupo)}", disabled=not pode_travar, type="primary", use_container_width=True)
                    
                with col_msg:
                    if grupo == SEM_CONTRATO:
                        st.caption("ℹ️ Grupo sem contrato — o salvamento em Parquet está liberado.")
                    elif incompletos > 0:
                        st.caption(f"ℹ️ {incompletos} equipamento(s) sem ITEM_DO_CONTRATO.")
                    else:
                        st.caption("✅ Grupo completo — pronto para ser travado.")

                # ------------------------------------------------------------
                # AÇÕES DOS BOTÕES
                # ------------------------------------------------------------
                if clicou_ia:
                    motor = MotorDeRegras(opcoes_contratos, st.session_state["dict_mestre"])
                    
                    novas_colunas = df_editado_grupo.apply(motor.processar_linha, axis=1)
                    df_editado_grupo['CONTRATO'] = novas_colunas[0]
                    df_editado_grupo['ITEM_DO_CONTRATO'] = novas_colunas[1]
                    
                    df_editado_completo = pd.concat(partes_editadas).sort_index()
                    df_aba_atual.loc[df_editado_completo.index, df_editado_completo.columns] = df_editado_completo
                    st.session_state[nome_memoria] = aplicar_automacao_no_dataframe(df_aba_atual)
                    st.rerun()

                if clicou_travar:
                    contrato_arquivo = "SEM CONTRATO" if grupo == SEM_CONTRATO else grupo
                    qtd_travada = travar_grupo(nome_memoria, contrato_arquivo, df_editado_grupo)
                    st.success(f"🔒 {qtd_travada} equipamento(s) travado(s) e salvos em Parquet!")
                    st.rerun()

    # Salva as alterações feitas manualmente na tabela regular
    if algo_mudou:
        df_editado_completo = pd.concat(partes_editadas).sort_index()
        df_aba_atual.loc[df_editado_completo.index, df_editado_completo.columns] = df_editado_completo
        st.session_state[nome_memoria] = aplicar_automacao_no_dataframe(df_aba_atual)
        st.rerun()

    # ----------------------------------------------------------------
    # 📦 PAINEL ISOLADO: EXTRA ITENS (ITENS EXTRAS) - AGORA EDITÁVEL
    # ----------------------------------------------------------------
    if not df_extras.empty:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("### 📦 Extra Itens (Fora do Escopo do Contrato)")
        st.info("Estes equipamentos pertencem a categorias de Kit (Monitores, Estabilizadores, etc.), porém os contratos selecionados não possuem esses itens previstos em contrato. Você pode editá-los manualmente aqui.")
        
        df_extras_exibicao = df_extras.drop(columns=["IS_EXTRA_KIT"], errors="ignore")
        
        df_extras_editado = st.data_editor(
            df_extras_exibicao,
            key=f"editor_extras_{nome_memoria}",
            use_container_width=True,
            column_config=configuracao_colunas_base
        )
        
        # Se o utilizador alterar o contrato ou remover o status de extra
        if not df_extras_editado.equals(df_extras_exibicao):
            df_aba_atual.loc[df_extras_editado.index, df_extras_editado.columns] = df_extras_editado
            st.session_state[nome_memoria] = aplicar_automacao_no_dataframe(df_aba_atual)
            st.rerun()