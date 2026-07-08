# Painel de Automacao de Equipamentos

Aplicacao Streamlit para consultar equipamentos alugados no banco legado, organizar os registros por empresa, relaciona-los a contratos e itens de contrato e salvar lotes validados em arquivos Parquet.

## Visao geral

O fluxo principal da aplicacao e:

1. Carregar as planilhas locais de contratos e itens de contrato.
2. Consultar no MySQL os equipamentos ativos de cada organizacao configurada.
3. Separar os equipamentos nas abas `ALUCOM`, `IP SERVICOS`, `MOREIA` e `AS SISTEMAS`.
4. Permitir a selecao de contrato e, opcionalmente, do item de contrato.
5. Salvar os grupos em `locks_parquet/`, removendo-os temporariamente das tabelas editaveis.
6. Permitir que um lote seja destravado, devolvendo seus registros para edicao.

Os equipamentos podem ser salvos em Parquet mesmo quando `CONTRATO` ou
`ITEM_DO_CONTRATO` ainda nao estiver preenchido.

## Requisitos

- Docker e Docker Compose; ou
- Python 3.11 com as dependencias de `requirements.txt`;
- acesso ao banco MySQL legado;
- arquivos-base de contratos e itens de contrato no diretorio raiz.

O projeto utiliza recursos de abas com carregamento sob demanda. Use uma versao atual do Streamlit; o ambiente atual foi validado com Streamlit 1.59.0.

## Execucao com Docker

O modo recomendado e executar pelo Docker Compose:

```bash
docker compose up --build -d
```

A aplicacao ficara disponivel em:

```text
http://localhost:8501
```

Para acompanhar os logs:

```bash
docker compose logs -f app-automacao
```

O volume `.:/app` mantem os CSVs e Parquets no diretorio do projeto, mesmo quando o container e recriado.

## Execucao local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Na execucao local, o host padrao do banco e `localhost`.

## Configuracao do banco de dados

A conexao atual e montada em `app.py` com os seguintes valores:

| Configuracao | Valor atual | Como alterar |
|---|---:|---|
| Host | `localhost` | Variavel `DB_HOST_NEW` |
| Porta | `3307` | Alteracao em `app.py` |
| Banco | `aluguel_legado` | Alteracao em `app.py` |
| Usuario | `root` | Alteracao em `app.py` |
| Senha | `root` | Alteracao em `app.py` |
| Driver | `mysql+pymysql` | Alteracao em `app.py` |

Formato equivalente da URL:

```text
mysql+pymysql://root:root@<DB_HOST_NEW>:3307/aluguel_legado
```

No `docker-compose.yml`, `DB_HOST_NEW` recebe `host.docker.internal`. A entrada em `extra_hosts` permite que o container acesse um MySQL executado na maquina hospedeira, inclusive em Linux.

Para apontar para outro servidor:

```yaml
environment:
  - DB_HOST_NEW=192.168.1.100
```

Ou, na execucao local:

```bash
DB_HOST_NEW=192.168.1.100 streamlit run app.py
```

> **Seguranca:** usuario e senha estao fixos no codigo. Antes de usar o projeto fora de um ambiente controlado, mova tambem porta, banco, usuario e senha para variaveis de ambiente e utilize um usuario MySQL com permissoes somente de leitura.

### Estrutura consultada

A sincronizacao le as tabelas:

- `aluguel_equipamentos`;
- `aluguel_movimento_itens`;
- `aluguel_movimento`;
- `aluguel_clientes`.

Somente equipamentos com `situacao_id = 1` e registros nao excluidos logicamente sao carregados. A separacao entre empresas utiliza `orgao_id` e os conjuntos definidos em `MAPPINGS`, dentro de `app.py`.

Para alterar quais orgaos pertencem a cada empresa, ajuste:

```python
MAPPING_ALUCOM = {...}
MAPPING_IP = {...}
MAPPING_MOREIA = {...}
MAPPING_AS = {...}
```

## Padrao dos arquivos

Todos os arquivos devem ficar no diretorio raiz do projeto, exceto os Parquets, que ficam em `locks_parquet/`.

### 1. Cadastro de contratos

Nome aceito, em ordem de prioridade:

1. `Contratos.xlsx`;
2. `Contratos.csv`.

Se os dois existirem, o XLSX sera utilizado. Para CSV, use codificacao UTF-8 e separador por virgula.

Colunas principais:

| Coluna | Obrigatoria | Finalidade |
|---|---|---|
| `CONTRATOS` | Sim | Nome exibido para selecao do contrato |
| `CONTRACT_ID` | Sim | Identificador do contrato |
| `CLIENTE` | Nao | Informacao auxiliar |
| `ORGANIZACAO` | Nao | Informacao auxiliar |
| `NUMERO_CONTRATO` | Nao | Informacao auxiliar |
| `NUMERO_MAIS_CONTRATO` | Nao | Informacao auxiliar |

Exemplo:

```csv
CONTRATOS,CLIENTE,ORGANIZACAO,NUMERO_CONTRATO,NUMERO_MAIS_CONTRATO,CONTRACT_ID
ALECE,ASSEMBLEIA LEGISLATIVA DO ESTADO DO CEARA,ALUCOM,97-2025,ALECE - 97-2025,3
```

