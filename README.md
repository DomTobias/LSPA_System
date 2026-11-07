# LSPA-System — Análise da Produção Agrícola (IBGE)

Sistema web para consultar, processar e visualizar os dados do **LSPA — Levantamento
Sistemático da Produção Agrícola**, publicados pelo IBGE no
[SIDRA](https://sidra.ibge.gov.br/pesquisa/lspa/tabelas) e obtidos em tempo real pela
[API SIDRA](https://apisidra.ibge.gov.br/).

Desenvolvido em Python/Flask com arquitetura MVC, SQLite, Bootstrap 5 e Chart.js.

---

## Funcionalidades

- **Dashboard** (`/` e `/dashboard`): cards de produção, área plantada, área colhida e
  rendimento médio (com variação anual e mensal); evolução por período (anual ou
  mensal); comparação entre períodos por grande região; produção por estado; ranking
  dos estados produtores; comparação entre produtos agrícolas.
- **Consulta de produção** (`/producao`): filtros por produto, indicador, região,
  estado, ano e mês; tabela com ordenação, pesquisa, paginação e exportação CSV.
- **API interna** em JSON (`/api/...`).
- **Cache persistente** em SQLite, com reconsulta periódica para capturar as
  **revisões** que o IBGE faz nas estimativas (histórico guardado em `producao_revisoes`).
- Se o IBGE estiver fora do ar, o sistema mostra os últimos dados locais com um aviso
  ou, sem dados locais, uma mensagem de indisponibilidade.

## Dados utilizados (códigos oficiais do SIDRA)

Verificados nos metadados e em requisições reais à API:

| Item | Código | Descrição |
|---|---|---|
| Pesquisa | `LA` | Levantamento Sistemático da Produção Agrícola |
| Tabela | **6588** | Série histórica da estimativa anual da área plantada, área colhida, produção e rendimento médio dos produtos das lavouras (mensal, desde 09/2006) |
| Variável | 109 | Área plantada (hectares) |
| Variável | 216 | Área colhida (hectares) |
| Variável | 35 | Produção (toneladas) |
| Variável | 36 | Rendimento médio (kg/ha) |
| Classificação | 48 | Produto das lavouras (categorias lidas dinamicamente dos metadados) |
| Níveis territoriais | N1 / N2 / N3 | Brasil / Grande Região / Unidade da Federação |

Cada período `AAAAMM` da tabela 6588 é a **estimativa da safra do ano AAAA feita no
mês MM**. A estimativa de dezembro é a última do ano. Os símbolos publicados pelo IBGE
são preservados: `-` (zero absoluto; também usado para indicadores não calculados em
agregados), `..` (não se aplica), `...` (não disponível) e `X` (sigilo).

Produtos, localidades e períodos **não são fixos no código**: vêm dos metadados do SIDRA.
O produto inicial do dashboard é a primeira categoria agregada de nível 1 da classificação
(no LSPA, *Cereais, leguminosas e oleaginosas*, o principal indicador divulgado pelo IBGE).
Para mudar esse padrão, defina `DASHBOARD_PRODUTO_PADRAO` no `.env`.

---

## 1. Pré-requisitos

- Windows 10/11
- Python 3.10 ou superior (testado com Python 3.13), com a opção *Add Python to PATH*
- Acesso à internet (para a API do IBGE e para carregar Bootstrap/Chart.js via CDN)

## 2. Criação do ambiente virtual

No PowerShell ou no Prompt de Comando, dentro da pasta do projeto:

```bat
python -m venv venv
venv\Scripts\activate
```

> Se o PowerShell bloquear a ativação, execute uma vez:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 3. Instalação das dependências

```bat
pip install -r requirements.txt
```

## 4. Configuração do ambiente

Copie o arquivo de exemplo e ajuste os valores:

```bat
copy .env.example .env
```

Gere uma chave secreta e coloque-a em `SECRET_KEY`:

```bat
python -c "import secrets; print(secrets.token_hex(32))"
```

Principais variáveis:

| Variável | Padrão | Descrição |
|---|---|---|
| `APP_ENV` | `development` | `development`, `production` ou `testing` |
| `SECRET_KEY` | — | Obrigatória em produção |
| `DATABASE_PATH` | `database/lspa.db` | Arquivo SQLite |
| `SIDRA_TIMEOUT` | `30` | Timeout das requisições ao IBGE (segundos) |
| `SIDRA_TENTATIVAS` | `2` | Novas tentativas em falhas transitórias (429/5xx) |
| `CACHE_TTL_HORAS` | `6` | Validade do cache de valores |
| `METADADOS_TTL_HORAS` | `24` | Validade do cache de produtos/localidades/períodos |
| `LOG_LEVEL` / `LOG_FILE` | `INFO` / `logs/lspa.log` | Logs da aplicação |

## 5. Inicialização do banco

O banco e as tabelas são criados automaticamente quando a aplicação inicia. Para criá-los
manualmente:

```bat
python -m database.connection
```

## 6. Execução do sistema

```bat
python run.py
```

Acesse **http://127.0.0.1:5000**.

A primeira abertura de cada tela consulta o IBGE (cerca de 1 segundo). As seguintes usam o
cache local até `CACHE_TTL_HORAS` vencer.

## 7. Execução dos testes

```bat
pytest
```

Os testes usam um cliente SIDRA simulado, que reproduz o **formato** das respostas reais
com valores sintéticos, então não dependem da disponibilidade da API. Para rodar também o
teste de integração contra a API real do IBGE:

```bat
set SIDRA_TESTE_REAL=1
pytest
```

---

## Arquitetura (MVC)

```
app/
├── config/          Configurações por ambiente (python-dotenv)
├── models/          Entidades: Producao, Indicador, Produto, Localidade, Periodo
├── views/           Templates Jinja2 + CSS/JS (Bootstrap 5, Chart.js)
├── controllers/     Recebem a requisição e escolhem a resposta (HTML/JSON/CSV)
├── routes/          Blueprints que mapeiam URLs → controllers
├── services/        Regras de negócio: validação, cache, indicadores, paginação, CSV
├── integrations/ibge/
│   ├── sidra_client.py     Requisições HTTP (sessão, timeout, retentativas, logs)
│   ├── sidra_endpoints.py  Códigos oficiais e montagem validada das consultas
│   └── sidra_parser.py     Interpretação e normalização do JSON
├── repositories/    Persistência SQLite (SQL parametrizado)
└── exceptions.py    Exceções de domínio → códigos HTTP
database/            Conexão e schema.sql
tests/               Pytest (cliente, parser, services, repositório, controllers)
```

Fluxo de uma consulta: `route → controller → service → (cache no repository | sidra_client → sidra_parser → repository) → controller → view/JSON`.

### API interna

| Rota | Descrição | Parâmetros |
|---|---|---|
| `GET /api/producao` | Consulta paginada | `produto`, `indicador` (`producao`, `area_plantada`, `area_colhida`, `rendimento_medio`), `regiao`, `estado`, `ano`, `mes` (1–12 ou `todos`), `busca`, `ordenar`, `direcao`, `pagina`, `por_pagina`, `formato=csv` |
| `GET /api/produtos` | Produtos agrícolas | `agregados=0` para só os produtos individuais |
| `GET /api/localidades` | Brasil, regiões e UFs | `nivel` (N1/N2/N3), `regiao` |
| `GET /api/periodos` | Meses de referência | `ano` |
| `GET /api/indicadores` | Variáveis do LSPA | — |
| `GET /api/dashboard` | Dados do dashboard | `produto`, `ano`, `mes` |
| `GET /api/status` | Estatísticas do cache local | — |

Erros retornam JSON `{"erro", "mensagem", "status"}` com o código HTTP adequado:
400 para parâmetro inválido, 404, 405, 502 para resposta inválida do IBGE e 503 para IBGE
indisponível.

### Segurança

- Consultas SQL sempre parametrizadas.
- Filtros validados contra os metadados oficiais; códigos aceitos apenas como dígitos.
- As URLs do IBGE são fixas: somente `apisidra.ibge.gov.br` e `servicodados.ibge.gov.br`
  sobre HTTPS. O usuário nunca informa URLs.
- Limite de tamanho por consulta, para evitar requisições enormes à API.
- Cabeçalhos de segurança (CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`).
- Segredos no `.env`, que fica fora do Git.

### Migração futura para MySQL

O acesso ao banco passa por `database.connection.Database`. Para usar MySQL, crie uma
implementação com a mesma interface `conexao()` e adapte o dialeto do repositório
(placeholders `%s`, `ON DUPLICATE KEY UPDATE` no lugar de `ON CONFLICT`). O `schema.sql`
indica as equivalências de tipos.
