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
        st.caption("Selecione abaixo o lote que deseja reabrir para edição na tabela principal.")
        
        col_sel, col_btn = st.columns([4, 1])
        with col_sel:
            arquivo_selecionado = st.selectbox("Escolha o lote para destravar:", options=df_arquivos_parquet["Nome do Arquivo"].tolist(), key="sb_destravar_parquet")
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔓 Destravar Lote", type="secondary", use_container_width=True):
                linha_arq = df_arquivos_parquet[df_arquivos_parquet["Nome do Arquivo"] == arquivo_selecionado].iloc[0]
                destravar_arquivo(linha_arq["caminho_completo"], linha_arq["Organização"])
                st.rerun()
    else:
        st.info("Nenhum arquivo Parquet encontrado no diretório local.")