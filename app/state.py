"""Estado persistente entre execuções — SQLite.

Guarda quais fotos do pool foram usadas, para o sorteio excluir as últimas N
gerações (critério do card). SQLite resolve sem infra extra e sobrevive a restart
desde que STATE_DB aponte para um volume persistente no deploy.
"""
import sqlite3
from contextlib import contextmanager

from . import config


@contextmanager
def _conn():
    con = sqlite3.connect(config.STATE_DB)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS fotos_usadas (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   file_id TEXT NOT NULL,
                   used_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        yield con
        con.commit()
    finally:
        con.close()


def fotos_recentes(n: int) -> set[str]:
    """IDs das fotos usadas nas últimas N gerações."""
    if n <= 0:
        return set()
    with _conn() as con:
        rows = con.execute(
            "SELECT file_id FROM fotos_usadas ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return {r[0] for r in rows}


def registrar_foto(file_id: str) -> None:
    with _conn() as con:
        con.execute("INSERT INTO fotos_usadas (file_id) VALUES (?)", (file_id,))
        # mantém a tabela pequena: só as 500 últimas importam
        con.execute(
            "DELETE FROM fotos_usadas WHERE id NOT IN "
            "(SELECT id FROM fotos_usadas ORDER BY id DESC LIMIT 500)"
        )
