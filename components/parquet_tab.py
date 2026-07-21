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
        st.caption("Selecione abaixo os lotes que deseja reabrir, ou exporte a base consolidada para migração.")
        
        # 1. Seleção Múltipla
        arquivos_selecionados = st.multiselect(
            "Escolha os lotes para destravar ou exportar (você pode selecionar vários):", 
            options=df_arquivos_parquet["Nome do Arquivo"].tolist(), 
            key="ms_destravar_parquet",
            placeholder="Clique ou digite para buscar o lote..."
        )
        
        # 2. Layout de botões (Agora com 3 colunas)
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔓 Destravar Selecionados", type="secondary", disabled=len(arquivos_selecionados) == 0, use_container_width=True):
                with st.spinner("Destravando lotes selecionados..."):
                    for arquivo in arquivos_selecionados:
                        linha_arq = df_arquivos_parquet[df_arquivos_parquet["Nome do Arquivo"] == arquivo].iloc[0]
                        destravar_arquivo(linha_arq["caminho_completo"], linha_arq["Organização"])
                st.rerun()

        with col2:
            if st.button("🚨 Destravar TODOS", type="secondary", use_container_width=True):
                with st.spinner("Limpando trava de todos os lotes..."):
                    for _, linha_arq in df_arquivos_parquet.iterrows():
                        destravar_arquivo(linha_arq["caminho_completo"], linha_arq["Organização"])
                st.rerun()

        with col3:
            # Define se vai exportar apenas os que foram marcados no selectbox ou a base inteira
            nomes_alvo = arquivos_selecionados if arquivos_selecionados else df_arquivos_parquet["Nome do Arquivo"].tolist()
            df_alvo = df_arquivos_parquet[df_arquivos_parquet["Nome do Arquivo"].isin(nomes_alvo)]
            
            try:
                # O Pandas lê todos os arquivos bloqueados na velocidade da luz
                dfs_para_exportar = [pd.read_parquet(caminho) for caminho in df_alvo["caminho_completo"]]
                
                if dfs_para_exportar:
                    # Cola todos os DataFrames um embaixo do outro
                    df_mestre = pd.concat(dfs_para_exportar, ignore_index=True)
                    
                    # Converte o dataframe gigante resultante de volta para formato Parquet (na memória)
                    parquet_bytes = df_mestre.to_parquet(index=False)
                    
                    texto_btn = "📦 Baixar Selecionados" if arquivos_selecionados else "📦 Baixar Dados"
                    
                    # O st.download_button nativo do Streamlit joga o arquivo direto pro navegador do usuário
                    st.download_button(
                        label=texto_btn,
                        data=parquet_bytes,
                        file_name=f"MIGRACAO_{datetime.now().strftime('%Y%m%d_%H%M')}.parquet",
                        mime="application/octet-stream",
                        use_container_width=True,
                        type="primary"
                    )
            except Exception as e:
                st.error(f"Não foi possível gerar o arquivo consolidado. Erro: {e}")

        # 3. Tabela Visual
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("##### 📋 Visão Geral dos Lotes Travados")
        st.dataframe(df_arquivos_parquet.drop(columns=["caminho_completo"]), width="stretch")
        
    else:
        st.info("Nenhum arquivo Parquet encontrado no diretório local. Todos os lotes estão destravados.")