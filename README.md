# Painel de Automacao de Equipamentos

Aplicacao Streamlit para consultar equipamentos alugados no banco legado, separar os registros por organizacao, vincular contratos e itens de contrato, e salvar lotes validados em arquivos Parquet.

## Visao geral

O app apoia o seguinte fluxo:

1. Carregar os cadastros locais de contratos e itens de contrato em `docs/`.
2. Sincronizar equipamentos ativos do MySQL legado por grupos de orgaos.
3. Exibir os equipamentos nas abas `ALUCOM`, `IP SERVICOS`, `MOREIA` e `AS SISTEMAS`.
4. Permitir filtro por cliente, ID ou tombo.
5. Editar `CONTRATO` e `ITEM_DO_CONTRATO` diretamente na tabela.
6. Preencher campos derivados como `CONTRACT_ID`, descricao, quantidade e evento a partir do dicionario mestre.
7. Usar o botao `Auto-Preencher` para sugerir contratos por similaridade e regras simples.
8. Salvar e travar lotes em `locks_parquet/`, removendo esses equipamentos da fila editavel.
9. Destravar lotes salvos para devolver os registros a edicao.

Equipamentos sem contrato ou sem item tambem podem ser salvos em Parquet. Nesses casos, o lote usa identificadores como `SEMID` e `SEM-CONTRATO` no nome do arquivo.

## Requisitos

- Python 3.11.
- Docker e Docker Compose, caso use a execucao em container.
- Acesso ao banco MySQL legado.
- Arquivos-base em `docs/Contratos.csv` ou `.xlsx` e `docs/itens_de_contratos.csv` ou `.xlsx`.
- Dependencias Python de `requirements.txt`.
- Uma engine Parquet disponivel para o Pandas, como `pyarrow` ou `fastparquet`, para salvar e ler os lotes travados.

## Configuracao

A conexao com os bancos e montada em [`core/database.py`](core/database.py) a partir de variaveis de ambiente carregadas do arquivo `.env` na raiz do projeto. Comece copiando o exemplo seguro:

```bash
cp .env.example .env
```

Configure as variaveis `DB_LEGADO_HOST`, `DB_LEGADO_PORT`, `DB_LEGADO_DATABASE`, `DB_LEGADO_USERNAME` e `DB_LEGADO_PASSWORD` para o banco legado, e `DB_NOVO_HOST`, `DB_NOVO_PORT`, `DB_NOVO_DATABASE`, `DB_NOVO_USERNAME` e `DB_NOVO_PASSWORD` para o banco novo. O arquivo `.env` e ignorado pelo Git; substitua todos os valores de exemplo e mantenha nele as credenciais reais.

Exemplo de configuracao do banco novo local quando o app roda diretamente no host:

```env
DB_NOVO_HOST=localhost
DB_NOVO_PORT=3307
DB_NOVO_DATABASE=controle-interno
DB_NOVO_USERNAME=root
DB_NOVO_PASSWORD=senha-configurada-localmente
```

O endereco depende de onde o app executa e de onde esta o MySQL. Para o MySQL `banco-novo` deste Compose, use `localhost:3307` ao executar o app no host, mas `banco-novo:3306` ao executar o app em container na rede do Compose. Portanto, ajuste `DB_NOVO_HOST` e `DB_NOVO_PORT` no `.env` conforme o contexto antes de iniciar o app. Se o banco estiver em outro servidor, informe um host/porta acessivel a partir do ambiente do app; nao presuma que o nome do servico Compose ou `host.docker.internal` seja valido para um servidor remoto. As credenciais nao precisam mudar entre contextos, a menos que o servidor exija.

```env
DB_NOVO_HOST=banco-novo
DB_NOVO_PORT=3306
DB_NOVO_DATABASE=controle-interno
DB_NOVO_USERNAME=root
DB_NOVO_PASSWORD=senha-configurada-localmente
```

