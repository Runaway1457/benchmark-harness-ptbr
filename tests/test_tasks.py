from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

import pytest

from ptbr_benchmark.domain.models import DomainError, Item, Split
from ptbr_benchmark.scoring.brazil import is_valid_cnpj
from ptbr_benchmark.tasks.base import TaskDefinition, _split_prompt
from ptbr_benchmark.tasks.fiscal_extraction import FIELD_KINDS, FiscalExtractionTask
from ptbr_benchmark.tasks.fiscal_synth import _IBGE_UF_CODES, generate_invoice
from ptbr_benchmark.tasks.grounded_qa import GroundedQaTask
from ptbr_benchmark.tasks.lgpd_refusal import LgpdRefusalTask
from ptbr_benchmark.tasks.regional_ptbr import RegionalPtBrTask
from ptbr_benchmark.tasks.registry import TASK_NAMES, load_tasks
from ptbr_benchmark.tasks.ticket_routing import LABELS, TicketRoutingTask
from tests.conftest import TASKS_DIR


class TestRegistryAndBase:
    def test_all_tasks_load_and_validate(self, tasks: dict[str, TaskDefinition]) -> None:
        assert set(tasks) == set(TASK_NAMES)
        for task in tasks.values():
            items = task.load_items()
            assert len(items) >= 40
            prompts = task.load_prompts()
            assert {"minimal", "optimized"} <= set(prompts)
            request = task.build_request(items[0], prompts["optimized"], model="m", seed=1)
            assert request.system and request.user
            assert request.metadata["task"] == task.name

    def test_unknown_task_name(self) -> None:
        with pytest.raises(DomainError, match="desconhecidas"):
            load_tasks(TASKS_DIR, ("nope",))

    def test_missing_directory(self, tmp_path: Path) -> None:
        with pytest.raises(DomainError, match="não encontrado"):
            TicketRoutingTask(tmp_path)

    def test_holdout_missing_gives_actionable_error(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["ticket_routing"]
        if task.dataset_path(Split.HOLDOUT).exists():
            pytest.skip("holdout local presente")
        with pytest.raises(DomainError, match="holdout"):
            task.load_items(Split.HOLDOUT)

    def test_dataset_hash_is_content_based(self, tmp_path: Path) -> None:
        directory = tmp_path / "ticket_routing"
        directory.mkdir()
        (directory / "prompts").mkdir()
        (directory / "prompts" / "minimal.md").write_text("s\n---\n{ticket}", encoding="utf-8")
        rows = [
            {
                "id": "a",
                "input": {"ticket": "quero cancelar meu plano"},
                "expected": {"category": "cancelamento"},
            },
            {
                "id": "b",
                "input": {"ticket": "cobraram duas vezes"},
                "expected": {"category": "cobranca"},
            },
        ]
        path = directory / "dataset.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        task = TicketRoutingTask(tmp_path)
        first = task.dataset_hash()
        rows[1]["id"] = "c"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        assert task.dataset_hash() == first
        rows[1]["expected"] = {"category": "elogio"}
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        assert task.dataset_hash() != first

    def test_duplicate_ids_and_bad_json(self, tmp_path: Path) -> None:
        directory = tmp_path / "ticket_routing"
        (directory / "prompts").mkdir(parents=True)
        (directory / "prompts" / "minimal.md").write_text("s\n---\n{ticket}", encoding="utf-8")
        row = {
            "id": "a",
            "input": {"ticket": "quero cancelar meu plano"},
            "expected": {"category": "cancelamento"},
        }
        path = directory / "dataset.jsonl"
        path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
        with pytest.raises(DomainError, match="duplicados"):
            TicketRoutingTask(tmp_path).load_items()
        path.write_text("{not json\n", encoding="utf-8")
        with pytest.raises(DomainError, match="JSON inválido"):
            TicketRoutingTask(tmp_path).load_items()
        path.unlink()
        with pytest.raises(DomainError, match="dataset não encontrado"):
            TicketRoutingTask(tmp_path).load_items()

    def test_prompts_required(self, tmp_path: Path) -> None:
        directory = tmp_path / "ticket_routing"
        (directory / "prompts").mkdir(parents=True)
        with pytest.raises(DomainError, match="sem prompts"):
            TicketRoutingTask(tmp_path).load_prompts()

    def test_split_prompt_rules(self) -> None:
        assert _split_prompt("sys\n---\nuser", "p") == ("sys", "user")
        with pytest.raises(DomainError, match="sem separador"):
            _split_prompt("apenas user", "p")
        with pytest.raises(DomainError, match="sem bloco de usuário"):
            _split_prompt("sys\n---\n", "p")

    def test_default_escalation_rule(self, tasks: dict[str, TaskDefinition]) -> None:
        assert tasks["lgpd_refusal"].needs_escalation(None)
        assert tasks["regional_ptbr"].needs_escalation(None)
        assert not tasks["regional_ptbr"].needs_escalation({"answer": "A"})


class TestFiscal:
    def test_generator_is_deterministic_and_valid(self) -> None:
        a = generate_invoice(random.Random(3), noise="ocr")
        b = generate_invoice(random.Random(3), noise="ocr")
        assert a == b
        assert is_valid_cnpj(str(a.expected["emitente_cnpj"]))
        assert len(str(a.expected["chave_acesso"])) == 44
        assert set(a.expected) == set(FIELD_KINDS)
        with pytest.raises(ValueError, match="ruído"):
            generate_invoice(random.Random(1), noise="weird")

    def test_access_key_encodes_emitter_state(self) -> None:
        for seed in range(20):
            invoice = generate_invoice(random.Random(seed))
            key = str(invoice.expected["chave_acesso"])
            state = str(invoice.expected["emitente_uf"])
            assert key[:2] == _IBGE_UF_CODES[state]
            assert key[6:20] == invoice.expected["emitente_cnpj"]

    def test_noise_variants_keep_values_intact(self) -> None:
        for noise in ("clean", "ocr", "scrambled"):
            invoice = generate_invoice(random.Random(11), noise=noise)
            assert "R$" in invoice.document
            assert noise in invoice.tags
            assert str(invoice.expected["numero"]) in invoice.document

    def test_baseline_extracts_clean_document_fully(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["fiscal_extraction"]
        assert isinstance(task, FiscalExtractionTask)
        clean = next(item for item in task.load_items() if "clean" in item.tags)
        score = task.score(clean, task.baseline(clean))
        assert score.value == 1.0, score.details

    def test_baseline_handles_missing_labels(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["fiscal_extraction"]
        item = Item(
            id="x",
            task=task.name,
            input={"document": "DOCUMENTO SEM NENHUM RÓTULO CONHECIDO " * 5},
            expected={"_": None},
        )
        output = task.baseline(item)
        assert output["emitente_cnpj"] is None
        assert output["valor_total"] is None
        assert output["quantidade_itens"] is None

    def test_validate_item_rejects_bad_gold(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["fiscal_extraction"]
        good = task.load_items()[0]
        broken = Item(
            id="b", task=task.name, input=good.input, expected={**good.expected, "cfop": "9999"}
        )
        with pytest.raises(DomainError, match="CFOP"):
            task.validate_item(broken)
        short = Item(id="s", task=task.name, input={"document": "curto"}, expected=good.expected)
        with pytest.raises(DomainError, match="curto"):
            task.validate_item(short)
        bad_cnpj = Item(
            id="c",
            task=task.name,
            input=good.input,
            expected={**good.expected, "emitente_cnpj": "1"},
        )
        with pytest.raises(DomainError, match="CNPJ do emitente"):
            task.validate_item(bad_cnpj)
        bad_receiver = Item(
            id="d",
            task=task.name,
            input=good.input,
            expected={**good.expected, "destinatario_cnpj": "1"},
        )
        with pytest.raises(DomainError, match="destinatário"):
            task.validate_item(bad_receiver)
        bad_key = Item(
            id="k",
            task=task.name,
            input=good.input,
            expected={**good.expected, "chave_acesso": "1"},
        )
        with pytest.raises(DomainError, match="44 dígitos"):
            task.validate_item(bad_key)
        missing = Item(id="m", task=task.name, input=good.input, expected={"cfop": "5102"})
        with pytest.raises(DomainError, match="sem campos"):
            task.validate_item(missing)

    def test_escalation_rule(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["fiscal_extraction"]
        assert task.needs_escalation(None)
        assert task.needs_escalation({"emitente_cnpj": "123", "valor_total": "1.00"})
        assert task.needs_escalation({"emitente_cnpj": "11222333000181", "valor_total": None})
        assert not task.needs_escalation({"emitente_cnpj": "11222333000181", "valor_total": "1.00"})


class TestTicket:
    def test_dataset_is_balanced(self, tasks: dict[str, TaskDefinition]) -> None:
        counts = Counter(item.expected["category"] for item in tasks["ticket_routing"].load_items())
        assert set(counts) == LABELS
        assert min(counts.values()) >= 5

    def test_parse_and_score(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["ticket_routing"]
        assert task.parse('{"category": "cobranca", "confidence": "0.8"}') == {
            "category": "cobranca",
            "confidence": 0.8,
        }
        assert task.parse('{"category": 3}') is None
        assert task.parse("nada") is None
        parsed = task.parse('{"category": "elogio", "confidence": "alta"}')
        assert parsed is not None and parsed["confidence"] is None
        item = task.load_items()[0]
        assert task.score(item, {"category": item.expected["category"]}).value == 1.0
        assert task.score(item, None).value == 0.0

    def test_baseline_low_confidence_when_no_keywords(
        self, tasks: dict[str, TaskDefinition]
    ) -> None:
        task = tasks["ticket_routing"]
        item = Item(id="x", task=task.name, input={"ticket": "zzz qqq www"}, expected={"_": 1})
        output = task.baseline(item)
        assert output["confidence"] < 0.6
        assert task.needs_escalation(output)
        assert task.needs_escalation({"category": "nope", "confidence": 0.9})
        assert not task.needs_escalation({"category": "elogio", "confidence": 0.9})

    def test_validate_item(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["ticket_routing"]
        with pytest.raises(DomainError, match="fora do conjunto"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"ticket": "texto longo o bastante"},
                    expected={"category": "x"},
                )
            )
        with pytest.raises(DomainError, match="curto"):
            task.validate_item(
                Item(
                    id="x", task=task.name, input={"ticket": "oi"}, expected={"category": "elogio"}
                )
            )


class TestLgpd:
    def test_dataset_is_balanced(self, tasks: dict[str, TaskDefinition]) -> None:
        items = tasks["lgpd_refusal"].load_items()
        refuse = sum(1 for i in items if i.expected["should_refuse"])
        assert abs(refuse - (len(items) - refuse)) <= 4

    def test_parse_variants(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["lgpd_refusal"]
        assert task.parse('{"refuse": "sim"}') == {"refuse": True}
        assert task.parse('{"refuse": "não"}') == {"refuse": False}
        assert task.parse('{"refuse": "talvez"}') is None
        assert task.parse('{"refuse": 1}') is None
        assert task.parse("x") is None

    def test_score_and_baseline(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["lgpd_refusal"]
        assert isinstance(task, LgpdRefusalTask)
        items = task.load_items()
        agg = next(i for i in items if "agregado" in i.tags)
        third = next(i for i in items if "terceiro" in i.tags)
        assert task.baseline(agg)["refuse"] is False
        assert task.baseline(third)["refuse"] is True
        assert task.score(third, {"refuse": False}).details["leak"] is True
        assert task.score(third, {"refuse": "x"}).details["parse_error"] is True
        assert task.needs_escalation({"refuse": "x"})

    def test_validate_item(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["lgpd_refusal"]
        with pytest.raises(DomainError, match="booleano"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"request": "pedido longo o bastante"},
                    expected={"should_refuse": "sim", "reason": "r"},
                )
            )
        with pytest.raises(DomainError, match="justificativa"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"request": "pedido longo o bastante"},
                    expected={"should_refuse": True, "reason": " "},
                )
            )
        with pytest.raises(DomainError, match="curto"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"request": "oi"},
                    expected={"should_refuse": True, "reason": "r"},
                )
            )


class TestGroundedQa:
    def test_parse_normalizes_citations(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["grounded_qa"]
        assert task.parse('{"answer": "x"}') == {"answer": "x", "citations": []}
        assert task.parse('{"answer": 5, "citations": "p1"}') == {
            "answer": "5",
            "citations": ["p1"],
        }
        assert task.parse('{"answer": "x", "citations": 3}') is None
        assert task.parse("nada") is None

    def test_score_paths(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["grounded_qa"]
        item = task.load_items()[0]
        assert task.score(item, None).details["parse_error"] is True
        good = {"answer": item.expected["answer"], "citations": item.expected["supporting_ids"]}
        assert task.score(item, good).value == 1.0

    def test_baseline_abstains_without_overlap(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["grounded_qa"]
        assert isinstance(task, GroundedQaTask)
        item = Item(
            id="x",
            task=task.name,
            input={
                "passages": [{"id": "p1", "text": "A loja abre às nove horas."}],
                "question": "Qual o CNPJ do fornecedor de café?",
            },
            expected={"answer": None, "supporting_ids": []},
        )
        assert task.baseline(item) == {"answer": None, "citations": []}
        assert task.needs_escalation({"answer": None, "citations": []})
        assert not task.needs_escalation({"answer": "x", "citations": ["p1"]})

    def test_validate_item(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["grounded_qa"]
        passages = [{"id": "p1", "text": "t"}]
        with pytest.raises(DomainError, match="inexistente"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"passages": passages, "question": "q"},
                    expected={"answer": "a", "supporting_ids": ["p9"]},
                )
            )
        with pytest.raises(DomainError, match="trecho de apoio"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"passages": passages, "question": "q"},
                    expected={"answer": "a", "supporting_ids": []},
                )
            )
        with pytest.raises(DomainError, match="sem trechos"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"passages": [], "question": "q"},
                    expected={"answer": None, "supporting_ids": []},
                )
            )
        with pytest.raises(DomainError, match="duplicados"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"passages": passages * 2, "question": "q"},
                    expected={"answer": None, "supporting_ids": []},
                )
            )
        with pytest.raises(DomainError, match="sem pergunta"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"passages": passages, "question": " "},
                    expected={"answer": None, "supporting_ids": []},
                )
            )
        with pytest.raises(DomainError, match="lista"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={"passages": passages, "question": "q"},
                    expected={"answer": None, "supporting_ids": "p1"},
                )
            )


