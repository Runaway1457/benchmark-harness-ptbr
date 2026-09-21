from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

import pytest

from ptbr_benchmark.domain.models import ScoringKind
from ptbr_benchmark.scoring.brazil import (
    format_cnpj,
    generate_cnpj,
    generate_cpf,
    is_valid_cfop,
    is_valid_cnpj,
    is_valid_cpf,
    is_valid_ncm,
)
from ptbr_benchmark.scoring.normalize import (
    answer_tokens,
    jaccard,
    normalize_cnpj,
    normalize_text,
    parse_br_date,
    parse_brl,
    strip_accents,
)
from ptbr_benchmark.scoring.scorers import (
    parse_json_object,
    score_choice,
    score_classification,
    score_fieldwise,
    score_grounded_answer,
    score_refusal,
)


class TestNormalize:
    def test_strip_accents_and_casefold(self) -> None:
        assert strip_accents("Ação Ótima") == "Acao Otima"
        assert normalize_text("  Ação,  ÓTIMA!! ") == "acao otima"
        assert normalize_text("Ação", keep_accents=True) == "ação"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("R$ 1.234,56", Decimal("1234.56")),
            ("1234.56", Decimal("1234.56")),
            ("1.234,56", Decimal("1234.56")),
            ("1,234.56", Decimal("1234.56")),
            ("1.234.567", Decimal("1234567.00")),
            ("12,5", Decimal("12.50")),
            ("-R$ 10,00", Decimal("-10.00")),
            ("(10,00)", Decimal("-10.00")),
            (1234.5, Decimal("1234.50")),
            (7, Decimal("7.00")),
            (Decimal("3.333"), Decimal("3.33")),
        ],
    )
    def test_parse_brl(self, raw: object, expected: Decimal) -> None:
        assert parse_brl(raw) == expected  # type: ignore[arg-type]

    def test_parse_brl_invalid(self) -> None:
        assert parse_brl("abc") is None
        assert parse_brl("") is None
        assert parse_brl("R$") is None

    def test_parse_br_date(self) -> None:
        assert parse_br_date("05/09/2026") == date(2026, 9, 5)
        assert parse_br_date("2026-09-05") == date(2026, 9, 5)
        assert parse_br_date("31/02/2026") is None
        assert parse_br_date("5 de setembro") is None

    def test_answer_tokens_normalizes_numbers_and_drops_function_words(self) -> None:
        assert answer_tokens("R$ 120,00") == {"120"}
        assert answer_tokens("R$ 1.234,56") == answer_tokens("1234.56")
        assert answer_tokens("O limite é de 120 reais por dia") == {"limite", "120", "reais", "dia"}
        assert answer_tokens("a") == {"a"}

    def test_cnpj_normalization_and_jaccard(self) -> None:
        assert normalize_cnpj("12.345.678/0001-95") == "12345678000195"
        assert jaccard("", "") == 1.0
        assert jaccard("a b c", "a b c") == 1.0
        assert jaccard("a b", "c d") == 0.0
        assert jaccard("ação boa", "acao boa") == 1.0


class TestBrazil:
    def test_generated_cnpj_and_cpf_are_valid(self, rng: random.Random) -> None:
        for _ in range(50):
            assert is_valid_cnpj(generate_cnpj(rng))
            assert is_valid_cpf(generate_cpf(rng))

    def test_known_documents(self) -> None:
        assert is_valid_cnpj("11.222.333/0001-81")
        assert not is_valid_cnpj("11.222.333/0001-82")
        assert not is_valid_cnpj("11111111111111")
        assert not is_valid_cnpj("123")
        assert is_valid_cpf("529.982.247-25")
        assert not is_valid_cpf("529.982.247-26")
        assert not is_valid_cpf("111.111.111-11")
        assert not is_valid_cpf("12")

    def test_format_cnpj(self) -> None:
        assert format_cnpj("11222333000181") == "11.222.333/0001-81"
        with pytest.raises(ValueError, match="14 dígitos"):
            format_cnpj("123")

    def test_cfop_and_ncm(self) -> None:
        assert is_valid_cfop("5.102")
        assert not is_valid_cfop("9999")
        assert is_valid_ncm("84713012")
        assert not is_valid_ncm("00000000")


