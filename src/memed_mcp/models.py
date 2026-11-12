"""Modelos dos dados que o LLM envia. Validação rígida: nada vai à Memed sem passar aqui."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _digits(v: str | None) -> str | None:
    return re.sub(r"\D", "", v) if v else v


def cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        dv = (soma * 10) % 11 % 10
        if dv != int(cpf[n]):
            return False
    return True


class Paciente(BaseModel):
    nome: str = Field(min_length=3, max_length=200, description="Nome completo do paciente")
    cpf: str | None = Field(None, description="CPF (só dígitos ou formatado). Omitir se o paciente não tiver CPF.")
    data_nascimento: str | None = Field(None, pattern=r"^\d{2}/\d{2}/\d{4}$", description="dd/mm/aaaa")
    telefone: str | None = None
    endereco: str | None = None
    cidade: str | None = None
    nome_social: str | None = None
    nome_mae: str | None = None
    peso_kg: float | None = Field(None, gt=0, lt=500)
    altura_m: float | None = Field(None, gt=0.2, lt=2.8)
    id_externo: str | None = Field(None, max_length=100, description="Identificador do paciente no seu sistema/prontuário")

    @field_validator("cpf", "telefone")
    @classmethod
    def _so_digitos(cls, v: str | None) -> str | None:
        return _digits(v)

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, v: str | None) -> str | None:
        if v and not cpf_valido(v):
            raise ValueError("CPF inválido (dígitos verificadores não conferem)")
        return v


class Item(BaseModel):
    tipo: Literal["medicamento", "texto_livre"] = Field(
        "medicamento",
        description="'medicamento' para um fármaco; 'texto_livre' para orientações, atestado, solicitação etc.",
    )
    nome: str = Field(min_length=2, max_length=300, description="Ex.: 'Losartana potássica 50 mg, comprimido' ou título do texto livre")
    posologia: str = Field(min_length=2, max_length=4000, description="Posologia completa ou o texto livre")
    quantidade: str | None = Field(None, max_length=100, description="Ex.: '1 caixa', '30 comprimidos', 'uso contínuo'")
    via: str | None = Field(None, max_length=50, description="Ex.: oral, IV, tópica")


class RascunhoIn(BaseModel):
    paciente: Paciente
    itens: list[Item] = Field(min_length=1, max_length=30)
    alergias: list[str] = Field(default_factory=list, max_length=30)
    nota_para_medico: str | None = Field(
        None, max_length=2000, description="Resumo do raciocínio/pendências para o médico ler antes de emitir. NÃO vai para a receita."
    )
