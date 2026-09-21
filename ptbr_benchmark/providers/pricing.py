"""Tabela de preço por modelo.

Preço muda. A tabela é um arquivo versionado com data de referência, e o
relatório carrega essa data. Modelo sem preço cadastrado entra com custo
desconhecido, nunca com zero silencioso.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ptbr_benchmark.domain.models import DomainError, Usage

DEFAULT_PRICING_PATH = Path(__file__).with_name("pricing.json")


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million_usd: float
    output_per_million_usd: float

    def cost(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self.input_per_million_usd
            + usage.output_tokens * self.output_per_million_usd
        ) / 1_000_000


@dataclass(frozen=True, slots=True)
class PricingTable:
    as_of: str
    prices: dict[str, ModelPrice]

    def price_for(self, model: str) -> ModelPrice | None:
        if model in self.prices:
            return self.prices[model]
        # Permite cadastrar prefixo, para versões datadas do mesmo modelo.
        for key in sorted(self.prices, key=len, reverse=True):
            if model.startswith(key):
                return self.prices[key]
        return None


def load_pricing(path: Path = DEFAULT_PRICING_PATH) -> PricingTable:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DomainError(f"tabela de preço não encontrada: {path}") from exc
    prices = {
        model: ModelPrice(
            input_per_million_usd=float(entry["input_per_million_usd"]),
            output_per_million_usd=float(entry["output_per_million_usd"]),
        )
        for model, entry in raw["models"].items()
    }
    return PricingTable(as_of=str(raw["as_of"]), prices=prices)
