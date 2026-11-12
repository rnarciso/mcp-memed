import json
import re

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from memed_mcp.config import Settings
from memed_mcp.memed_client import MemedClient
from memed_mcp.models import cpf_valido
from memed_mcp.server import build_app, build_server
from memed_mcp.store import Store

API = "https://memed.test/v1"
TOKEN = "x" * 40
PACIENTE = {"nome": "Maria da Silva", "cpf": "529.982.247-25", "data_nascimento": "01/02/1960"}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        env="homolog",
        api_key="AK",
        secret_key="SK",
        api_base_url=API,
        script_url="https://memed.test/sinapse.js",
        prescriber_external_id="dr-1",
        public_base_url="http://dev-docker.lan:8765",
        mcp_auth_token=TOKEN,
        data_dir=tmp_path,
    )


@pytest.fixture
def memed():
    with respx.mock(base_url=API, assert_all_called=False) as m:
        m.get("/sinapse-prescricao/usuarios/dr-1").respond(
            json={"data": {"attributes": {"nome": "Roberto", "sobrenome": "N", "status": "Ativo", "token": "TOK"}}}
        )
        yield m


@pytest.fixture
def parts(settings, memed):
    client = MemedClient(settings)
    store = Store(settings.data_dir / "db.sqlite3")
    return settings, client, store


async def call(mcp, name, args):
    res = await mcp.call_tool(name, args)
    return res.structured_content or json.loads(res.content[0].text)


def test_cpf():
    assert cpf_valido("52998224725")
    assert not cpf_valido("52998224724")
    assert not cpf_valido("11111111111")


@pytest.mark.anyio
async def test_status_prescritor_nao_vaza_token(parts):
    mcp = build_server(*parts)
    out = await call(mcp, "status_prescritor", {})
    assert out["ok"] and out["status"] == "Ativo"
    assert "TOK" not in json.dumps(out)


@pytest.mark.anyio
async def test_preparar_receita_cria_rascunho_sem_emitir(parts):
    settings, client, store = parts
    mcp = build_server(*parts)
    out = await call(
        mcp,
        "preparar_receita",
        {"paciente": PACIENTE, "itens": [{"nome": "Losartana 50 mg", "posologia": "1 cp VO 12/12h", "quantidade": "60 cp"}], "alergias": ["dipirona"]},
    )
    assert out["ok"] and out["status"] == "rascunho"
    assert out["link_revisao"].startswith("http://dev-docker.lan:8765/rascunhos/")
    assert "NADA FOI EMITIDO" in out["aviso"]
    d = store.rascunho(out["rascunho_id"])
    assert d["dados"]["paciente"]["cpf"] == "52998224725"


@pytest.mark.anyio
async def test_cpf_invalido_rejeitado(parts):
    mcp = build_server(*parts)
    with pytest.raises(Exception, match="CPF"):
        await call(mcp, "preparar_atestado", {"paciente": {"nome": "Fulano", "cpf": "123"}, "texto": "Atesto..."})


@pytest.mark.anyio
async def test_preparar_atestado_vira_texto_livre(parts):
    _, _, store = parts
    mcp = build_server(*parts)
    out = await call(mcp, "preparar_atestado", {"paciente": PACIENTE, "texto": "Atesto para os devidos fins que..."})
    d = store.rascunho(out["rascunho_id"])
    assert d["dados"]["itens"][0]["tipo"] == "texto_livre"


@pytest.mark.anyio
async def test_solicitar_exclusao_nao_exclui(parts, memed):
    delete = memed.delete("/prescricoes/99").respond(204)
    mcp = build_server(*parts)
    out = await call(mcp, "solicitar_exclusao", {"memed_prescricao_id": "99"})
    assert out["ok"] and "/exclusoes/" in out["link_confirmacao"]
    assert not delete.called


def _http(parts):
    return TestClient(build_app(*parts))


def test_mcp_exige_bearer(parts):
    with _http(parts) as c:
        assert c.post("/mcp", json={}).status_code == 401
        assert c.post("/mcp", json={}, headers={"Authorization": "Bearer errado"}).status_code == 401
        r = c.post(
            "/mcp",
            headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        )
        assert r.status_code == 200
        assert c.get("/healthz").text == "ok"


def _novo_rascunho(store):
    from memed_mcp.models import RascunhoIn

    return store.criar_rascunho(
        RascunhoIn.model_validate({"paciente": {**PACIENTE, "nome": "</script><script>alert(1)</script>"}, "itens": [{"nome": "AAS", "posologia": "1 cp"}]})
    )


def test_pagina_revisao_escapa_html_e_injeta_token(parts):
    _, _, store = parts
    d = _novo_rascunho(store)
    with _http(parts) as c:
        r = c.get(f"/rascunhos/{d['id']}")
    assert r.status_code == 200
    assert "</script><script>alert" not in r.text
    assert '"token": "TOK"' in r.text
    assert r.headers["x-frame-options"] == "DENY"


def test_emissao_exige_nonce_e_confirmacao_na_memed(parts, memed):
    _, _, store = parts
    d = _novo_rascunho(store)
    memed.get("/prescricoes/123").respond(json={"data": {"id": "123"}})
    memed.get("/prescricoes/666").respond(404, json={"errors": [{"detail": "not found"}]})
    with _http(parts) as c:
        url = f"/rascunhos/{d['id']}/emitida"
        assert c.post(url, json={"nonce": "errado", "prescricao_id": "123"}).status_code == 403
        assert store.rascunho(d["id"])["status"] == "rascunho"
        assert c.post(url, json={"nonce": d["nonce"], "prescricao_id": "666"}).status_code == 409
        assert store.rascunho(d["id"])["status"] == "rascunho"
        assert c.post(url, json={"nonce": d["nonce"], "prescricao_id": "123"}).status_code == 200
    d2 = store.rascunho(d["id"])
    assert d2["status"] == "emitida" and d2["memed_prescricao_id"] == "123"


def test_exclusao_so_com_confirmacao(parts, memed):
    _, _, store = parts
    delete = memed.delete("/prescricoes/77").respond(204)
    e = store.criar_exclusao("77", "erro de dose")
    with _http(parts) as c:
        assert c.post(f"/exclusoes/{e['id']}/confirmar", json={"nonce": "x"}).status_code == 403
        assert not delete.called
        assert c.post(f"/exclusoes/{e['id']}/confirmar", json={"nonce": e["nonce"]}).status_code == 200
        assert delete.called
        assert c.post(f"/exclusoes/{e['id']}/confirmar", json={"nonce": e["nonce"]}).status_code == 409


@pytest.mark.anyio
async def test_erro_da_memed_nao_vaza_chaves(parts, memed):
    settings, client, _ = parts
    memed.get("/prescricoes").respond(500, json={"errors": [{"detail": "boom"}]})
    mcp = build_server(*parts)
    out = await call(mcp, "listar_prescricoes_memed", {})
    assert not out["ok"]
    assert "SK" not in out["erro"] and "TOK" not in out["erro"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_prompt_fluxo(parts):
    mcp = build_server(*parts)
    res = await mcp.get_prompt("fluxo_prescricao", {})
    assert "Você nunca emite" in json.dumps(res.model_dump(), ensure_ascii=False)


def test_skill_empacotada_igual_a_publicada():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "skills/memed-prescricao/SKILL.md").read_text() == (root / "src/memed_mcp/templates/skill.md").read_text(), (
        "Copie skills/memed-prescricao/SKILL.md para src/memed_mcp/templates/skill.md"
    )
