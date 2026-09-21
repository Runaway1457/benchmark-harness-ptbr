"""Contrato de tarefa.

Uma tarefa sabe carregar seu dataset, montar a requisição a partir de um
prompt, interpretar a saída do modelo, pontuar contra o gabarito e produzir
uma solução de referência baseada em regras. A solução de referência existe
para dois fins: ser o piso da comparação e permitir que o pipeline inteiro
rode sem chave de API.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ptbr_benchmark.domain.models import (
    DomainError,
    Item,
    Prompt,
    Score,
    ScoringKind,
    Split,
    stable_hash,
)
from ptbr_benchmark.providers.base import CompletionRequest

PROMPT_SEPARATOR = "---"


class TaskDefinition(ABC):
    name: str
    scoring_kind: ScoringKind
    description: str

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / self.name
        if not self._dir.is_dir():
            raise DomainError(f"diretório da tarefa não encontrado: {self._dir}")

    @property
    def directory(self) -> Path:
        return self._dir

    def dataset_path(self, split: Split) -> Path:
        return self._dir / ("dataset.jsonl" if split is Split.PUBLIC else "holdout.jsonl")

    def load_items(self, split: Split = Split.PUBLIC) -> tuple[Item, ...]:
        path = self.dataset_path(split)
        if not path.exists():
            if split is Split.HOLDOUT:
                raise DomainError(
                    f"holdout de {self.name!r} não existe localmente. "
                    "Gere com `ptbr-benchmark datasets holdout` e não versione o arquivo."
                )
            raise DomainError(f"dataset não encontrado: {path}")
        items = tuple(self._read_jsonl(path, split))
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            duplicated = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
            raise DomainError(f"ids duplicados em {self.name}: {duplicated}")
        for item in items:
            self.validate_item(item)
        return items

    def dataset_hash(self, split: Split = Split.PUBLIC) -> str:
        return stable_hash([item.content_hash for item in self.load_items(split)])

    def _read_jsonl(self, path: Path, split: Split) -> Iterator[Item]:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DomainError(f"{path}:{line_number} JSON inválido") from exc
                yield Item(
                    id=str(raw["id"]),
                    task=self.name,
                    input=dict(raw["input"]),
                    expected=dict(raw["expected"]),
                    split=split,
                    tags=tuple(raw.get("tags", ())),
                )

    def load_prompts(self) -> dict[str, Prompt]:
        prompts_dir = self._dir / "prompts"
        found: dict[str, Prompt] = {}
        for path in sorted(prompts_dir.glob("*.md")):
            found[path.stem] = Prompt(name=path.stem, template=path.read_text(encoding="utf-8"))
        if not found:
            raise DomainError(f"tarefa {self.name!r} sem prompts em {prompts_dir}")
        return found

    def build_request(
        self, item: Item, prompt: Prompt, *, model: str, seed: int
    ) -> CompletionRequest:
        rendered = prompt.render(**self.prompt_variables(item))
        system, user = _split_prompt(rendered, prompt.name)
        return CompletionRequest(
            model=model,
            system=system,
            user=user,
            seed=seed,
            metadata={"task": self.name, "item_id": item.id, "input": item.input},
        )

    @abstractmethod
    def validate_item(self, item: Item) -> None:
        """Rejeita item malformado no dataset. Falha cedo, não no relatório."""

    @abstractmethod
    def prompt_variables(self, item: Item) -> dict[str, Any]: ...

    @abstractmethod
    def parse(self, text: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def score(self, item: Item, parsed: dict[str, Any] | None) -> Score: ...

    @abstractmethod
    def baseline(self, item: Item) -> dict[str, Any]:
        """Solução de referência por regras. Devolve o mesmo formato que o modelo."""

    def needs_escalation(self, parsed: dict[str, Any] | None) -> bool:
        """Regra de roteamento em cascata. Por padrão, escala quando não parseia."""
        return parsed is None


def _split_prompt(rendered: str, name: str) -> tuple[str, str]:
    lines = rendered.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == PROMPT_SEPARATOR:
            system = "\n".join(lines[:index]).strip()
            user = "\n".join(lines[index + 1 :]).strip()
            if not user:
                raise DomainError(f"prompt {name!r} sem bloco de usuário após o separador")
            return system, user
    raise DomainError(f"prompt {name!r} sem separador '---' entre system e user")
