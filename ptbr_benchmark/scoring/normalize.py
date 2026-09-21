"""Normalização de texto e valores para comparação.

Texto em português brasileiro tem armadilhas próprias: acentuação
inconsistente, número com vírgula decimal e ponto de milhar, CNPJ com ou sem
máscara, data em dd/mm/aaaa. Comparar sem normalizar penaliza o modelo por
formatação, não por conteúdo.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_DIGITS_ONLY = re.compile(r"\D")
_BR_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def normalize_text(text: str, *, keep_accents: bool = False) -> str:
    """Minúsculas, sem pontuação, espaços colapsados, opcionalmente sem acento."""
    lowered = unicodedata.normalize("NFC", text).casefold()
    if not keep_accents:
        lowered = strip_accents(lowered)
    without_punctuation = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", without_punctuation).strip()


def digits_only(value: str) -> str:
    return _DIGITS_ONLY.sub("", value)


def parse_brl(value: str | int | float | Decimal) -> Decimal | None:
    """Converte representações brasileiras de valor monetário em Decimal.

    Aceita "R$ 1.234,56", "1234.56", "1.234,56", 1234.56 e Decimal. Devolve
    None quando não consegue interpretar, em vez de chutar.
    """
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    if isinstance(value, int | float):
        return Decimal(str(value)).quantize(Decimal("0.01"))

    cleaned = value.strip().upper().replace("R$", "").replace(" ", "")
    if not cleaned:
        return None
    negative = cleaned.startswith("-") or (cleaned.startswith("(") and cleaned.endswith(")"))
    cleaned = cleaned.strip("-()")

    if "," in cleaned and "." in cleaned:
        # Formato brasileiro: ponto de milhar, vírgula decimal.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Formato anglófono: vírgula de milhar, ponto decimal.
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")

    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative:
        parsed = -parsed
    return parsed.quantize(Decimal("0.01"))


def parse_br_date(value: str) -> date | None:
    """Aceita dd/mm/aaaa e aaaa-mm-dd. Devolve None se inválida."""
    text = value.strip()
    if match := _BR_DATE.match(text):
        day, month, year = (int(part) for part in match.groups())
    elif match := _ISO_DATE.match(text):
        year, month, day = (int(part) for part in match.groups())
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def normalize_cnpj(value: str) -> str:
    return digits_only(value)


def token_set(text: str) -> set[str]:
    return set(normalize_text(text).split())


_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "o",
        "as",
        "os",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "um",
        "uma",
        "por",
        "para",
        "com",
        "que",
        "ao",
        "aos",
        "se",
        "ou",
        "r",
        "us",
    }
)
_CENTS_ZERO = re.compile(r"(\d+),00\b")
_THOUSANDS_DOT = re.compile(r"(?<=\d)\.(?=\d{3}\b)")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def answer_tokens(text: str) -> set[str]:
    """Tokens informativos de uma resposta curta.

    Remove palavras funcionais e tokens de um caractere, e normaliza número
    brasileiro para que "R$ 1.234,56" e "1234.56" produzam os mesmos tokens e
    "R$ 120,00" e "120 reais" compartilhem o token que importa.
    """
    text = _CENTS_ZERO.sub(r"\1", text)
    text = _THOUSANDS_DOT.sub("", text)
    text = _DECIMAL_COMMA.sub(".", text)
    tokens = {t for t in normalize_text(text).split() if t not in _STOPWORDS and len(t) > 1}
    return tokens or token_set(text)


def jaccard(a: str, b: str) -> float:
    """Similaridade de Jaccard sobre tokens normalizados. 1.0 quando ambos vazios."""
    tokens_a = token_set(a)
    tokens_b = token_set(b)
    if not tokens_a and not tokens_b:
        return 1.0
    union = tokens_a | tokens_b
    return len(tokens_a & tokens_b) / len(union)
