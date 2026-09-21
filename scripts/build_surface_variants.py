#!/usr/bin/env python3
"""Build controlled PT-BR surface variants without inflating statistical N.

The hand-authored source records remain the semantic families. Generated
variants stress register, spelling noise and contextual framing. Their IDs
use ``<family>--<variant>`` so the report can cluster bootstrap by family.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

TARGET_ITEMS = 150
TASKS = ("ticket_routing", "lgpd_refusal", "grounded_qa", "regional_ptbr")
ROOT = Path(__file__).resolve().parents[1]


def _noisy(text: str) -> str:
    replacements = (
        ("Não", "Nao"),
        ("não", "nao"),
        ("vocês", "vcs"),
        ("você", "vc"),
        ("para", "pra"),
        ("porque", "pq"),
        ("está", "ta"),
        ("Estou", "To"),
        ("estou", "to"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return text.rstrip(".?!") + " pfv"


def _ticket(record: dict[str, Any], variant: str) -> None:
    text = str(record["input"]["ticket"])
    if variant == "formal":
        text = (
            f"Prezados, registro a seguinte ocorrência: {text} Solicito o encaminhamento correto."
        )
    elif variant == "noisy":
        text = "oi, " + _noisy(text).lower()
    else:
        text = f"Mensagem recebida pelo atendimento móvel: “{text}” Qual equipe deve assumir?"
    record["input"]["ticket"] = text


def _lgpd(record: dict[str, Any], variant: str) -> None:
    request = str(record["input"]["request"])
    if variant == "formal":
        request = f"Solicitação registrada pelo usuário: {request}"
    elif variant == "noisy":
        request = _noisy(request).lower()
    else:
        request = f"Durante o atendimento foi solicitado o seguinte: “{request}”"
    record["input"]["request"] = request


def _gqa(record: dict[str, Any], variant: str) -> None:
    question = str(record["input"]["question"])
    lowered = question[:1].lower() + question[1:]
    if variant == "formal":
        question = f"Segundo o documento, {lowered}"
    elif variant == "noisy":
        question = _noisy(question).lower()
    else:
        question = f"Responda somente com base nos trechos: {lowered}"
    record["input"]["question"] = question


def _regional(record: dict[str, Any], variant: str) -> None:
    sentence = str(record["input"]["sentence"])
    if variant == "formal":
        sentence = f"Em uma conversa de trabalho, alguém disse: “{sentence}”"
    elif variant == "noisy":
        sentence = f"No grupo da equipe apareceu: “{_noisy(sentence)}”"
    else:
        sentence = f"Um colega usou esta expressão no escritório: “{sentence}”"
    record["input"]["sentence"] = sentence


TRANSFORMS: dict[str, Callable[[dict[str, Any], str], None]] = {
    "ticket_routing": _ticket,
    "lgpd_refusal": _lgpd,
    "grounded_qa": _gqa,
    "regional_ptbr": _regional,
}


def _load_base(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    # Running the script twice must be idempotent.
    return [row for row in rows if "--" not in str(row["id"])]


def build_task(task: str) -> dict[str, int]:
    path = ROOT / "tasks" / task / "dataset.jsonl"
    base = _load_base(path)
    expanded = list(base)
    variants = ("formal", "noisy", "context")
    candidates = [(variant, source) for variant in variants for source in base]
    if task == "lgpd_refusal":
        # Keep the published binary safety task exactly balanced.  The base
        # families are intentionally all retained; only the selection of
        # additional surface forms is stratified.
        target_per_label = TARGET_ITEMS // 2
        current = {
            label: sum(bool(row["expected"]["should_refuse"]) is label for row in expanded)
            for label in (False, True)
        }
        selected: list[tuple[str, dict[str, Any]]] = []
        for label in (False, True):
            needed = target_per_label - current[label]
            pool = [
                candidate
                for candidate in candidates
                if bool(candidate[1]["expected"]["should_refuse"]) is label
            ]
            if needed < 0 or len(pool) < needed:
                raise RuntimeError(f"{task}: cannot build balanced surface variants")
            selected.extend(pool[:needed])
        candidates = selected

    for variant, source in candidates:
        if len(expanded) >= TARGET_ITEMS:
            break
        row = deepcopy(source)
        row["id"] = f"{source['id']}--{variant}"
        row["tags"] = [*row.get("tags", []), "surface_variant", variant]
        TRANSFORMS[task](row, variant)
        expanded.append(row)
    if len(expanded) != TARGET_ITEMS:
        raise RuntimeError(f"{task}: expected {TARGET_ITEMS}, built {len(expanded)}")
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in expanded
        ),
        encoding="utf-8",
    )
    return {
        "items": len(expanded),
        "semantic_families": len(base),
        "surface_variants": len(expanded) - len(base),
    }


def main() -> None:
    manifest = {
        "method": "controlled_surface_variants_v1",
        "statistical_unit": "semantic_family",
        "tasks": {task: build_task(task) for task in TASKS},
    }
    fiscal_path = ROOT / "tasks" / "fiscal_extraction" / "dataset.jsonl"
    fiscal_items = sum(1 for line in fiscal_path.read_text(encoding="utf-8").splitlines() if line)
    manifest["tasks"]["fiscal_extraction"] = {
        "items": fiscal_items,
        "semantic_families": fiscal_items,
        "surface_variants": 0,
    }
    target = ROOT / "tasks" / "dataset-manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
