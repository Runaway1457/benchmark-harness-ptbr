"""Regras estruturais do repositório.

Módulo que ninguém importa é fiação morta. README que descreve comando que a
CLI não tem é fiação morta. Estes testes falham antes que o leitor descubra.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ptbr_benchmark.cli import build_parser
from tests.conftest import REPO_ROOT

PACKAGE = REPO_ROOT / "ptbr_benchmark"


def _modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
    return found


def test_every_module_is_imported_by_another_module_or_is_an_entrypoint() -> None:
    modules = _modules()
    imported: set[str] = set()
    for path in modules.values():
        imported |= _imports(path)
    entrypoints = {"ptbr_benchmark", "ptbr_benchmark.cli"}
    orphans = sorted(
        name
        for name, path in modules.items()
        if name not in entrypoints and path.name != "__init__.py" and name not in imported
    )
    assert orphans == [], f"módulos sem nenhum importador: {orphans}"


def test_domain_does_not_depend_on_infrastructure() -> None:
    forbidden = (
        "httpx",
        "sqlite3",
        "structlog",
        "ptbr_benchmark.providers",
        "ptbr_benchmark.runner",
        "ptbr_benchmark.report",
    )
    for path in (PACKAGE / "domain").glob("*.py"):
        offenders = [name for name in _imports(path) if name.startswith(forbidden)]
        assert offenders == [], f"{path.name} importa infraestrutura: {offenders}"


def test_tasks_do_not_import_providers_or_runner() -> None:
    for path in (PACKAGE / "tasks").glob("*.py"):
        offenders = [
            name
            for name in _imports(path)
            if name.startswith(("ptbr_benchmark.runner", "ptbr_benchmark.report", "httpx"))
        ]
        assert offenders == [], f"{path.name} acopla tarefa a infraestrutura: {offenders}"


def test_readme_commands_exist_in_cli() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    parser = build_parser()
    subcommands = set(parser._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    used = set(
        re.findall(r"ptbr-benchmark (validate|run|report|datasets|judge-validate)\b", readme)
    )
    assert used, "README sem exemplos de uso da CLI"
    assert used <= subcommands


def test_every_task_directory_has_prompts_dataset_and_readme() -> None:
    for directory in sorted((REPO_ROOT / "tasks").iterdir()):
        if not directory.is_dir():
            continue
        assert (directory / "dataset.jsonl").exists(), directory
        assert (directory / "prompts" / "minimal.md").exists(), directory
        assert (directory / "prompts" / "optimized.md").exists(), directory
        assert (directory / "README.md").exists(), f"{directory.name} sem README"


def test_no_committed_holdout() -> None:
    committed = [p for p in (REPO_ROOT / "tasks").glob("*/holdout.jsonl")]
    assert committed == [], "holdout não pode ser versionado; use holdout.example.jsonl"