O Compose injeta o `.env` no app sem substituir os valores `DB_NOVO_*`. Para o banco legado, use igualmente um host e porta acessiveis a partir do ambiente em que o app executa. Por seguranca, prefira um usuario MySQL com permissoes somente de leitura quando aplicavel.

## Banco novo local com Docker

O Compose sobe um MySQL 8.4 separado para o banco novo. Configure `DB_NOVO_DATABASE` e `DB_NOVO_PASSWORD` no `.env`; este ultimo define a senha root do servico MySQL. O app usa os cinco parametros `DB_NOVO_*` do mesmo arquivo. Para o app em container, o banco fica acessivel pela rede interna do Compose em `banco-novo:3306`; para o app executado no host, use `localhost:3307`. O Compose nao forca host, porta, usuario ou senha do app, assim as definicoes do `.env` nao sao sobrescritas.

Coloque o dump SQL em `docker/mysql/init/` antes de subir os containers. Arquivos `.sql`, `.sql.gz` e scripts executaveis nessa pasta sao processados pelo MySQL somente quando o volume do banco e criado pela primeira vez. O banco inicial e `controle-interno` (configuravel por `DB_NOVO_DATABASE` no `.env`). O dump deve criar/importar as tabelas nesse banco.

```bash
mkdir -p docker/mysql/init
cp /caminho/para/seu-dump.sql docker/mysql/init/01-dump.sql
docker compose up --build
```

Para conectar com um cliente MySQL no host, use `localhost:3307`, usuario definido por `DB_NOVO_USERNAME` (no servico local, normalmente `root`) e a senha `DB_NOVO_PASSWORD`. Para reinicializar e importar novamente o dump, pare os containers e remova **somente o volume do banco** com `docker compose down -v`; isso apaga os dados persistidos.

> Dumps sao ignorados pelo Git via `.gitignore`. Evite colocar dados sensiveis sob controle de versao.

## Relatorio Base a partir do banco local (servidor de testes)

Por padrao, o botao **Atualizar Relatorio Base** consulta o banco legado configurado em `DB_LEGADO_*`. Em um servidor de testes cujo MySQL legado esta incompleto, e possivel apontar apenas essa leitura para o banco legado da maquina de desenvolvimento, sem mexer em `DB_LEGADO_*`:

### 1. Na maquina de desenvolvimento

Crie um usuario MySQL somente leitura e publique o banco na rede local com o servico `db-relay`:

```sql
CREATE USER 'leitura_legado'@'%' IDENTIFIED BY 'senha-forte';
GRANT SELECT ON aluguel_legado.* TO 'leitura_legado'@'%';
FLUSH PRIVILEGES;
```

No `.env` da maquina de desenvolvimento, informe o IP local usado pelo servidor:

```env
RELAY_BIND=172.16.0.121
RELAY_PORTA=3308
```

```bash
docker compose --profile relatorio-local up -d db-relay
```

O relay encaminha `172.16.0.121:3308` para o container `controle-interno-db:3306` na rede `controle-interno`.

### 2. No servidor de testes

No `.env` do servidor, defina a fonte exclusiva do relatorio:

```env
DB_RELATORIO_HOST=172.16.0.121
DB_RELATORIO_PORT=3308
DB_RELATORIO_DATABASE=aluguel_legado
DB_RELATORIO_USERNAME=leitura_legado
DB_RELATORIO_PASSWORD=senha-forte
```

Recrie o container para aplicar o `.env` (`docker compose up -d --no-build app-automacao`). A barra lateral passa a exibir `Base do relatorio: 172.16.0.121:3308/aluguel_legado` e o botao **Testar conexao da base** valida o caminho antes de sincronizar. Se `DB_RELATORIO_HOST` nao estiver definido, nada muda: o botao usa `DB_LEGADO_*`.

> A ponte publica o MySQL na rede local. Use um usuario com `SELECT` apenas e restrinja a porta `3308` ao IP do servidor no firewall, por exemplo: `sudo iptables -I DOCKER-USER -p tcp --dport 3308 ! -s 172.16.0.200 -j DROP`.

