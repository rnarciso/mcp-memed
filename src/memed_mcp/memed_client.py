"""Cliente HTTP da API REST da Memed (Sinapse Prescrição).

A API REST da Memed NÃO emite prescrições: a emissão acontece no módulo
frontend, com ação do médico. Este cliente cobre apenas o que o backend
permite: prescritor/token, consulta, PDF e exclusão.

Os caminhos abaixo seguem a documentação pública da Memed, mas devem ser
conferidos em https://doc.memed.com.br durante a homologação. Estão
centralizados em PATHS para facilitar o ajuste.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Prescriber, Settings

log = logging.getLogger(__name__)

PATHS = {
    "prescritor": "/sinapse-prescricao/usuarios/{external_id}",
    "prescritores": "/sinapse-prescricao/usuarios",
    "prescricoes": "/prescricoes",
    "prescricao": "/prescricoes/{id}",
    "pdf": "/prescricoes/{id}/url-document/full",
}

JSONAPI = "application/vnd.api+json"


class MemedError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _safe_error(resp: httpx.Response) -> MemedError:
    """Monta erro sem vazar query string (que contém as chaves)."""
    detail = ""
    try:
        body = resp.json()
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            detail = "; ".join(str(e.get("detail") or e.get("title") or e) for e in errors)
    except ValueError:
        pass
    return MemedError(f"Memed respondeu HTTP {resp.status_code} em {resp.request.url.path}. {detail}".strip(), resp.status_code)


class MemedClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self._http = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=20.0,
            headers={"Accept": JSONAPI, "Content-Type": JSONAPI},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- utilitários -------------------------------------------------------
    @property
    def _keys(self) -> dict[str, str]:
        return {"api-key": self.s.api_key, "secret-key": self.s.secret_key}

    async def _request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        try:
            resp = await self._http.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise MemedError(f"Falha de rede ao falar com a Memed: {type(exc).__name__}") from None
        if resp.status_code >= 400:
            raise _safe_error(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # -- prescritor --------------------------------------------------------
    async def get_prescriber(self, external_id: str | None = None) -> dict[str, Any]:
        ext = external_id or self.s.prescriber_external_id
        body = await self._request("GET", PATHS["prescritor"].format(external_id=ext), params=self._keys)
        return (body.get("data") or {}).get("attributes") or {}

    async def get_token(self) -> str:
        attrs = await self.get_prescriber()
        token = attrs.get("token")
        if not token:
            raise MemedError("A Memed não devolveu token para o prescritor. Ele está cadastrado e ativo?")
        return token

    async def register_prescriber(self, p: Prescriber) -> dict[str, Any]:
        missing = [k for k in ("nome", "sobrenome", "cpf", "data_nascimento", "crm", "uf") if not getattr(p, k)]
        if missing:
            raise MemedError("Dados do prescritor incompletos: " + ", ".join(f"MEMED_PRESCRIBER_{m.upper()}" for m in missing))
        payload = {
            "data": {
                "type": "usuarios",
                "attributes": {
                    "external_id": self.s.prescriber_external_id,
                    "nome": p.nome,
                    "sobrenome": p.sobrenome,
                    "cpf": p.cpf,
                    "data_nascimento": p.data_nascimento,
                    "email": p.email or None,
                    "telefone": p.telefone or None,
                    "sexo": p.sexo or None,
                    "cidade": p.cidade or None,
                    "especialidade": p.especialidade or None,
                    "board": {"board_code": "CRM", "board_number": p.crm, "board_state": p.uf},
                },
            }
        }
        payload["data"]["attributes"] = {k: v for k, v in payload["data"]["attributes"].items() if v is not None}
        body = await self._request("POST", PATHS["prescritores"], params=self._keys, json=payload)
        return (body.get("data") or {}).get("attributes") or {}

    # -- prescrições ------------------------------------------------------
    async def list_prescriptions(self, limit: int = 20) -> list[dict[str, Any]]:
        token = await self.get_token()
        body = await self._request("GET", PATHS["prescricoes"], params={"token": token, "limit": limit})
        return body.get("data") or []

    async def get_prescription(self, prescription_id: str) -> dict[str, Any]:
        token = await self.get_token()
        body = await self._request("GET", PATHS["prescricao"].format(id=prescription_id), params={"token": token})
        return body.get("data") or {}

    async def get_pdf_url(self, prescription_id: str) -> str:
        token = await self.get_token()
        body = await self._request("GET", PATHS["pdf"].format(id=prescription_id), params={"token": token})
        data = body.get("data")
        if isinstance(data, list) and data:
            data = data[0]
        url = ((data or {}).get("attributes") or {}).get("link") if isinstance(data, dict) else None
        if not url:
            raise MemedError("A Memed não devolveu link de PDF para esta prescrição.")
        return url

    async def delete_prescription(self, prescription_id: str) -> None:
        token = await self.get_token()
        await self._request("DELETE", PATHS["prescricao"].format(id=prescription_id), params={"token": token})
