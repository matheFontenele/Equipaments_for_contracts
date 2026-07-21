import streamlit as st
import pandas as pd
import os
from datetime import datetime
from services.locking_service import listar_arquivos_travados, destravar_arquivo
from utils.text_processing import nomes_abas_memoria

def renderizar_arquivos_parquet():
    arquivos_dados = []
    for aba in nomes_abas_memoria:
        for caminho in listar_arquivos_travados(aba):
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
        st.caption("Selecione abaixo os lotes que deseja reabrir para edição na tabela principal.")
        
        # 1. Troca do Selectbox pelo Multiselect
        arquivos_selecionados = st.multiselect(
            "Escolha os lotes para destravar (você pode selecionar vários):", 
            options=df_arquivos_parquet["Nome do Arquivo"].tolist(), 
            key="ms_destravar_parquet",
            placeholder="Clique ou digite para buscar o lote..."
        )
        
        # 2. Layout de botões
        col1, col2 = st.columns(2)
        
        with col1:
            # Botão de destrava múltipla (só fica clicável se pelo menos 1 arquivo for selecionado)
            if st.button("🔓 Destravar Selecionados", type="primary", disabled=len(arquivos_selecionados) == 0, use_container_width=True):
                with st.spinner("Destravando lotes selecionados..."):
                    for arquivo in arquivos_selecionados:
                        # Puxa os dados daquele arquivo específico
                        linha_arq = df_arquivos_parquet[df_arquivos_parquet["Nome do Arquivo"] == arquivo].iloc[0]
                        destravar_arquivo(linha_arq["caminho_completo"], linha_arq["Organização"])
                st.rerun()

        with col2:
            # Botão de destrava em massa absoluta (Pânico/Reset)
            if st.button("🚨 Destravar TODOS os Lotes", type="secondary", use_container_width=True):
                with st.spinner("Limpando trava de todos os lotes..."):
                    # Varre a tabela inteira e destrava um por um
                    for _, linha_arq in df_arquivos_parquet.iterrows():
                        destravar_arquivo(linha_arq["caminho_completo"], linha_arq["Organização"])
                st.rerun()

        # 3. Tabela Visual (Aproveitando os dados de Tamanho e Data que você já puxava)
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("##### 📋 Visão Geral dos Lotes Travados")
        # Exibe a tabela ocultando a coluna do caminho (que é feia para o usuário)
        st.dataframe(df_arquivos_parquet.drop(columns=["caminho_completo"]), width="stretch")
        
    else:
        st.info("Nenhum arquivo Parquet encontrado no diretório local. Todos os lotes estão destravados.")