## Execucao com Docker

```bash
docker compose up --build
```

O container executa o Streamlit na porta interna `8501`, publicada no host como:

```text
http://localhost:8503
```

Para acompanhar os logs:

```bash
docker compose logs -f app-automacao
```

Para parar:

```bash
docker compose down
```

O volume `.:/app` mantem os CSVs, o cache em `docs/relatorio_banco.csv` e os Parquets em `locks_parquet/` no diretorio local do projeto.

## Execucao local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Na execucao local, o Streamlit normalmente fica disponivel em:

```text
http://localhost:8501
```

Se precisar apontar para outro banco sem editar o `.env`, exporte as variaveis antes de iniciar:

```bash
DB_HOST=192.168.1.100 DB_PORT=3307 streamlit run app.py
```

## Como usar

1. Coloque os arquivos-base em `docs/`.
2. Inicie o app.
3. Clique em `Atualizar Relatorio Base` na barra lateral para consultar o banco e recriar `docs/relatorio_banco.csv`.
4. Abra a aba da organizacao desejada.
5. Use o filtro para localizar equipamentos por cliente, ID ou tombo.
6. Preencha ou revise o contrato e o item de contrato.
7. Use `Auto-Preencher` quando quiser aplicar as regras de sugestao.
8. Clique em `Salvar e Travar` para gravar o lote em Parquet.
9. Use a aba `Itens Travados` para destravar um lote e devolve-lo para edicao.

## Banco consultado

A sincronizacao le dados das tabelas:

- `aluguel_equipamentos`;
- `aluguel_movimento_itens`;
- `aluguel_movimento`;
- `aluguel_clientes`.

A consulta considera equipamentos com `situacao_id = 1`, usa o ultimo movimento por equipamento e filtra movimentos, itens de movimento e clientes nao excluidos logicamente. A separacao entre organizacoes usa `orgao_id` e os mapeamentos em [`utils/text_processing.py`](utils/text_processing.py).

Para alterar quais orgaos entram em cada aba, ajuste:

```python
MAPPING_ALUCOM = {...}
MAPPING_IP = {...}
MAPPING_MOREIA = {...}
MAPPING_AS = {...}
```

## Arquivos de entrada

Os arquivos podem ficar em `docs/` ou, por compatibilidade, na raiz do projeto. Quando houver `.xlsx` e `.csv` com o mesmo nome-base, o `.xlsx` tem prioridade.

### Contratos

Nomes aceitos:

1. `docs/Contratos.xlsx`
2. `docs/Contratos.csv`

Colunas principais:

| Coluna | Obrigatoria | Uso |
|---|---|---|
| `CONTRATOS` | Sim | Nome exibido no seletor de contratos |
| `CONTRACT_ID` | Sim | Identificador preenchido automaticamente |
| `CLIENTE` | Nao | Informacao auxiliar |
| `ORGANIZACAO` | Nao | Informacao auxiliar |
| `NUMERO_CONTRATO` | Nao | Informacao auxiliar |
| `NUMERO_MAIS_CONTRATO` | Nao | Informacao auxiliar |

Exemplo:

```csv
CONTRATOS,CLIENTE,ORGANIZACAO,NUMERO_CONTRATO,NUMERO_MAIS_CONTRATO,CONTRACT_ID
ALECE,ASSEMBLEIA LEGISLATIVA DO ESTADO DO CEARA,ALUCOM,97-2025,ALECE - 97-2025,3
```

### Itens de contrato

Nomes aceitos:

1. `docs/itens_de_contratos.xlsx`
2. `docs/itens_de_contratos.csv`

Colunas principais:

| Coluna | Obrigatoria | Uso |
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

Quando houver mais de um registro para o mesmo contrato e apelido, a aplicacao usa o maior `EVENTO`.

## Arquivos gerados

### Cache do relatorio do banco

Arquivo:

```text
docs/relatorio_banco.csv
```

