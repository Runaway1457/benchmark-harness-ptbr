"""Validadores e geradores de identificadores brasileiros.

Usados tanto para gerar dado sintético plausível quanto para validar o que o
modelo devolve. Um CNPJ com dígito verificador errado é um erro de extração,
mesmo que os primeiros doze dígitos estejam corretos.
"""

from __future__ import annotations

import random

from ptbr_benchmark.scoring.normalize import digits_only

_CNPJ_WEIGHTS_FIRST = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_SECOND = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def _cnpj_check_digit(digits: str, weights: tuple[int, ...]) -> int:
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights, strict=True))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cnpj(value: str) -> bool:
    digits = digits_only(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    first = _cnpj_check_digit(digits[:12], _CNPJ_WEIGHTS_FIRST)
    second = _cnpj_check_digit(digits[:12] + str(first), _CNPJ_WEIGHTS_SECOND)
    return digits[12:] == f"{first}{second}"


def generate_cnpj(rng: random.Random) -> str:
    """CNPJ sintético com dígitos verificadores corretos, formatado."""
    base = "".join(str(rng.randint(0, 9)) for _ in range(8)) + "0001"
    first = _cnpj_check_digit(base, _CNPJ_WEIGHTS_FIRST)
    second = _cnpj_check_digit(base + str(first), _CNPJ_WEIGHTS_SECOND)
    digits = f"{base}{first}{second}"
    return format_cnpj(digits)


def format_cnpj(digits: str) -> str:
    clean = digits_only(digits)
    if len(clean) != 14:
        raise ValueError("CNPJ precisa de 14 dígitos")
    return f"{clean[:2]}.{clean[2:5]}.{clean[5:8]}/{clean[8:12]}-{clean[12:]}"


def is_valid_cpf(value: str) -> bool:
    digits = digits_only(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for length in (9, 10):
        total = sum(int(digits[i]) * (length + 1 - i) for i in range(length))
        remainder = (total * 10) % 11
        remainder = 0 if remainder == 10 else remainder
        if remainder != int(digits[length]):
            return False
    return True


def generate_cpf(rng: random.Random) -> str:
    base = [rng.randint(0, 9) for _ in range(9)]
    for length in (9, 10):
        total = sum(base[i] * (length + 1 - i) for i in range(length))
        remainder = (total * 10) % 11
        base.append(0 if remainder == 10 else remainder)
    digits = "".join(str(d) for d in base)
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


# Subconjunto de CFOPs de saída frequentes em operações comerciais.
VALID_CFOPS: frozenset[str] = frozenset(
    {
        "5101",
        "5102",
        "5103",
        "5109",
        "5110",
        "5116",
        "5117",
        "5401",
        "5403",
        "5405",
        "5910",
        "5915",
        "5949",
        "6101",
        "6102",
        "6107",
        "6108",
        "6401",
        "6403",
        "6404",
        "6910",
        "6949",
    }
)


def is_valid_cfop(value: str) -> bool:
    return digits_only(value) in VALID_CFOPS


# NCMs de produtos comuns em nota de venda B2B. Código e descrição resumida.
COMMON_NCMS: tuple[tuple[str, str], ...] = (
    ("84713012", "Notebook com tela inferior a 14 polegadas"),
    ("84713019", "Notebook, outros"),
    ("84714110", "Estação de trabalho de processamento"),
    ("84716052", "Teclado"),
    ("84716053", "Mouse"),
    ("85285200", "Monitor de vídeo"),
    ("48201000", "Livros de registro, cadernos"),
    ("48025510", "Papel A4 em folhas"),
    ("94013000", "Cadeira giratória de escritório"),
    ("94033000", "Mesa de madeira para escritório"),
    ("85171231", "Telefone celular"),
    ("85044010", "Carregador de acumulador"),
    ("39269090", "Artefatos de plástico, outros"),
    ("61091000", "Camiseta de algodão"),
    ("62034200", "Calça de algodão"),
    ("21069090", "Preparações alimentícias, outros"),
    ("22021000", "Água mineral gaseificada"),
    ("09012100", "Café torrado não descafeinado"),
    ("34011190", "Sabonete, outros"),
    ("33049990", "Produtos de beleza, outros"),
)

VALID_NCMS: frozenset[str] = frozenset(code for code, _ in COMMON_NCMS)


def is_valid_ncm(value: str) -> bool:
    return digits_only(value) in VALID_NCMS


BRAZILIAN_STATES: tuple[str, ...] = (
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
)
