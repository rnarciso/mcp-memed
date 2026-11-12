"""Ponto de entrada.

    memed-mcp serve                  # sobe o servidor MCP (HTTP) e as páginas de revisão
    memed-mcp status                 # testa credenciais e status do prescritor
    memed-mcp registrar-prescritor   # cadastra o médico na Memed (usa MEMED_PRESCRIBER_*)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

from .config import ConfigError, Settings
from .memed_client import MemedClient, MemedError
from .server import build_app
from .store import Store


async def _status(s: Settings) -> int:
    c = MemedClient(s)
    try:
        a = await c.get_prescriber()
        print(f"[{s.env}] prescritor {a.get('nome', '')} {a.get('sobrenome', '')} | status: {a.get('status')}")
        return 0
    except MemedError as e:
        print(f"[{s.env}] erro: {e}", file=sys.stderr)
        return 1
    finally:
        await c.aclose()


async def _registrar(s: Settings) -> int:
    c = MemedClient(s)
    try:
        a = await c.register_prescriber(s.prescriber)
        print(f"[{s.env}] cadastrado. status: {a.get('status')}")
        return 0
    except MemedError as e:
        print(f"[{s.env}] erro: {e}", file=sys.stderr)
        return 1
    finally:
        await c.aclose()


def main() -> None:
    p = argparse.ArgumentParser(prog="memed-mcp")
    p.add_argument("comando", choices=["serve", "status", "registrar-prescritor"], nargs="?", default="serve")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx registra URLs com query string (que contém as chaves): silenciar.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        s = Settings.from_env()
    except ConfigError as e:
        sys.exit(f"Configuração inválida: {e}")

    if args.comando == "status":
        sys.exit(asyncio.run(_status(s)))
    if args.comando == "registrar-prescritor":
        sys.exit(asyncio.run(_registrar(s)))

    if s.is_production:
        logging.warning("AMBIENTE DE PRODUÇÃO: documentos emitidos terão validade legal.")
    app = build_app(s, MemedClient(s), Store(s.data_dir / "memed-mcp.sqlite3"))
    uvicorn.run(app, host=s.host, port=s.port, proxy_headers=True, access_log=False)


if __name__ == "__main__":
    main()
