from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ptbr_benchmark.cli import build_parser, main
from tests.conftest import TASKS_DIR, make_completion
from tests.test_providers import ScriptedProvider


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cópia das tarefas com apenas dois datasets pequenos, para CLI rápida."""
    tasks_dir = tmp_path / "tasks"
    shutil.copytree(TASKS_DIR, tasks_dir)
    monkeypatch.setenv("PTBR_BENCHMARK_TASKS_DIR", str(tasks_dir))
    monkeypatch.setenv("PTBR_BENCHMARK_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("PTBR_BENCHMARK_DOCS_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("PTBR_BENCHMARK_SITE_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("PTBR_BENCHMARK_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("PTBR_BENCHMARK_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return tmp_path


def test_version_and_parser() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--tasks", "ticket_routing", "--limit", "3"])
    assert args.command == "run" and args.limit == 3
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])


def test_validate(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "fiscal_extraction" in out and "total" in out
    assert main(["validate", "--tasks", "ticket_routing,lgpd_refusal"]) == 0


def test_validate_reports_domain_error(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = workspace / "tasks" / "regional_ptbr" / "dataset.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    broken = json.loads(rows[0])
    broken["expected"]["answer"] = "Z"
    rows[0] = json.dumps(broken, ensure_ascii=False)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert main(["validate", "--tasks", "regional_ptbr"]) == 1
    assert "erro:" in capsys.readouterr().err


def test_run_report_and_cascade_end_to_end(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["run", "--tasks", "ticket_routing,regional_ptbr", "--limit", "6", "--repetitions", "2"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "observações" in out
    run_dirs = [p for p in (workspace / "results").iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    assert manifest["observations"] == 24

    assert (
        main(
            [
                "run",
                "--tasks",
                "ticket_routing,regional_ptbr",
                "--limit",
                "6",
                "--repetitions",
                "2",
                "--prompt",
                "optimized",
                "--no-cache",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "run",
                "--tasks",
                "ticket_routing,regional_ptbr",
                "--limit",
                "6",
                "--repetitions",
                "1",
                "--cascade-to",
                "baseline:baseline-rules",
            ]
        )
        == 0
    )
    cascade_files = list((workspace / "results").glob("*/cascade.json"))
    assert len(cascade_files) == 1
    cascade = json.loads(cascade_files[0].read_text())
    assert cascade["total"] == 12

    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "relatório:" in out
    assert (workspace / "docs" / "results.md").exists()
    page = (workspace / "site" / "index.html").read_text(encoding="utf-8")
    assert "ticket_routing" in page and "regional_ptbr" in page
    summary = json.loads((workspace / "site" / "summary.json").read_text())
    assert summary["dataset_sizes"]["ticket_routing"] == 150
    assert summary["dataset_families"]["ticket_routing"] == 48
    assert summary["publication_status"] == "calibration"


def test_run_errors(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--prompt", "inexistente", "--tasks", "ticket_routing"]) == 1
    assert "não tem prompt" in capsys.readouterr().err
    assert (
        main(["run", "--tasks", "ticket_routing", "--limit", "2", "--cascade-to", "baseline"]) == 1
    )
    assert "provedor:modelo" in capsys.readouterr().err
    assert (
        main(["run", "--provider", "anthropic", "--tasks", "ticket_routing", "--limit", "1"]) == 1
    )
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert main(["run", "--provider", "openai", "--tasks", "ticket_routing", "--limit", "1"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_report_without_runs(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report"]) == 1
    assert "nenhuma rodada" in capsys.readouterr().err


def test_datasets_generate_and_holdout(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["datasets", "generate-fiscal", "--count", "8", "--seed", "3"]) == 0
    dataset = workspace / "tasks" / "fiscal_extraction" / "dataset.jsonl"
    assert len(dataset.read_text(encoding="utf-8").splitlines()) == 8
    assert main(["validate", "--tasks", "fiscal_extraction"]) == 1
    assert "publicação exige pelo menos 150" in capsys.readouterr().err

    assert main(["datasets", "holdout", "--count", "4"]) == 0
    out = capsys.readouterr().out
    assert "curadoria manual" in out
    holdout = workspace / "tasks" / "fiscal_extraction" / "holdout.jsonl"
    assert len(holdout.read_text(encoding="utf-8").splitlines()) == 4
    assert (
        main(["run", "--tasks", "fiscal_extraction", "--split", "holdout", "--repetitions", "1"])
        == 0
    )
    assert main(["datasets", "holdout", "--tasks", "ticket_routing"]) == 1

    assert main(["run", "--tasks", "ticket_routing", "--split", "holdout", "--limit", "1"]) == 1
    assert "holdout" in capsys.readouterr().err


def test_judge_validate_writes_validation_file(
    workspace: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = workspace / "tasks" / "grounded_qa" / "dataset.jsonl"
    ids = [json.loads(line)["id"] for line in dataset.read_text(encoding="utf-8").splitlines()]
    ids = ids[:30]
    labels = workspace / "labels.jsonl"
    labels.write_text(
        "\n".join(
            json.dumps({"item_id": i, "candidate": "x", "label": "correct" if n % 3 else "partial"})
            for n, i in enumerate(ids)
        ),
        encoding="utf-8",
    )
    always_correct = ScriptedProvider(*[make_completion('{"label": "correct"}')] * 30)
    monkeypatch.setattr("ptbr_benchmark.cli.build_provider", lambda *a, **k: always_correct)
    argv = ["judge-validate", "--task", "grounded_qa", "--model", "m", "--labels", str(labels)]
    assert main(argv) == 2
    assert "rejeitado" in capsys.readouterr().out
    saved = json.loads(
        (workspace / "results" / "judge_validation" / "grounded_qa.json").read_text()
    )
    assert saved["accepted"] is False and saved["sample_size"] == 30

    perfect = ScriptedProvider(
        *[
            make_completion(json.dumps({"label": "correct" if n % 3 else "partial"}))
            for n in range(30)
        ]
    )
    monkeypatch.setattr("ptbr_benchmark.cli.build_provider", lambda *a, **k: perfect)
    assert main(argv) == 0
    assert "aceito" in capsys.readouterr().out
