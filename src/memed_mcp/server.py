"""Servidor MCP da Memed.

Princípio de segurança: o LLM só PREPARA. Emitir e excluir exigem ação do
médico numa página web servida por este mesmo processo, e a emissão só é
registrada depois de confirmada na API da Memed.
"""

from __future__ import annotations

import hmac
import json
import logging
from importlib import resources
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .config import Settings
from .memed_client import MemedClient, MemedError
from .models import Item, Paciente, RascunhoIn
from .store import Store

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
Conector da Memed para um médico prescritor. Regras obrigatórias:
1. Você NUNCA emite, assina ou exclui documentos. Você prepara rascunhos e devolve um link;
   o médico revisa e emite pessoalmente no módulo oficial da Memed.
2. Nunca diga que uma receita ou atestado foi emitido sem que `status_rascunho` retorne
   status 'emitida' com o ID da Memed.
3. Antes de preparar: confirme identidade do paciente, alergias, peso/função renal quando
   relevante, dose, via, frequência, duração e quantidade. Se faltar algo, pergunte.
4. Use apenas os dados que o médico forneceu; não invente CPF, datas ou diagnósticos.
5. CID em atestado só com autorização expressa do paciente (Resolução CFM 1.658/2002).
6. Use `nota_para_medico` para sinalizar dúvidas, interações e pendências.
"""


def _template(name: str, config: dict[str, Any]) -> HTMLResponse:
    html = resources.files("memed_mcp").joinpath("templates", name).read_text(encoding="utf-8")
    # JSON seguro dentro de <script>: escapa '<', '>' e '&' para impedir quebra da tag.
    blob = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return HTMLResponse(
        html.replace("__CONFIG_JSON__", blob),
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _nonce_ok(expected: str, got: Any) -> bool:
    return isinstance(got, str) and hmac.compare_digest(expected.encode(), got.encode())


def build_server(settings: Settings, client: MemedClient, store: Store) -> MCPServer:
    mcp = MCPServer(name="memed", instructions=INSTRUCTIONS, version="0.1.0")
    base = settings.public_base_url

    def link_rascunho(rid: str) -> str:
        return f"{base}/rascunhos/{rid}"

    def criar(r: RascunhoIn) -> dict[str, Any]:
        d = store.criar_rascunho(r)
        return {
            "rascunho_id": d["id"],
            "status": d["status"],
            "link_revisao": link_rascunho(d["id"]),
            "ambiente": settings.env,
            "aviso": "NADA FOI EMITIDO. Envie o link ao médico: ele revisa e emite no módulo da Memed. "
            "Depois consulte status_rascunho para confirmar.",
        }

    # ---------------------------------------------------------------- tools
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def status_prescritor() -> dict[str, Any]:
        """Verifica se o médico está cadastrado e ativo na Memed (não retorna o token)."""
        try:
            a = await client.get_prescriber()
        except MemedError as e:
            return {"ok": False, "erro": str(e), "ambiente": settings.env}
        return {
            "ok": True,
            "ambiente": settings.env,
            "nome": " ".join(x for x in (a.get("nome"), a.get("sobrenome")) if x),
            "status": a.get("status"),
            "conselho": a.get("board"),
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    async def preparar_receita(
        paciente: Paciente,
        itens: list[Item],
        alergias: list[str] | None = None,
        nota_para_medico: str | None = None,
    ) -> dict[str, Any]:
        """Prepara um RASCUNHO de receita (medicamentos e/ou textos livres) para o médico revisar e emitir.

        Não emite nada. Retorna um link de revisão que deve ser entregue ao médico.
        """
        try:
            r = RascunhoIn(paciente=paciente, itens=itens, alergias=alergias or [], nota_para_medico=nota_para_medico)
        except ValidationError as e:
            return {"ok": False, "erro": e.errors(include_url=False)}
        return {"ok": True, **criar(r)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    async def preparar_atestado(
        paciente: Paciente,
        texto: str,
        titulo: str = "Atestado médico",
        nota_para_medico: str | None = None,
    ) -> dict[str, Any]:
        """Prepara um RASCUNHO de atestado (ou declaração/relatório/encaminhamento) como texto livre.

        O texto deve estar completo, em português formal, sem CID salvo autorização expressa do paciente.
        Não emite nada. Retorna um link de revisão para o médico.
        """
        try:
            r = RascunhoIn(
                paciente=paciente,
                itens=[Item(tipo="texto_livre", nome=titulo, posologia=texto)],
                nota_para_medico=nota_para_medico,
            )
        except ValidationError as e:
            return {"ok": False, "erro": e.errors(include_url=False)}
        return {"ok": True, **criar(r)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def status_rascunho(rascunho_id: str) -> dict[str, Any]:
        """Consulta se um rascunho foi emitido pelo médico (status: rascunho | emitida | descartada)."""
        d = store.rascunho(rascunho_id)
        if not d:
            return {"ok": False, "erro": "Rascunho não encontrado"}
        return {
            "ok": True,
            "rascunho_id": d["id"],
            "status": d["status"],
            "memed_prescricao_id": d["memed_prescricao_id"],
            "paciente": d["dados"]["paciente"]["nome"],
            "link_revisao": link_rascunho(d["id"]),
            "atualizado_em": d["atualizado_em"],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def listar_rascunhos(status: str | None = None, limite: int = 20) -> dict[str, Any]:
        """Lista rascunhos recentes, opcionalmente filtrando por status (rascunho, emitida, descartada)."""
        return {"ok": True, "rascunhos": store.listar_rascunhos(status, max(1, min(limite, 100)))}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def listar_prescricoes_memed(limite: int = 20) -> dict[str, Any]:
        """Lista as prescrições já emitidas na Memed por este médico."""
        try:
            data = await client.list_prescriptions(max(1, min(limite, 100)))
        except MemedError as e:
            return {"ok": False, "erro": str(e)}
        return {"ok": True, "prescricoes": data}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def obter_pdf(memed_prescricao_id: str) -> dict[str, Any]:
        """Obtém o link do PDF de uma prescrição emitida na Memed."""
        try:
            return {"ok": True, "link_pdf": await client.get_pdf_url(memed_prescricao_id)}
        except MemedError as e:
            return {"ok": False, "erro": str(e)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    async def solicitar_exclusao(memed_prescricao_id: str, motivo: str | None = None) -> dict[str, Any]:
        """Cria um PEDIDO de exclusão de uma prescrição emitida. Não exclui nada:
        devolve um link onde o médico confirma a exclusão pessoalmente."""
        e = store.criar_exclusao(memed_prescricao_id, motivo)
        return {
            "ok": True,
            "link_confirmacao": f"{base}/exclusoes/{e['id']}",
            "aviso": "NADA FOI EXCLUÍDO. O médico precisa confirmar no link.",
        }

    @mcp.prompt(name="fluxo_prescricao", description="Regras e fluxo para preparar receitas/atestados na Memed")
    def fluxo_prescricao() -> str:
        """Mesmo conteúdo da skill, para clientes que usam prompts MCP em vez de skills."""
        txt = resources.files("memed_mcp").joinpath("templates", "skill.md").read_text(encoding="utf-8")
        return txt.split("---", 2)[-1].strip() if txt.startswith("---") else txt

    # -------------------------------------------------------- páginas web
    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    @mcp.custom_route("/rascunhos/{rid}", methods=["GET"], include_in_schema=False)
    async def pagina_rascunho(request: Request) -> HTMLResponse:
        d = store.rascunho(request.path_params["rid"])
        if not d:
            return HTMLResponse("Rascunho não encontrado", status_code=404)
        token = ""
        if d["status"] == "rascunho":
            try:
                token = await client.get_token()
            except MemedError as e:
                return HTMLResponse(f"Erro ao obter token da Memed: {e}", status_code=502)
        return _template(
            "revisao.html",
            {
                "id": d["id"],
                "nonce": d["nonce"],
                "status": d["status"],
                "rascunho": d["dados"],
                "ambiente": settings.env,
                "script_url": settings.script_url,
                "token": token,
                "base": f"/rascunhos/{d['id']}",
            },
        )

    async def _body(request: Request) -> dict[str, Any]:
        try:
            b = await request.json()
            return b if isinstance(b, dict) else {}
        except ValueError:
            return {}

    @mcp.custom_route("/rascunhos/{rid}/emitida", methods=["POST"], include_in_schema=False)
    async def rascunho_emitido(request: Request) -> JSONResponse:
        d = store.rascunho(request.path_params["rid"])
        body = await _body(request)
        if not d or not _nonce_ok(d["nonce"], body.get("nonce")):
            return JSONResponse({"erro": "não autorizado"}, status_code=403)
        pid = str(body.get("prescricao_id") or "").strip()
        if not pid or pid in ("undefined", "null"):
            return JSONResponse({"erro": "prescricao_id ausente"}, status_code=400)
        # Não confia no navegador: confirma na API da Memed que a prescrição existe.
        try:
            await client.get_prescription(pid)
        except MemedError as e:
            return JSONResponse({"erro": f"não confirmada na Memed: {e}"}, status_code=409)
        store.marcar_rascunho(d["id"], "emitida", pid)
        log.info("rascunho %s emitido como prescrição %s", d["id"], pid)
        return JSONResponse({"ok": True, "memed_prescricao_id": pid})

    @mcp.custom_route("/rascunhos/{rid}/descartar", methods=["POST"], include_in_schema=False)
    async def rascunho_descartado(request: Request) -> JSONResponse:
        d = store.rascunho(request.path_params["rid"])
        body = await _body(request)
        if not d or not _nonce_ok(d["nonce"], body.get("nonce")):
            return JSONResponse({"erro": "não autorizado"}, status_code=403)
        if d["status"] != "rascunho":
            return JSONResponse({"erro": f"status atual: {d['status']}"}, status_code=409)
        store.marcar_rascunho(d["id"], "descartada")
        return JSONResponse({"ok": True})

    @mcp.custom_route("/exclusoes/{eid}", methods=["GET"], include_in_schema=False)
    async def pagina_exclusao(request: Request) -> HTMLResponse:
        e = store.exclusao(request.path_params["eid"])
        if not e:
            return HTMLResponse("Pedido não encontrado", status_code=404)
        return _template(
            "exclusao.html",
            {
                "nonce": e["nonce"],
                "status": e["status"],
                "memed_prescricao_id": e["memed_prescricao_id"],
                "motivo": e["motivo"],
                "base": f"/exclusoes/{e['id']}",
            },
        )

    @mcp.custom_route("/exclusoes/{eid}/confirmar", methods=["POST"], include_in_schema=False)
    async def confirmar_exclusao(request: Request) -> JSONResponse:
        e = store.exclusao(request.path_params["eid"])
        body = await _body(request)
        if not e or not _nonce_ok(e["nonce"], body.get("nonce")):
            return JSONResponse({"erro": "não autorizado"}, status_code=403)
        if e["status"] != "pendente":
            return JSONResponse({"erro": f"status atual: {e['status']}"}, status_code=409)
        try:
            await client.delete_prescription(e["memed_prescricao_id"])
        except MemedError as err:
            store.marcar_exclusao(e["id"], "erro")
            return JSONResponse({"erro": str(err)}, status_code=502)
        store.marcar_exclusao(e["id"], "confirmada")
        return JSONResponse({"ok": True})

    return mcp


class BearerAuth:
    """Exige 'Authorization: Bearer <MCP_AUTH_TOKEN>' no endpoint /mcp.

    As páginas de revisão ficam fora: são abertas pelo médico no navegador e
    protegidas por IDs aleatórios + nonce. Mantenha o serviço na LAN/VPN.
    """

    def __init__(self, app, token: str, protected_prefix: str = "/mcp"):
        self.app, self.token, self.prefix = app, token.encode(), protected_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.prefix):
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"")
            if not (auth.startswith(b"Bearer ") and hmac.compare_digest(auth[7:], self.token)):
                resp = JSONResponse({"erro": "não autorizado"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(settings: Settings, client: MemedClient, store: Store):
    mcp = build_server(settings, client, store)
    security = None
    if settings.allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=[settings.public_base_url],
        )
    app = mcp.streamable_http_app(transport_security=security, host=settings.host)
    return BearerAuth(app, settings.mcp_auth_token)