### 2. Cadastro de itens de contrato

Nome aceito, em ordem de prioridade:

1. `itens_de_contratos.xlsx`;
2. `itens_de_contratos.csv`.

Colunas esperadas:

| Coluna | Obrigatoria | Finalidade |
|---|---|---|
| `EVENTO` | Sim | Identificador/versao do item |
| `TIPO_EVENTO` | Nao | Tipo do evento de origem |
| `CONTRATO` | Sim | Nome correspondente a `CONTRATOS` |
| `APELIDO` | Sim | Texto mostrado no seletor de itens |
| `DESCRICAO` | Sim | Descricao preenchida automaticamente |
| `QUANTIDADE` | Sim | Quantidade prevista no contrato |

Exemplo:

```csv
EVENTO,TIPO_EVENTO,CONTRATO,APELIDO,DESCRICAO,QUANTIDADE
6,CADASTRO,ALECE,NOBREAK 700 VA,UPS MAX SECURITY 700VA 115V,30
```

Quando houver mais de um registro com o mesmo contrato e apelido, a aplicacao utiliza o registro de maior `EVENTO`.

### 3. Relatorio gerado pelo banco

Arquivo: `relatorio_banco.csv`.

Ele e recriado ao clicar em **Atualizar Relatorio Base** e tambem e usado como cache na inicializacao da aplicacao.

Colunas:

```text
id_cliente,nome_cliente,id_equipamento,tombo,nome_equipamentos,orgao_id,aba_origem
```

Se esse arquivo nao existir, as abas de organizacao permanecerao vazias ate a primeira sincronizacao com o banco.

### 4. Arquivos Parquet

Diretorio: `locks_parquet/`.

Cada arquivo representa os equipamentos de um contrato para um cliente. Equipamentos ainda sem
contrato tambem podem ser salvos e usam `SEMID-SEM-CONTRATO` na identificacao do lote. O nome segue o padrao:

```text
<ORGANIZACAO>__C<CONTRACT_ID>-<CONTRATO>__CLI<CLIENTE_ID>-<CLIENTE>.parquet
```

Exemplo:

```text
ALUCOM__C197-GOVERNO-MUNICIPAL-DE-URUOCA__CLI868-PMURUOCASECEDU.parquet
```

Os trechos textuais do nome sao convertidos para letras maiusculas, sem acentos e sem caracteres especiais. Espacos viram hifens.

Colunas armazenadas:

```text
CLIENTE_ID
CLIENTE_NOME
EQUIPAMENTO_ID
TOMBO
EQUIPAMENTO_NOME
CONTRACT_ID
CONTRATO
ITEM_DO_CONTRATO
DESCRICAO_ITEM
QUANTIDADE_ITEM_NO_CONTRATO
ID_EVENTO
TIPO_EQUIPAMENTO
ORGAO
TRAVADO_EM
```

As colunas `ORGAO` e `TRAVADO_EM` sao adicionadas no momento do salvamento. Ao destravar, o arquivo e lido, essas duas colunas de controle sao removidas e o Parquet e excluido.

Enquanto um `EQUIPAMENTO_ID` estiver presente em um Parquet, ele nao aparece novamente na tabela editavel da mesma organizacao.

## Estrutura do projeto

```text
.
|-- app.py                      # Aplicacao Streamlit
|-- requirements.txt            # Dependencias Python
|-- Dockerfile                  # Imagem da aplicacao
|-- docker-compose.yml          # Execucao e acesso ao host
|-- Contratos.csv/.xlsx         # Cadastro local de contratos
|-- itens_de_contratos.csv/.xlsx# Cadastro local de itens
|-- relatorio_banco.csv         # Cache gerado pela sincronizacao
`-- locks_parquet/              # Lotes salvos/travados
```

## Persistencia e Git

O `.gitignore` atual ignora arquivos CSV e a pasta `locks_parquet/`. Portanto:

- os dados gerados nao devem ser tratados como backup;
- os arquivos-base em CSV precisam ser fornecidos manualmente em uma nova instalacao;
- mantenha backup externo dos Parquets enquanto eles forem necessarios;
- evite versionar planilhas com dados pessoais ou credenciais.

Ao usar Docker, mantenha o volume do projeto montado ou substitua-o por um volume persistente dedicado para nao perder os lotes.

## Solucao de problemas

### Falha ao conectar ao banco

Confirme se:

- o MySQL esta acessivel na porta `3307`;
- o banco `aluguel_legado` existe;
- as credenciais configuradas estao corretas;
- `DB_HOST_NEW` aponta para o host correto;
- o firewall permite a conexao a partir do container.

### Mensagem de arquivos-base ausentes

Verifique se `Contratos.csv`/`.xlsx` e `itens_de_contratos.csv`/`.xlsx` estao na raiz e se os nomes respeitam maiusculas, minusculas e sublinhados.

### Erro ao salvar Parquet

Confirme se o processo possui permissao de escrita em `locks_parquet/` e se as dependencias de `requirements.txt` foram instaladas no mesmo ambiente que executa o Streamlit.