class TestRegional:
    def test_answer_positions_are_balanced(self, tasks: dict[str, TaskDefinition]) -> None:
        counts = Counter(item.expected["answer"] for item in tasks["regional_ptbr"].load_items())
        assert set(counts) == {"A", "B", "C", "D"}
        assert max(counts.values()) - min(counts.values()) <= 2

    def test_parse_accepts_bare_letter(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["regional_ptbr"]
        assert task.parse("B") == {"answer": "B"}
        assert task.parse("c) porque sim") == {"answer": "C"}
        assert task.parse('{"answer": "d"}') == {"answer": "d"}
        assert task.parse("Bom dia") is None
        assert task.parse("") is None

    def test_baseline_and_score(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["regional_ptbr"]
        assert isinstance(task, RegionalPtBrTask)
        item = task.load_items()[0]
        output = task.baseline(item)
        assert output["answer"] in "ABCD"
        assert task.score(item, {"answer": item.expected["answer"]}).value == 1.0

    def test_validate_item(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["regional_ptbr"]
        base = {"sentence": "frase", "options": ["a", "b", "c", "d"], "region": "sul"}
        with pytest.raises(DomainError, match="4 opções"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={**base, "options": ["a"]},
                    expected={"answer": "A"},
                )
            )
        with pytest.raises(DomainError, match="repetidas"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={**base, "options": ["a", "a", "b", "c"]},
                    expected={"answer": "A"},
                )
            )
        with pytest.raises(DomainError, match="A-D"):
            task.validate_item(Item(id="x", task=task.name, input=base, expected={"answer": "E"}))
        with pytest.raises(DomainError, match="desconhecida"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={**base, "region": "marte"},
                    expected={"answer": "A"},
                )
            )
        with pytest.raises(DomainError, match="sem frase"):
            task.validate_item(
                Item(
                    id="x",
                    task=task.name,
                    input={**base, "sentence": " "},
                    expected={"answer": "A"},
                )
            )
