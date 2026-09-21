"""Cache de respostas endereçado por conteúdo.

A chave é o hash de (provedor, modelo, prompt renderizado, seed). Mudar uma
palavra no prompt invalida o cache sozinho, sem versão manual. O cache
guarda o uso de tokens e a latência original, para que uma reexecução
reporte o custo real da primeira chamada, marcada como cache hit.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock

from ptbr_benchmark.domain.models import Completion, Usage, stable_hash
from ptbr_benchmark.providers.base import CompletionRequest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS completions (
    key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def cache_key(provider_name: str, request: CompletionRequest) -> str:
    return stable_hash(
        {
            "provider": provider_name,
            "model": request.model,
            "system": request.system,
            "user": request.user,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "seed": request.seed,
        }
    )


class CompletionCache:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._lock = Lock()
        with self._lock:
            self._connection.execute(_SCHEMA)
            self._connection.commit()

    def get(self, key: str) -> Completion | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM completions WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return Completion(
            text=data["text"],
            model=data["model"],
            usage=Usage(
                input_tokens=data["usage"]["input_tokens"],
                output_tokens=data["usage"]["output_tokens"],
                estimated=data["usage"].get("estimated", False),
            ),
            latency_ms=data["latency_ms"],
            cached=True,
            attempts=data.get("attempts", 1),
            cost_usd=data.get("cost_usd"),
        )

    def put(self, key: str, provider_name: str, completion: Completion) -> None:
        payload = json.dumps(
            {
                "text": completion.text,
                "model": completion.model,
                "usage": {
                    "input_tokens": completion.usage.input_tokens,
                    "output_tokens": completion.usage.output_tokens,
                    "estimated": completion.usage.estimated,
                },
                "latency_ms": completion.latency_ms,
                "attempts": completion.attempts,
                "cost_usd": completion.cost_usd,
            },
            ensure_ascii=False,
        )
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO completions (key, provider, model, payload) "
                "VALUES (?, ?, ?, ?)",
                (key, provider_name, completion.model, payload),
            )
            self._connection.commit()

    def count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) FROM completions").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()
