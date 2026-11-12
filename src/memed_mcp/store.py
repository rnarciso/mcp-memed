"""Armazenamento local (SQLite) dos rascunhos e pedidos de exclusão.

Guarda dados de pacientes: o volume /data deve ficar em disco do próprio
servidor, com backup e acesso restrito (LGPD).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RascunhoIn

SCHEMA = """
CREATE TABLE IF NOT EXISTS rascunhos (
    id TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    dados TEXT NOT NULL,
    status TEXT NOT NULL,              -- rascunho | emitida | descartada
    memed_prescricao_id TEXT,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exclusoes (
    id TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    memed_prescricao_id TEXT NOT NULL,
    motivo TEXT,
    status TEXT NOT NULL,              -- pendente | confirmada | cancelada | erro
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    # -- rascunhos ---------------------------------------------------------
    def criar_rascunho(self, r: RascunhoIn) -> dict[str, Any]:
        rid, nonce, now = secrets.token_urlsafe(18), secrets.token_urlsafe(24), _now()
        with self._lock:
            self._db.execute(
                "INSERT INTO rascunhos VALUES (?,?,?,?,?,?,?)",
                (rid, nonce, r.model_dump_json(), "rascunho", None, now, now),
            )
            self._db.commit()
        return self.rascunho(rid)  # type: ignore[return-value]

    def rascunho(self, rid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM rascunhos WHERE id=?", (rid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["dados"] = json.loads(d["dados"])
        return d

    def listar_rascunhos(self, status: str | None = None, limite: int = 20) -> list[dict[str, Any]]:
        q, args = "SELECT id, status, memed_prescricao_id, criado_em, atualizado_em, dados FROM rascunhos", []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY criado_em DESC LIMIT ?"
        args.append(limite)
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            dados = json.loads(d.pop("dados"))
            d["paciente"] = dados["paciente"]["nome"]
            d["itens"] = len(dados["itens"])
            out.append(d)
        return out

    def marcar_rascunho(self, rid: str, status: str, memed_id: str | None = None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE rascunhos SET status=?, memed_prescricao_id=COALESCE(?, memed_prescricao_id), atualizado_em=? WHERE id=?",
                (status, memed_id, _now(), rid),
            )
            self._db.commit()

    # -- exclusões ---------------------------------------------------------
    def criar_exclusao(self, memed_id: str, motivo: str | None) -> dict[str, Any]:
        eid, nonce, now = secrets.token_urlsafe(18), secrets.token_urlsafe(24), _now()
        with self._lock:
            self._db.execute(
                "INSERT INTO exclusoes VALUES (?,?,?,?,?,?,?)", (eid, nonce, memed_id, motivo, "pendente", now, now)
            )
            self._db.commit()
        return self.exclusao(eid)  # type: ignore[return-value]

    def exclusao(self, eid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM exclusoes WHERE id=?", (eid,)).fetchone()
        return dict(row) if row else None

    def marcar_exclusao(self, eid: str, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE exclusoes SET status=?, atualizado_em=? WHERE id=?", (status, _now(), eid))
            self._db.commit()
