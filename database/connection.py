"""Gerenciamento de conexões com o banco de dados.

A aplicação usa SQLite inicialmente. Todo acesso passa por :class:`Database`,
de modo que trocar para MySQL exige apenas uma nova implementação desta
classe (mesma interface ``conexao()``) e o ajuste do dialeto no repositório.

Uso pela linha de comando (cria o arquivo e as tabelas)::

    python -m database.connection
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """Fábrica de conexões SQLite com transação por bloco ``with``."""

    def __init__(self, caminho: str):
        self.caminho = str(caminho)
        self._memoria = self.caminho == ":memory:"
        self._lock = threading.RLock()
        self._conexao_compartilhada: sqlite3.Connection | None = None
        if not self._memoria:
            Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)

    def _abrir(self) -> sqlite3.Connection:
        conexao = sqlite3.connect(
            self.caminho,
            timeout=15,
            check_same_thread=not self._memoria,
            detect_types=0,
        )
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
        if not self._memoria:
            conexao.execute("PRAGMA journal_mode = WAL")
            conexao.execute("PRAGMA synchronous = NORMAL")
        return conexao

    @contextmanager
    def conexao(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão, confirma a transação ao final ou desfaz em erro."""
        if self._memoria:
            # Banco em memória: uma única conexão protegida por lock.
            with self._lock:
                if self._conexao_compartilhada is None:
                    self._conexao_compartilhada = self._abrir()
                conexao = self._conexao_compartilhada
                try:
                    yield conexao
                    conexao.commit()
                except Exception:
                    conexao.rollback()
                    raise
            return

        conexao = self._abrir()
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def inicializar(self) -> None:
        """Cria as tabelas (idempotente)."""
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.conexao() as conexao:
            conexao.executescript(script)
        logger.info("Banco de dados inicializado em %s", self.caminho)

    def fechar(self) -> None:
        if self._conexao_compartilhada is not None:
            self._conexao_compartilhada.close()
            self._conexao_compartilhada = None


def main() -> None:
    """Inicializa o banco configurado no .env."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.config.settings import obter_configuracao

    configuracao = obter_configuracao()
    banco = Database(configuracao.DATABASE_PATH)
    banco.inicializar()
    print(f"Banco de dados pronto: {banco.caminho}")


if __name__ == "__main__":
    main()