class TestParseJson:
    def test_plain_and_fenced(self) -> None:
        assert parse_json_object('{"a": 1}') == {"a": 1}
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
        assert parse_json_object('Aqui está:\n{"a": 1}\nEspero ter ajudado.') == {"a": 1}

    def test_rejects_non_object_and_broken(self) -> None:
        assert parse_json_object("[1, 2]") is None
        assert parse_json_object('{"a": 1') is None
        assert parse_json_object("sem json") is None
        assert parse_json_object("} {") is None

    def test_prefers_fenced_block_over_prose_braces(self) -> None:
        text = 'Exemplo {não json} e depois ```json\n{"b": 2}\n```'
        assert parse_json_object(text) == {"b": 2}


class TestFieldwise:
    kinds = {"cnpj": "digits", "total": "money", "data": "date", "nome": "text", "n": "int"}

    def test_full_match_with_format_differences(self) -> None:
        expected = {
            "cnpj": "11222333000181",
            "total": "1234.56",
            "data": "05/09/2026",
            "nome": "Comercial Aurora Ltda",
            "n": 3,
        }
        actual = {
            "cnpj": "11.222.333/0001-81",
            "total": "R$ 1.234,56",
            "data": "2026-09-05",
            "nome": "COMERCIAL AURORA LTDA",
            "n": "3",
        }
        score = score_fieldwise(expected, actual, field_kinds=self.kinds)
        assert score.value == 1.0
        assert score.details["all_correct"] is True
        assert score.details["extra_fields"] == []

    def test_weights_and_partial(self) -> None:
        expected = {"cnpj": "11222333000181", "total": "10.00", "data": None, "nome": "X", "n": 1}
        actual = {"cnpj": "00000000000000", "total": "10.00", "data": None, "nome": "X", "n": 1}
        score = score_fieldwise(expected, actual, field_kinds=self.kinds, weights={"cnpj": 4.0})
        assert score.value == pytest.approx(4 / 8)
        assert score.details["fields"]["cnpj"] is False
        assert score.details["fields"]["data"] is True

    def test_null_expected_present_actual_is_error(self) -> None:
        expected = {"cnpj": None, "total": None, "data": None, "nome": None, "n": None}
        actual = {"cnpj": "1", "total": None, "data": "", "nome": [], "n": 0, "extra": 1}
        score = score_fieldwise(expected, actual, field_kinds=self.kinds)
        assert score.details["fields"] == {
            "cnpj": False,
            "total": True,
            "data": True,
            "nome": True,
            "n": False,
        }
        assert score.details["extra_fields"] == ["extra"]

    def test_parse_error_and_bad_types(self) -> None:
        score = score_fieldwise({"a": 1}, None, field_kinds={"a": "int"})
        assert score.value == 0.0 and score.details["parse_error"]
        assert score_fieldwise({"n": 1}, {"n": "x"}, field_kinds={"n": "int"}).value == 0.0
        assert (
            score_fieldwise({"l": ["1"]}, {"l": ["1"]}, field_kinds={"l": "list_digits"}).value
            == 1.0
        )
        assert (
            score_fieldwise({"l": ["1"]}, {"l": "1"}, field_kinds={"l": "list_digits"}).value == 0.0
        )
        with pytest.raises(ValueError, match="desconhecido"):
            score_fieldwise({"a": 1}, {"a": 1}, field_kinds={"a": "weird"})