Ele e recriado ao clicar em `Atualizar Relatorio Base` e usado como cache na inicializacao. Se nao existir, as abas de organizacao ficam vazias ate a primeira sincronizacao.

Colunas gravadas pelo fluxo atual:

```text
id_cliente,nome_cliente,id_equipamento,tombo,nome_equipamentos,orgao_id,deleted_at,aba_origem
```

### Lotes Parquet

Diretorio:

```text
locks_parquet/
```

Cada arquivo representa os equipamentos salvos de um cliente dentro de um grupo de contrato. O nome segue o padrao:

```text
<ORGANIZACAO>__C<CONTRACT_ID>-<CONTRATO>__CLI<CLIENTE_ID>-<CLIENTE>.parquet
```

Exemplo:

```text
ALUCOM__C197-GOVERNO-MUNICIPAL-DE-URUOCA__CLI868-PMURUOCASECEDU.parquet
```

Os trechos textuais sao convertidos para maiusculas, sem acentos, sem caracteres especiais e com espacos trocados por hifens.

Colunas armazenadas:

```text
CLIENTE_ID
CLIENTE_NOME
EQUIPAMENTO_ID
TOMBO
EQUIPAMENTO_NOME
ORGAO_ID
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

Enquanto um `EQUIPAMENTO_ID` estiver presente em um Parquet da organizacao, ele nao aparece na tabela editavel dessa mesma organizacao. Ao destravar, o app le o Parquet, remove `ORGAO` e `TRAVADO_EM`, devolve os dados ao estado da tela e exclui o arquivo.

## Estrutura do projeto

```text
.
|-- app.py                      # Entrada Streamlit e composicao das abas
|-- core/
|   `-- database.py             # Conexao, leitura dos CSV/XLSX e consulta SQL
|-- components/
|   |-- organization_tab.py     # Interface das abas de organizacao
|   `-- parquet_tab.py          # Interface de lotes travados
|-- services/
|   |-- dictionary_service.py   # Dicionario mestre, automacao e sincronizacao
|   |-- locking_service.py      # Salvamento, leitura e destravamento de Parquets
|   `-- rules_engine.py         # Regras do Auto-Preencher
|-- utils/
|   `-- text_processing.py      # Normalizacao, slugs e mapeamento de orgaos
|-- docs/                       # Arquivos-base e cache do relatorio
|-- locks_parquet/              # Lotes travados
|-- Dockerfile
|-- docker-compose.yml
`-- requirements.txt
```

## Persistencia e Git

O `.gitignore` ignora `.env`, `locks_parquet/`, arquivos `.parquet`, caches do banco e CSVs gerados. Os CSVs base com nomes `Contratos.csv`, `itens_de_contratos.csv` e `clientes_banco.csv` sao excecoes e podem ser versionados quando fizer sentido.

Mantenha backup externo dos Parquets se eles forem parte do processo operacional, porque a pasta de travas nao deve ser tratada como backup definitivo.

## Solucao de problemas

### O app abre, mas as abas estao vazias

Confirme se `docs/relatorio_banco.csv` existe ou clique em `Atualizar Relatorio Base` para sincronizar com o banco.

### Falha ao conectar no banco

Verifique se:

- o `.env` existe;
- as variaveis `DB_LEGADO_*` e `DB_NOVO_*` correspondentes estao definidas e corretas;
- o MySQL aceita conexoes na porta configurada;
- o host/porta do banco sao alcancaveis a partir do contexto do app (`banco-novo:3306` para o MySQL no Compose, `localhost:3307` a partir do host);
- o firewall permite a conexao.

### Arquivos-base nao aparecem

Confira se os nomes sao exatamente `Contratos` e `itens_de_contratos`, com extensao `.csv` ou `.xlsx`, dentro de `docs/` ou na raiz.

### Erro ao salvar ou ler Parquet

Confirme se:

- a pasta `locks_parquet/` existe;
- o processo tem permissao de escrita nessa pasta;
- ha uma engine Parquet instalada no mesmo ambiente, como `pyarrow` ou `fastparquet`.
