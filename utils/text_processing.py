import unicodedata
import re
import hashlib
import pandas as pd
import streamlit as st

# ==============================================================================
# MAPEAMENTO DE ÓRGÃOS E ABAS
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
# FUNÇÕES DE TRATAMENTO DE TEXTO
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
    return hashlib.md5(str(texto).encode('utf-8')).hexdigest()[:12]

def slugify_arquivo(texto, max_len=40):
    texto_norm = normalizar(texto)
    texto_norm = texto_norm.replace(" ", "-")
    texto_norm = re.sub(r'[^A-Z0-9\-]', '', texto_norm)
    return texto_norm[:max_len].strip('-') or "SEMNOME"

def limpar_filtro(chave):
    st.session_state[chave] = ""