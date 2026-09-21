"""Extração de campos de documento fiscal (DANFE em texto).

A entrada é o texto de um DANFE como sairia de um OCR ou de um PDF nativo:
rótulos em caixa alta, campos fora de ordem, ruído de layout. O modelo devolve
os campos estruturados. Pontuação por campo, ponderada pelo custo do erro:
errar CNPJ ou valor total pesa mais que errar natureza da operação.
"""

from __future__ import annotations

import re
from typing import Any

from ptbr_benchmark.domain.models import DomainError, Item, Score, ScoringKind
from ptbr_benchmark.scoring.brazil import is_valid_cfop, is_valid_cnpj
from ptbr_benchmark.scoring.normalize import digits_only, parse_brl
from ptbr_benchmark.scoring.scorers import parse_json_object, score_fieldwise
from ptbr_benchmark.tasks.base import TaskDefinition

FIELD_KINDS: dict[str, str] = {
    "chave_acesso": "digits",
    "numero": "int",
    "serie": "int",
    "data_emissao": "date",
    "natureza_operacao": "text",
    "cfop": "digits",
    "emitente_cnpj": "digits",
    "emitente_razao_social": "text",
    "emitente_uf": "text",
    "destinatario_cnpj": "digits",
    "destinatario_razao_social": "text",
    "valor_produtos": "money",
    "valor_total": "money",
    "quantidade_itens": "int",
}

FIELD_WEIGHTS: dict[str, float] = {
    "chave_acesso": 2.0,
    "emitente_cnpj": 2.0,
    "destinatario_cnpj": 2.0,
    "valor_total": 2.0,
    "valor_produtos": 1.5,
    "data_emissao": 1.5,
    "numero": 1.5,
}

_LABEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "chave_acesso": re.compile(r"CHAVE DE ACESSO\s*[:\-]?\s*([\d\s]{44,60})", re.IGNORECASE),
    "numero": re.compile(r"N[ºO°]\.?\s*(\d{1,9})", re.IGNORECASE),
    "serie": re.compile(r"S[ÉE]RIE\s*[:\-]?\s*(\d{1,3})", re.IGNORECASE),
    "data_emissao": re.compile(
        r"DATA D[EA] EMISS[ÃA]O\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE
    ),
    "natureza_operacao": re.compile(
        r"NATUREZA DA OPERA[ÇC][ÃA]O\s*[:\-]?\s*([^\n]+)", re.IGNORECASE
    ),
    "cfop": re.compile(r"CFOP\s*[:\-]?\s*(\d\.?\d{3})", re.IGNORECASE),
    "valor_produtos": re.compile(
        r"VALOR TOTAL DOS PRODUTOS\s*[:\-]?\s*R?\$?\s*([\d\.,]+)", re.IGNORECASE
    ),
    "valor_total": re.compile(r"VALOR TOTAL DA NOTA\s*[:\-]?\s*R?\$?\s*([\d\.,]+)", re.IGNORECASE),
}
_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_UF = re.compile(r"\bUF\s*[:\-]?\s*([A-Z]{2})\b")
_ITEM_LINE = re.compile(r"^\s*\d{3}\s+\d{8}\b", re.MULTILINE)


class FiscalExtractionTask(TaskDefinition):
    name = "fiscal_extraction"
    scoring_kind = ScoringKind.FIELDWISE
    description = "Extração de campos estruturados de DANFE em texto"

    def validate_item(self, item: Item) -> None:
        document = item.input.get("document")
        if not isinstance(document, str) or len(document) < 100:
            raise DomainError(f"item {item.id}: documento ausente ou curto demais")
        expected = item.expected
        missing = sorted(set(FIELD_KINDS) - set(expected))
        if missing:
            raise DomainError(f"item {item.id}: gabarito sem campos {missing}")
        if not is_valid_cnpj(str(expected["emitente_cnpj"])):
            raise DomainError(f"item {item.id}: CNPJ do emitente inválido no gabarito")
        if not is_valid_cnpj(str(expected["destinatario_cnpj"])):
            raise DomainError(f"item {item.id}: CNPJ do destinatário inválido no gabarito")
        if not is_valid_cfop(str(expected["cfop"])):
            raise DomainError(f"item {item.id}: CFOP inválido no gabarito")
        if len(digits_only(str(expected["chave_acesso"]))) != 44:
            raise DomainError(f"item {item.id}: chave de acesso sem 44 dígitos")

    def prompt_variables(self, item: Item) -> dict[str, Any]:
        return {
            "document": item.input["document"],
            "fields": ", ".join(FIELD_KINDS),
        }

    def parse(self, text: str) -> dict[str, Any] | None:
        return parse_json_object(text)

    def score(self, item: Item, parsed: dict[str, Any] | None) -> Score:
        return score_fieldwise(
            item.expected,
            parsed,
            field_kinds=FIELD_KINDS,
            weights=FIELD_WEIGHTS,
        )

    def baseline(self, item: Item) -> dict[str, Any]:
        document = str(item.input["document"])
        result: dict[str, Any] = {}

        for field_name, pattern in _LABEL_PATTERNS.items():
            match = pattern.search(document)
            if not match:
                result[field_name] = None
                continue
            raw = match.group(1).strip()
            if field_name == "chave_acesso":
                result[field_name] = digits_only(raw)[:44]
            elif field_name in {"numero", "serie"}:
                result[field_name] = int(raw)
            elif field_name in {"valor_produtos", "valor_total"}:
                value = parse_brl(raw)
                result[field_name] = str(value) if value is not None else None
            elif field_name == "natureza_operacao":
                result[field_name] = raw.split("  ")[0].strip()
            elif field_name == "cfop":
                result[field_name] = digits_only(raw)
            else:
                result[field_name] = raw

        cnpjs = _CNPJ.findall(document)
        result["emitente_cnpj"] = digits_only(cnpjs[0]) if cnpjs else None
        result["destinatario_cnpj"] = digits_only(cnpjs[1]) if len(cnpjs) > 1 else None

        result["emitente_razao_social"] = _section_value(document, "EMITENTE", "RAZÃO SOCIAL")
        result["destinatario_razao_social"] = _section_value(document, "DESTINAT", "RAZÃO SOCIAL")

        emitter_block = _section(document, "EMITENTE", "DESTINAT")
        uf = _UF.search(emitter_block)
        result["emitente_uf"] = uf.group(1) if uf else None

        result["quantidade_itens"] = len(_ITEM_LINE.findall(document)) or None
        return result

    def needs_escalation(self, parsed: dict[str, Any] | None) -> bool:
        if parsed is None:
            return True
        cnpj = parsed.get("emitente_cnpj")
        if not cnpj or not is_valid_cnpj(str(cnpj)):
            return True
        total = parsed.get("valor_total")
        return total is None or parse_brl(str(total)) is None


def _section(document: str, start_label: str, end_label: str) -> str:
    upper = document.upper()
    start = upper.find(start_label.upper())
    if start == -1:
        return ""
    end = upper.find(end_label.upper(), start + len(start_label))
    return document[start : end if end != -1 else len(document)]


def _section_value(document: str, section_label: str, field_label: str) -> str | None:
    block = _section(document, section_label, "\n\n")
    if not block:
        return None
    pattern = re.compile(re.escape(field_label) + r"\s*[:\-]?\s*([^\n]+)", re.IGNORECASE)
    match = pattern.search(block)
    return match.group(1).strip() if match else None
