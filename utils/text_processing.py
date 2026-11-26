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

# Cada aba é uma empresa (órgão "dono"); um contrato só pode ser usado na aba
# da empresa à qual ele pertence (contracts.organization_id). Sem essa
# restrição, um cliente homônimo de outra aba "herda" o contrato errado — por
# exemplo, a URBANTECH da MOREIA recebia o contrato da IP SERVIÇOS.
ABA_POR_ORGAO = {orgao: aba for aba, orgaos in MAPPINGS.items() for orgao in orgaos}


def aba_da_organizacao(orgao_id):
    """Aba dona do órgão, ou ``None`` quando o órgão não está em nenhum MAPPING."""
    try:
        return ABA_POR_ORGAO.get(int(orgao_id))
    except (TypeError, ValueError):
        return None

# ==============================================================================
# FUNÇÕES DE TRATAMENTO DE TEXTO
# ==============================================================================
def normalizar(texto):
    if pd.isna(texto) or str(texto).strip() == "":
        return ""
    texto_norm = unicodedata.normalize("NFD", str(texto))
    texto_norm = "".join([c for c in texto_norm if unicodedata.category(c) != "Mn"])
    return " ".join(texto_norm.split()).upper()

# ==============================================================================
# MUNICÍPIO — GUARDA CONTRA CASAMENTO ENTRE MUNICÍPIOS DIFERENTES
# ==============================================================================
_PREFIXO_MUNICIPAL = {"PREFEITURA", "PREF", "P", "M", "PM", "MUNICIPAL", "MUNICIPIO", "GOVERNO"}
# Só aliases que começam assim identificam município com segurança.
# UFSC, consórcios, empresas, cartórios e secretarias ficam de fora.
_MARCADORES_MUNICIPAIS = {"PREFEITURA", "PREF", "PM", "MUNICIPIO", "GOVERNO"}
_CONECTORES_MUNICIPIO = {"DE", "DO", "DA", "DOS", "DAS", "EM"}
_UFS = {"AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
        "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
        "SE", "SP", "TO"}
# Palavras que não distinguem município (ou que indicam que o alias é de secretaria)
_NAO_MUNICIPAL = {
    "SECRETARIA", "SEC", "DEPARTAMENTO", "FUNDO", "CAMARA", "CONTROLADORIA",
    "GABINETE", "HOSPITAL", "INSTITUTO", "AUTARQUIA", "SAAE", "COORDENADORIA",
    "SUPERINTENDENCIA", "PROCURADORIA", "OUVIDORIA", "ESCOLA", "CENTRO",
    "UNIDADE", "ADMINISTRACAO", "FINANCAS", "EDUCACAO", "SAUDE", "ASSISTENCIA",
    "TRABALHO", "CULTURA", "ESPORTE", "OBRAS", "INFRAESTRUTURA", "URBANISMO",
    "PLANEJAMENTO", "DESENVOLVIMENTO", "RURAL", "AGRICULTURA", "SEGURANCA",
    "TRANSITO", "TURISMO", "MEIO", "AMBIENTE", "ESTADO", "UNIAO", "FEDERAL",
    # Marcadores de situação/anotação que aparecem grudados no município
    "CONTRATO", "ENCERRADO", "RECOLHIDO", "ATIVO", "REVOGADO", "VIGENTE",
    "DEVOLVIDO", "DEVOLVIDOS", "ANOS", "EQUIP",
}
_GENERICOS_MUNICIPIO = {"DE", "DO", "DA", "DOS", "DAS", "SAO", "SANTA", "SANTO",
                        "NORTE", "SUL", "LESTE", "OESTE", "NOVA", "NOVO",
                        "GRANDE", "PEQUENO", "PEQUENA"}

def tokens_municipio(alias):
    """Extrai tokens distintivos do município a partir do alias do cliente do contrato.

    Ex.: 'PREFEITURA MUNICIPAL DE MARANGUAPE' -> {'MARANGUAPE'}
         'P M DE JUAZEIRO DO NORTE'           -> {'JUAZEIRO'}
         'SECRETARIA DE SAUDE - FMS'          -> set()  (não identificável)
         'UFSC - FLORIANOPOLIS'               -> set()  (não é município)
    """
    texto = normalizar(alias)
    if not texto:
        return set()

    # Nome do órgão após separadores (" - ", "/", ",") não identifica município
    texto = re.split(r"\s*[-/,]\s*", texto)[0]
    # Pontuação vira espaço para lidar com "P.M. DE ARACOIABA" e "P. M. DE X"
    tokens = re.sub(r"[^A-Z0-9 ]", " ", texto).split()

    # Sem marcador municipal no início, o alias não é de prefeitura
    if not tokens:
        return set()
    if tokens[0] not in _MARCADORES_MUNICIPAIS:
        if not (tokens[0] == "P" and len(tokens) > 1 and tokens[1] == "M"):
            return set()

    while tokens and tokens[0] in _PREFIXO_MUNICIPAL:
        tokens.pop(0)
    while tokens and tokens[0] in _CONECTORES_MUNICIPIO:
        tokens.pop(0)
    while tokens and (tokens[-1] in _UFS or re.fullmatch(r"(19|20)\d{2}", tokens[-1])):
        tokens.pop()

    # O nome do município termina no primeiro token que não pode ser município
    # (ex.: "P M DE INDEPENDENCIA CONTRATO ENCERRADO ..." -> INDEPENDENCIA).
    corte = next((i for i, tok in enumerate(tokens) if tok in _NAO_MUNICIPAL), len(tokens))
    tokens = tokens[:corte]

    if not tokens:
        return set()

    return {tok for tok in tokens if tok not in _GENERICOS_MUNICIPIO and len(tok) > 1}

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