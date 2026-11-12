"""Configuração lida exclusivamente de variáveis de ambiente.

Nenhuma credencial é gravada em disco pelo servidor. Os tokens do prescritor
são obtidos da Memed a cada uso e mantidos apenas em memória.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# URLs padrão por ambiente. ATENÇÃO: conferir na documentação da Memed
# (https://doc.memed.com.br) antes de usar em produção; podem ser
# sobrescritas por MEMED_API_BASE_URL e MEMED_SCRIPT_URL.
DEFAULTS = {
    "homolog": {
        "api": "https://sandbox.api.memed.com.br/v1",
        "script": "https://sandbox.memed.com.br/modulos/plataforma.sinapse-prescricao/build/sinapse-prescricao.min.js",
    },
    "prod": {
        "api": "https://api.memed.com.br/v1",
        "script": "https://memed.com.br/modulos/plataforma.sinapse-prescricao/build/sinapse-prescricao.min.js",
    },
}


class ConfigError(RuntimeError):
    pass


def _req(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def _csv(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Prescriber:
    """Dados usados apenas pelo comando de cadastro do prescritor."""

    nome: str = ""
    sobrenome: str = ""
    cpf: str = ""
    data_nascimento: str = ""  # dd/mm/aaaa
    crm: str = ""
    uf: str = ""
    email: str = ""
    telefone: str = ""
    sexo: str = ""  # M/F
    cidade: str = ""
    especialidade: str = ""


@dataclass(frozen=True)
class Settings:
    env: str
    api_key: str
    secret_key: str
    api_base_url: str
    script_url: str
    prescriber_external_id: str
    public_base_url: str
    mcp_auth_token: str
    host: str = "0.0.0.0"
    port: int = 8765
    data_dir: Path = Path("/data")
    allowed_hosts: list[str] = field(default_factory=list)
    prescriber: Prescriber = field(default_factory=Prescriber)

    @property
    def is_production(self) -> bool:
        return self.env == "prod"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get("MEMED_ENV", "homolog").strip().lower()
        if env not in DEFAULTS:
            raise ConfigError("MEMED_ENV deve ser 'homolog' ou 'prod'")
        token = _req("MCP_AUTH_TOKEN")
        if len(token) < 32:
            raise ConfigError("MCP_AUTH_TOKEN deve ter ao menos 32 caracteres (use: openssl rand -hex 32)")
        public = _req("PUBLIC_BASE_URL").rstrip("/")
        return cls(
            env=env,
            api_key=_req("MEMED_API_KEY"),
            secret_key=_req("MEMED_SECRET_KEY"),
            api_base_url=os.environ.get("MEMED_API_BASE_URL", DEFAULTS[env]["api"]).rstrip("/"),
            script_url=os.environ.get("MEMED_SCRIPT_URL", DEFAULTS[env]["script"]),
            prescriber_external_id=_req("MEMED_PRESCRIBER_EXTERNAL_ID"),
            public_base_url=public,
            mcp_auth_token=token,
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8765")),
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
            allowed_hosts=_csv("ALLOWED_HOSTS"),
            prescriber=Prescriber(
                nome=os.environ.get("MEMED_PRESCRIBER_NOME", ""),
                sobrenome=os.environ.get("MEMED_PRESCRIBER_SOBRENOME", ""),
                cpf=os.environ.get("MEMED_PRESCRIBER_CPF", ""),
                data_nascimento=os.environ.get("MEMED_PRESCRIBER_DATA_NASCIMENTO", ""),
                crm=os.environ.get("MEMED_PRESCRIBER_CRM", ""),
                uf=os.environ.get("MEMED_PRESCRIBER_UF", ""),
                email=os.environ.get("MEMED_PRESCRIBER_EMAIL", ""),
                telefone=os.environ.get("MEMED_PRESCRIBER_TELEFONE", ""),
                sexo=os.environ.get("MEMED_PRESCRIBER_SEXO", ""),
                cidade=os.environ.get("MEMED_PRESCRIBER_CIDADE", ""),
                especialidade=os.environ.get("MEMED_PRESCRIBER_ESPECIALIDADE", ""),
            ),
        )
