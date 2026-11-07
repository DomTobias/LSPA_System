-- ==========================================================================
-- Schema do LSPA-System (SQLite)
--
-- Escrito em SQL próximo do padrão para facilitar a migração para MySQL:
--   * INTEGER PRIMARY KEY AUTOINCREMENT  -> INT AUTO_INCREMENT PRIMARY KEY
--   * TEXT com datas ISO-8601             -> DATETIME
--   * ON CONFLICT ... DO UPDATE          -> ON DUPLICATE KEY UPDATE
-- ==========================================================================

PRAGMA foreign_keys = ON;

-- Registro de cada consulta feita ao SIDRA (também usado como controle de cache)
CREATE TABLE IF NOT EXISTS consultas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo          TEXT    NOT NULL,          -- valores | metadados | periodos | localidades
    tabela        INTEGER NOT NULL,          -- tabela SIDRA de origem (ex.: 6588)
    caminho       TEXT    NOT NULL UNIQUE,   -- caminho canônico da consulta (chave de cache)
    parametros    TEXT,                      -- parâmetros em JSON
    registros     INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'sucesso',  -- sucesso | erro
    mensagem      TEXT,
    execucoes     INTEGER NOT NULL DEFAULT 1,
    criada_em     TEXT    NOT NULL,
    executada_em  TEXT                       -- última execução com sucesso (validade do cache)
);

CREATE TABLE IF NOT EXISTS produtos (
    tabela        INTEGER NOT NULL,
    codigo        TEXT    NOT NULL,          -- categoria da classificação 48
    nome          TEXT    NOT NULL,
    nome_original TEXT,
    hierarquia    TEXT,
    nivel         INTEGER NOT NULL DEFAULT 1,
    agregado      INTEGER NOT NULL DEFAULT 0,
    pai_codigo    TEXT,
    ordem         INTEGER NOT NULL DEFAULT 0,
    atualizado_em TEXT    NOT NULL,
    PRIMARY KEY (tabela, codigo)
);

CREATE TABLE IF NOT EXISTS localidades (
    nivel         TEXT    NOT NULL,          -- N1 | N2 | N3
    codigo        TEXT    NOT NULL,
    nome          TEXT    NOT NULL,
    nivel_nome    TEXT,
    regiao_codigo TEXT,
    sigla         TEXT,
    atualizado_em TEXT    NOT NULL,
    PRIMARY KEY (nivel, codigo)
);

CREATE TABLE IF NOT EXISTS periodos (
    tabela        INTEGER NOT NULL,
    codigo        TEXT    NOT NULL,          -- AAAAMM
    ano           INTEGER NOT NULL,
    mes           INTEGER NOT NULL,
    nome          TEXT,
    modificacao   TEXT,                      -- data da última modificação no IBGE
    atualizado_em TEXT    NOT NULL,
    PRIMARY KEY (tabela, codigo)
);

CREATE TABLE IF NOT EXISTS indicadores (
    tabela        INTEGER NOT NULL,
    codigo        INTEGER NOT NULL,
    chave         TEXT    NOT NULL,
    nome          TEXT    NOT NULL,
    unidade       TEXT,
    somavel       INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT    NOT NULL,
    PRIMARY KEY (tabela, codigo)
);

-- Observações agrícolas. A restrição UNIQUE impede duplicidade; valores
-- revisados pelo IBGE são atualizados (upsert) e versionados.
CREATE TABLE IF NOT EXISTS producao (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tabela            INTEGER NOT NULL,
    periodo           TEXT    NOT NULL,      -- AAAAMM (mês de referência)
    ano               INTEGER NOT NULL,
    mes               INTEGER NOT NULL,
    nivel             TEXT    NOT NULL,
    localidade_codigo TEXT    NOT NULL,
    localidade_nome   TEXT,
    produto_codigo    TEXT    NOT NULL,
    produto_nome      TEXT,
    variavel_codigo   INTEGER NOT NULL,
    variavel_nome     TEXT,
    unidade           TEXT,
    valor             REAL,                  -- NULL quando o IBGE publica símbolo
    simbolo           TEXT,                  -- '-', '..', '...', 'X'
    consulta_id       INTEGER REFERENCES consultas(id) ON DELETE SET NULL,
    versao            INTEGER NOT NULL DEFAULT 1,
    criado_em         TEXT    NOT NULL,
    atualizado_em     TEXT    NOT NULL,
    UNIQUE (tabela, periodo, nivel, localidade_codigo, produto_codigo, variavel_codigo)
);

CREATE INDEX IF NOT EXISTS idx_producao_filtro
    ON producao (tabela, periodo, variavel_codigo, produto_codigo);
CREATE INDEX IF NOT EXISTS idx_producao_localidade
    ON producao (nivel, localidade_codigo);

-- Histórico de revisões das estimativas
CREATE TABLE IF NOT EXISTS producao_revisoes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    producao_id      INTEGER NOT NULL REFERENCES producao(id) ON DELETE CASCADE,
    valor_anterior   REAL,
    simbolo_anterior TEXT,
    valor_novo       REAL,
    simbolo_novo     TEXT,
    consulta_id      INTEGER,
    revisado_em      TEXT    NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_producao_revisao
AFTER UPDATE OF valor, simbolo ON producao
WHEN OLD.valor IS NOT NEW.valor OR OLD.simbolo IS NOT NEW.simbolo
BEGIN
    INSERT INTO producao_revisoes
        (producao_id, valor_anterior, simbolo_anterior, valor_novo, simbolo_novo, consulta_id, revisado_em)
    VALUES
        (OLD.id, OLD.valor, OLD.simbolo, NEW.valor, NEW.simbolo, NEW.consulta_id, NEW.atualizado_em);
END;
