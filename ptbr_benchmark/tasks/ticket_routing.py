"""Classificação e roteamento de ticket de suporte.

Oito categorias operacionais. O modelo devolve a categoria e uma confiança
autodeclarada. A confiança alimenta a regra de escalada em cascata: abaixo do
limiar, o item vai para um modelo maior.
"""

from __future__ import annotations

from typing import Any

from ptbr_benchmark.domain.models import DomainError, Item, Score, ScoringKind
from ptbr_benchmark.scoring.normalize import normalize_text
from ptbr_benchmark.scoring.scorers import parse_json_object, score_classification
from ptbr_benchmark.tasks.base import TaskDefinition

LABELS: frozenset[str] = frozenset(
    {
        "cobranca",
        "acesso_login",
        "bug_tecnico",
        "cancelamento",
        "duvida_produto",
        "comercial",
        "elogio",
        "fraude_seguranca",
    }
)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fraude_seguranca": (
        "fraude",
        "golpe",
        "clonado",
        "clonaram",
        "invadiram",
        "invasao",
        "nao reconheco",
        "nao fui eu",
        "suspeita",
        "vazamento",
        "hackearam",
        "phishing",
    ),
    "cancelamento": (
        "cancelar",
        "cancelamento",
        "encerrar",
        "rescindir",
        "nao quero mais",
        "desistir",
        "quero sair",
    ),
    "cobranca": (
        "cobranca",
        "cobraram",
        "cobrado",
        "fatura",
        "boleto",
        "duplicidade",
        "estorno",
        "reembolso",
        "valor errado",
        "debito",
        "cartao",
        "pagamento",
        "mensalidade",
    ),
    "acesso_login": (
        "senha",
        "login",
        "logar",
        "acessar",
        "acesso",
        "bloqueado",
        "bloqueada",
        "codigo",
        "autenticacao",
        "2fa",
        "nao consigo entrar",
        "redefinir",
    ),
    "bug_tecnico": (
        "erro",
        "bug",
        "travou",
        "trava",
        "nao carrega",
        "nao abre",
        "tela branca",
        "crash",
        "fechou sozinho",
        "lento",
        "falha",
        "nao funciona",
        "nao salva",
    ),
    "comercial": (
        "proposta",
        "orcamento",
        "plano empresarial",
        "contratar",
        "upgrade",
        "quantos usuarios",
        "desconto",
        "negociar",
        "licencas",
        "revenda",
        "parceria",
    ),
    "duvida_produto": (
        "como faco",
        "como funciona",
        "e possivel",
        "tem como",
        "onde encontro",
        "duvida",
        "consigo",
        "da para",
        "posso",
    ),
    "elogio": (
        "parabens",
        "excelente",
        "adorei",
        "otimo atendimento",
        "muito bom",
        "agradecer",
        "obrigado pelo",
        "sensacional",
        "recomendo",
    ),
}


class TicketRoutingTask(TaskDefinition):
    name = "ticket_routing"
    scoring_kind = ScoringKind.CLASSIFICATION
    description = "Classificação de ticket de suporte em oito categorias"

    def validate_item(self, item: Item) -> None:
        ticket = item.input.get("ticket")
        if not isinstance(ticket, str) or len(ticket.strip()) < 10:
            raise DomainError(f"item {item.id}: ticket ausente ou curto demais")
        category = item.expected.get("category")
        if category not in LABELS:
            raise DomainError(f"item {item.id}: categoria {category!r} fora do conjunto")

    def prompt_variables(self, item: Item) -> dict[str, Any]:
        return {"ticket": item.input["ticket"], "labels": ", ".join(sorted(LABELS))}

    def parse(self, text: str) -> dict[str, Any] | None:
        parsed = parse_json_object(text)
        if parsed is None:
            return None
        category = parsed.get("category")
        if not isinstance(category, str):
            return None
        confidence = parsed.get("confidence")
        try:
            parsed["confidence"] = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            parsed["confidence"] = None
        return parsed

    def score(self, item: Item, parsed: dict[str, Any] | None) -> Score:
        actual = parsed.get("category") if parsed else None
        return score_classification(str(item.expected["category"]), actual, labels=LABELS)

    def baseline(self, item: Item) -> dict[str, Any]:
        text = normalize_text(str(item.input["ticket"]))
        scores = {
            label: sum(1 for keyword in keywords if keyword in text)
            for label, keywords in _KEYWORDS.items()
        }
        best_label, best_hits = max(scores.items(), key=lambda pair: pair[1])
        if best_hits == 0:
            return {"category": "duvida_produto", "confidence": 0.3}
        runner_up = sorted(scores.values(), reverse=True)[1]
        confidence = min(0.95, 0.5 + 0.15 * (best_hits - runner_up))
        return {"category": best_label, "confidence": round(confidence, 2)}

    def needs_escalation(self, parsed: dict[str, Any] | None) -> bool:
        if parsed is None:
            return True
        if normalize_text(str(parsed.get("category", ""))) not in LABELS:
            return True
        confidence = parsed.get("confidence")
        return confidence is None or confidence < 0.6
