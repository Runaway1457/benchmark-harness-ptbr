"""Gerador de DANFE sintético.

Produz o texto de uma nota como sairia de um OCR razoável: rótulos em caixa
alta, campos com separadores variados, ruído controlado. O gabarito é gerado
junto, então não há anotação manual e não há erro de anotação.

Todo identificador é válido por dígito verificador. Todo CFOP e NCM existe.
O valor total fecha com a soma dos itens. Isso permite que o pontuador
distinga erro de extração de erro de dado.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ptbr_benchmark.scoring.brazil import BRAZILIAN_STATES, COMMON_NCMS, generate_cnpj
from ptbr_benchmark.scoring.normalize import digits_only

_COMPANY_PREFIXES = (
    "Comercial",
    "Distribuidora",
    "Indústria",
    "Atacadão",
    "Tecnologia",
    "Logística",
    "Serviços",
    "Papelaria",
    "Alimentos",
    "Confecções",
    "Suprimentos",
    "Soluções",
)
_COMPANY_CORES = (
    "Horizonte",
    "Mantiqueira",
    "Ipiranga",
    "Guararapes",
    "Tocantins",
    "Aurora",
    "Pampa",
    "Paraíba",
    "Cerrado",
    "Amazônia",
    "Serra Azul",
    "Tietê",
    "Cariri",
    "Pantanal",
    "Vale Verde",
    "Itapuã",
    "Bandeirantes",
    "Nordestina",
    "Araucária",
    "Mangue",
)
_COMPANY_SUFFIXES = ("Ltda", "S.A.", "Eireli", "ME", "Ltda ME", "Comércio Ltda")

_STREETS = (
    "Rua das Acácias",
    "Avenida Brasil",
    "Rua Quinze de Novembro",
    "Avenida Paulista",
    "Rua Barão do Rio Branco",
    "Avenida Getúlio Vargas",
    "Rua Sete de Setembro",
    "Rua Marechal Deodoro",
    "Avenida Independência",
    "Travessa São José",
)
_CITIES_BY_STATE: dict[str, tuple[str, ...]] = {
    "SP": ("São Paulo", "Campinas", "Ribeirão Preto", "Sorocaba"),
    "RJ": ("Rio de Janeiro", "Niterói", "Petrópolis"),
    "MG": ("Belo Horizonte", "Uberlândia", "Juiz de Fora"),
    "RS": ("Porto Alegre", "Caxias do Sul", "Pelotas"),
    "PR": ("Curitiba", "Londrina", "Maringá"),
    "SC": ("Florianópolis", "Joinville", "Blumenau"),
    "BA": ("Salvador", "Feira de Santana", "Vitória da Conquista"),
    "PE": ("Recife", "Caruaru", "Petrolina"),
    "CE": ("Fortaleza", "Juazeiro do Norte", "Sobral"),
    "GO": ("Goiânia", "Anápolis", "Rio Verde"),
    "PA": ("Belém", "Santarém", "Marabá"),
    "AM": ("Manaus", "Parintins"),
    "DF": ("Brasília",),
    "ES": ("Vitória", "Vila Velha", "Cachoeiro de Itapemirim"),
    "MT": ("Cuiabá", "Rondonópolis"),
    "MS": ("Campo Grande", "Dourados"),
}

# Código IBGE da UF, usado nos dois primeiros dígitos da chave de acesso.
_IBGE_UF_CODES: dict[str, str] = {
    "RO": "11",
    "AC": "12",
    "AM": "13",
    "RR": "14",
    "PA": "15",
    "AP": "16",
    "TO": "17",
    "MA": "21",
    "PI": "22",
    "CE": "23",
    "RN": "24",
    "PB": "25",
    "PE": "26",
    "AL": "27",
    "SE": "28",
    "BA": "29",
    "MG": "31",
    "ES": "32",
    "RJ": "33",
    "SP": "35",
    "PR": "41",
    "SC": "42",
    "RS": "43",
    "MS": "50",
    "MT": "51",
    "GO": "52",
    "DF": "53",
}

_NATURES_INTRASTATE = (
    ("Venda de mercadoria adquirida de terceiros", "5102"),
    ("Venda de produção do estabelecimento", "5101"),
    ("Remessa para conserto", "5915"),
    ("Remessa de bonificação", "5910"),
    ("Venda com substituição tributária", "5403"),
)
_NATURES_INTERSTATE = (
    ("Venda de mercadoria adquirida de terceiros", "6102"),
    ("Venda de produção do estabelecimento", "6101"),
    ("Remessa de bonificação", "6910"),
    ("Venda com substituição tributária", "6403"),
)


@dataclass(frozen=True, slots=True)
class SyntheticInvoice:
    document: str
    expected: dict[str, Any]
    tags: tuple[str, ...]


def _brl(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, _, fraction = f"{quantized:.2f}".partition(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    return f"{grouped},{fraction}"


def _company(rng: random.Random) -> str:
    prefix = rng.choice(_COMPANY_PREFIXES)
    core = rng.choice(_COMPANY_CORES)
    return f"{prefix} {core} {rng.choice(_COMPANY_SUFFIXES)}"


def _address(rng: random.Random, state: str) -> tuple[str, str]:
    cities = _CITIES_BY_STATE.get(state) or ("Cidade Nova",)
    city = rng.choice(cities)
    cep = f"{rng.randint(10000, 99999)}-{rng.randint(100, 999):03d}"
    return f"{rng.choice(_STREETS)}, {rng.randint(10, 4999)}", f"{city} - {state}  CEP {cep}"


def _access_key(
    rng: random.Random,
    *,
    state_code: str,
    emission: date,
    cnpj_digits: str,
    serie: int,
    numero: int,
) -> str:
    prefix = _IBGE_UF_CODES[state_code]
    body = (
        prefix
        + emission.strftime("%y%m")
        + cnpj_digits
        + "55"
        + f"{serie:03d}"
        + f"{numero:09d}"
        + "1"
        + f"{rng.randint(0, 99999999):08d}"
    )
    digit = _mod11(body)
    return body + str(digit)


def _mod11(digits: str) -> int:
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        total += int(digit) * weights[index % len(weights)]
    remainder = total % 11
    return 0 if remainder in (0, 1) else 11 - remainder


def _format_key(key: str) -> str:
    return " ".join(key[i : i + 4] for i in range(0, 44, 4))


@dataclass(frozen=True, slots=True)
class _InvoiceData:
    emitter_state: str
    receiver_state: str
    nature: str
    cfop: str
    emitter_cnpj: str
    receiver_cnpj: str
    emitter_name: str
    receiver_name: str
    numero: int
    serie: int
    emission: date
    items: tuple[tuple[str, str, str, int, Decimal, Decimal], ...]
    products_total: Decimal
    freight: Decimal
    discount: Decimal
    key: str
    emitter_address: tuple[str, str]
    receiver_address: tuple[str, str]

    @property
    def total(self) -> Decimal:
        return self.products_total + self.freight - self.discount

    @property
    def same_state(self) -> bool:
        return self.emitter_state == self.receiver_state


def _draw_invoice(rng: random.Random) -> _InvoiceData:
    states = [s for s in BRAZILIAN_STATES if s in _CITIES_BY_STATE]
    emitter_state = rng.choice(states)
    same_state = rng.random() < 0.55
    receiver_state = (
        emitter_state if same_state else rng.choice([s for s in states if s != emitter_state])
    )
    nature, cfop = rng.choice(_NATURES_INTRASTATE if same_state else _NATURES_INTERSTATE)

    emitter_name = _company(rng)
    receiver_name = _company(rng)
    while receiver_name == emitter_name:
        receiver_name = _company(rng)

    numero = rng.randint(1000, 999999)
    serie = rng.choice((1, 1, 1, 2, 3))
    emission = date(2026, 1, 1) + timedelta(days=rng.randint(0, 250))

    items: list[tuple[str, str, str, int, Decimal, Decimal]] = []
    products_total = Decimal("0")
    for index in range(rng.randint(1, 6)):
        ncm, description = rng.choice(COMMON_NCMS)
        quantity = rng.randint(1, 40)
        unit = Decimal(rng.randint(590, 489900)) / 100
        subtotal = (unit * quantity).quantize(Decimal("0.01"))
        products_total += subtotal
        items.append((f"{index + 1:03d}", ncm, description, quantity, unit, subtotal))

    freight_rate = Decimal(rng.choice(("0", "0", "0.02", "0.035")))
    discount_rate = Decimal(rng.choice(("0", "0", "0", "0.05")))
    emitter_cnpj = generate_cnpj(rng)
    return _InvoiceData(
        emitter_state=emitter_state,
        receiver_state=receiver_state,
        nature=nature,
        cfop=cfop,
        emitter_cnpj=emitter_cnpj,
        receiver_cnpj=generate_cnpj(rng),
        emitter_name=emitter_name,
        receiver_name=receiver_name,
        numero=numero,
        serie=serie,
        emission=emission,
        items=tuple(items),
        products_total=products_total,
        freight=(products_total * freight_rate).quantize(Decimal("0.01")),
        discount=(products_total * discount_rate).quantize(Decimal("0.01")),
        key=_access_key(
            rng,
            state_code=emitter_state,
            emission=emission,
            cnpj_digits=digits_only(emitter_cnpj),
            serie=serie,
            numero=numero,
        ),
        emitter_address=_address(rng, emitter_state),
        receiver_address=_address(rng, receiver_state),
    )


def _render_document(data: _InvoiceData, rng: random.Random, *, noise: str) -> str:
    sep = rng.choice((":", " :", ": ", " - ")) if noise != "clean" else ": "
    cfop = f"{data.cfop[0]}.{data.cfop[1:]}" if rng.random() < 0.5 else data.cfop
    emitter_street, emitter_city = data.emitter_address
    receiver_street, receiver_city = data.receiver_address
    complement = rng.choice(
        (
            "Documento emitido por ME ou EPP optante pelo Simples Nacional.",
            "Não gera direito a crédito fiscal de IPI.",
            "Mercadoria sujeita a conferência no recebimento.",
            f"Pedido de compra nº {rng.randint(10000, 99999)}.",
        )
    )
    item_lines = [
        f"{code}  {ncm}  {description:<44}{quantity:>4}  {_brl(unit):>10}  {_brl(subtotal):>12}"
        for code, ncm, description, quantity, unit, subtotal in data.items
    ]
    header_line = (
        "CÓD  NCM       DESCRIÇÃO                                   QTD   VL UNIT      VL TOTAL"
    )
    lines = [
        "DANFE - DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRÔNICA",
        f"0 - ENTRADA   1 - SAÍDA  [1]     Nº {data.numero}    SÉRIE{sep}{data.serie}",
        f"CHAVE DE ACESSO{sep}{_format_key(data.key)}",
        f"NATUREZA DA OPERAÇÃO{sep}{data.nature}",
        f"DATA DE EMISSÃO{sep}{data.emission.strftime('%d/%m/%Y')}",
        f"CFOP{sep}{cfop}",
        "",
        "EMITENTE",
        f"RAZÃO SOCIAL{sep}{data.emitter_name}",
        f"CNPJ{sep}{data.emitter_cnpj}",
        f"ENDEREÇO{sep}{emitter_street}",
        f"MUNICÍPIO{sep}{emitter_city}   UF{sep}{data.emitter_state}",
        f"INSCRIÇÃO ESTADUAL{sep}{rng.randint(100000000, 999999999)}",
        "",
        "DESTINATÁRIO / REMETENTE",
        f"RAZÃO SOCIAL{sep}{data.receiver_name}",
        f"CNPJ{sep}{data.receiver_cnpj}",
        f"ENDEREÇO{sep}{receiver_street}",
        f"MUNICÍPIO{sep}{receiver_city}   UF{sep}{data.receiver_state}",
        "",
        "DADOS DOS PRODUTOS / SERVIÇOS",
        header_line,
        *item_lines,
        "",
        "CÁLCULO DO IMPOSTO",
        f"VALOR TOTAL DOS PRODUTOS{sep}R$ {_brl(data.products_total)}",
        f"VALOR DO FRETE{sep}R$ {_brl(data.freight)}",
        f"DESCONTO{sep}R$ {_brl(data.discount)}",
        f"VALOR TOTAL DA NOTA{sep}R$ {_brl(data.total)}",
        "",
        "INFORMAÇÕES COMPLEMENTARES",
        complement,
    ]
    document = "\n".join(lines)
    if noise == "ocr":
        return _apply_ocr_noise(document, rng)
    if noise == "scrambled":
        return _scramble_blocks(document, rng)
    return document


def generate_invoice(rng: random.Random, *, noise: str = "clean") -> SyntheticInvoice:
    """Gera uma nota. `noise` controla o ruído de layout: clean, ocr ou scrambled."""
    if noise not in {"clean", "ocr", "scrambled"}:
        raise ValueError(f"ruído desconhecido: {noise}")
    data = _draw_invoice(rng)
    document = _render_document(data, rng, noise=noise)
    tags = [noise, "intraestadual" if data.same_state else "interestadual"]
    if noise == "scrambled":
        tags.append("blocos_fora_de_ordem")
    expected: dict[str, Any] = {
        "chave_acesso": data.key,
        "numero": data.numero,
        "serie": data.serie,
        "data_emissao": data.emission.strftime("%d/%m/%Y"),
        "natureza_operacao": data.nature,
        "cfop": data.cfop,
        "emitente_cnpj": digits_only(data.emitter_cnpj),
        "emitente_razao_social": data.emitter_name,
        "emitente_uf": data.emitter_state,
        "destinatario_cnpj": digits_only(data.receiver_cnpj),
        "destinatario_razao_social": data.receiver_name,
        "valor_produtos": str(data.products_total.quantize(Decimal("0.01"))),
        "valor_total": str(data.total.quantize(Decimal("0.01"))),
        "quantidade_itens": len(data.items),
    }
    return SyntheticInvoice(document=document, expected=expected, tags=tuple(tags))


def _apply_ocr_noise(document: str, rng: random.Random) -> str:
    """Ruído típico de OCR em rótulos, nunca em valores.

    Trocar dígito em valor tornaria o gabarito inconsistente com o documento.
    O ruído fica em rótulos e prosa, que é onde OCR de verdade erra sem
    invalidar o dado.
    """
    substitutions = (("Ç", "C"), ("Ã", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"))
    result_lines: list[str] = []
    for line in document.split("\n"):
        if any(token in line for token in ("R$", "CNPJ", "CHAVE", "/20")):
            result_lines.append(line)
            continue
        noisy = line
        for original, replacement in substitutions:
            if rng.random() < 0.4:
                noisy = noisy.replace(original, replacement)
        if rng.random() < 0.15:
            noisy = noisy.replace("  ", " ")
        result_lines.append(noisy)
    return "\n".join(result_lines)


def _scramble_blocks(document: str, rng: random.Random) -> str:
    blocks = document.split("\n\n")
    header, body = blocks[0], blocks[1:]
    rng.shuffle(body)
    return "\n\n".join([header, *body])