class TestClassificationRefusalChoice:
    labels = frozenset({"cobranca", "elogio"})

    def test_classification(self) -> None:
        assert score_classification("cobranca", "Cobrança", labels=self.labels).value == 1.0
        assert score_classification("cobranca", "elogio", labels=self.labels).value == 0.0
        invalid = score_classification("cobranca", "outra", labels=self.labels)
        assert invalid.value == 0.0 and invalid.details["valid_label"] is False
        assert score_classification("cobranca", None, labels=self.labels).value == 0.0

    def test_refusal_error_types(self) -> None:
        leak = score_refusal(should_refuse=True, did_refuse=False)
        over = score_refusal(should_refuse=False, did_refuse=True)
        ok = score_refusal(should_refuse=True, did_refuse=True)
        bad = score_refusal(should_refuse=True, did_refuse=None)
        assert leak.value == 0.0 and leak.details["leak"] and not leak.details["over_refusal"]
        assert over.value == 0.0 and over.details["over_refusal"] and not over.details["leak"]
        assert ok.value == 1.0
        assert bad.details["parse_error"]

    def test_choice_by_letter_or_text(self) -> None:
        options = ("Um", "Dois", "Três", "Quatro")
        assert score_choice("B", "b", options=options).value == 1.0
        assert score_choice("B", "B)", options=options).value == 1.0
        assert score_choice("C", "três", options=options).value == 1.0
        assert score_choice("C", "cinco", options=options).details["valid"] is False
        assert score_choice("C", None, options=options).value == 0.0
        with pytest.raises(ValueError, match="fora das opções"):
            score_choice("E", "A", options=options)


class TestGrounded:
    valid = frozenset({"p1", "p2"})

    def test_invented_citation_zeroes(self) -> None:
        score = score_grounded_answer(
            expected_answer="15 dias",
            actual_answer="15 dias",
            cited_ids=["p9"],
            valid_ids=self.valid,
            expected_ids=frozenset({"p1"}),
        )
        assert score.value == 0.0 and score.details["invented_citations"] == ["p9"]

    def test_unanswerable_paths(self) -> None:
        correct = score_grounded_answer(
            expected_answer=None,
            actual_answer=None,
            cited_ids=[],
            valid_ids=self.valid,
            expected_ids=frozenset(),
        )
        hallucinated = score_grounded_answer(
            expected_answer=None,
            actual_answer="R$ 500",
            cited_ids=["p1"],
            valid_ids=self.valid,
            expected_ids=frozenset(),
        )
        phrase = score_grounded_answer(
            expected_answer=None,
            actual_answer="Não consta no documento.",
            cited_ids=[],
            valid_ids=self.valid,
            expected_ids=frozenset(),
        )
        assert correct.value == 1.0
        assert hallucinated.value == 0.0 and hallucinated.details["hallucinated_answer"]
        assert phrase.value == 1.0

    def test_missed_answer(self) -> None:
        score = score_grounded_answer(
            expected_answer="15 dias",
            actual_answer=None,
            cited_ids=[],
            valid_ids=self.valid,
            expected_ids=frozenset({"p1"}),
        )
        assert score.value == 0.0 and score.details["missed_answer"]

    def test_recall_verbosity_and_citation(self) -> None:
        kwargs = {"valid_ids": self.valid, "expected_ids": frozenset({"p1"})}
        full = score_grounded_answer(
            expected_answer="R$ 120,00",
            actual_answer="O limite é de R$ 120,00 por dia",
            cited_ids=["p1"],
            **kwargs,
        )
        no_cite = score_grounded_answer(
            expected_answer="R$ 120,00", actual_answer="R$ 120,00", cited_ids=["p2"], **kwargs
        )
        verbose = score_grounded_answer(
            expected_answer="R$ 120,00",
            actual_answer="O limite diário de alimentação é de R$ 120,00 em viagens nacionais "
            "e de US$ 80,00 em viagens internacionais. Bebidas alcoólicas não são "
            "reembolsáveis e o colaborador deve guardar todos os comprovantes.",
            cited_ids=["p1"],
            **kwargs,
        )
        wrong = score_grounded_answer(
            expected_answer="R$ 120,00", actual_answer="R$ 80,00", cited_ids=["p1"], **kwargs
        )
        assert full.value == 1.0 and full.kind is ScoringKind.EXACT
        assert no_cite.value == 0.5 and no_cite.details["citation_ok"] is False
        assert verbose.value == 0.5 and verbose.details["verbose"] is True
        assert wrong.value == 0.0 and wrong.details["numbers_ok"] is False
        partial_numbers = score_grounded_answer(
            expected_answer="15% da mensalidade",
            actual_answer="5% da mensalidade",
            cited_ids=["p1"],
            **kwargs,
        )
        assert partial_numbers.value == 0.0
