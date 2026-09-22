"""Interface de linha de comando.

ptbr-benchmark validate                      valida todos os datasets
ptbr-benchmark run --provider baseline       executa e grava a rodada
ptbr-benchmark report                        agrega rodadas e gera docs/results.md e site/
ptbr-benchmark datasets generate-fiscal      regenera o dataset fiscal a partir da seed
ptbr-benchmark datasets holdout              gera holdout local, não versionado
ptbr-benchmark judge-validate                mede kappa do juiz contra anotação humana
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import structlog

from ptbr_benchmark import __version__
from ptbr_benchmark.config import Settings
from ptbr_benchmark.domain.models import DomainError, RunSpec, Split, utc_now
from ptbr_benchmark.providers.base import Provider, ProviderError
from ptbr_benchmark.providers.baseline import BASELINE_MODEL, BaselineProvider
from ptbr_benchmark.providers.cascade import CascadeProvider
from ptbr_benchmark.providers.http import AnthropicProvider, OpenAIProvider
from ptbr_benchmark.providers.pricing import load_pricing
from ptbr_benchmark.providers.simulation import PROFILES, SimulationProvider
from ptbr_benchmark.report.aggregate import write_run
from ptbr_benchmark.report.build import build_context, write_reports
from ptbr_benchmark.report.gates import is_real_provider
from ptbr_benchmark.runner.cache import CompletionCache
from ptbr_benchmark.runner.executor import Executor
from ptbr_benchmark.scoring.judge import LlmJudge, load_human_labels, validate_judge
from ptbr_benchmark.tasks.base import TaskDefinition
from ptbr_benchmark.tasks.fiscal_synth import generate_invoice
from ptbr_benchmark.tasks.registry import TASK_NAMES, load_tasks

log = structlog.get_logger("ptbr_benchmark.cli")
MIN_PUBLIC_ITEMS = 150


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", level=level.upper(), stream=sys.stderr)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.KeyValueRenderer(key_order=["event"]),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def build_provider(
    name: str, *, settings: Settings, tasks_by_name: Mapping[str, TaskDefinition]
) -> Provider:
    if name == "baseline":
        return BaselineProvider(tasks_by_name)
    if name == "anthropic":
        return AnthropicProvider(timeout_seconds=settings.request_timeout_seconds)
    if name == "openai":
        return OpenAIProvider(timeout_seconds=settings.request_timeout_seconds)
    if name == "simulation":
        return SimulationProvider(tasks_by_name)
    raise DomainError(
        f"provedor desconhecido: {name!r}. Use baseline, simulation, anthropic ou openai."
    )


def _parse_tasks(value: str) -> tuple[str, ...]:
    if value == "all":
        return TASK_NAMES
    return tuple(part.strip() for part in value.split(",") if part.strip())


def cmd_validate(args: argparse.Namespace, settings: Settings) -> int:
    tasks = load_tasks(settings.tasks_dir, _parse_tasks(args.tasks))
    total = 0
    for task in tasks:
        items = task.load_items(Split.PUBLIC)
        if len(items) < MIN_PUBLIC_ITEMS:
            raise DomainError(
                f"{task.name}: {len(items)} itens; publicação exige pelo menos {MIN_PUBLIC_ITEMS}"
            )
        prompts = task.load_prompts()
        for prompt in prompts.values():
            task.build_request(items[0], prompt, model="validation", seed=0)
        total += len(items)
        digest = task.dataset_hash()[:12]
        families = len({item.scenario_family for item in items})
        print(
            f"{task.name:<20} {len(items):>4} itens  {families:>3} famílias  "
            f"{len(prompts)} prompts  hash {digest}"
        )
    print(f"{'total':<20} {total:>4} itens")
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    task_names = _parse_tasks(args.tasks)
    tasks = load_tasks(settings.tasks_dir, task_names)
    tasks_by_name = {task.name: task for task in tasks}
    pricing = load_pricing()

    provider: Provider
    model = args.model
    if args.cascade_to:
        primary = build_provider(args.provider, settings=settings, tasks_by_name=tasks_by_name)
        fallback_provider_name, _, fallback_model = args.cascade_to.partition(":")
        fallback = build_provider(
            fallback_provider_name, settings=settings, tasks_by_name=tasks_by_name
        )
        if not fallback_model:
            raise DomainError("--cascade-to exige o formato provedor:modelo")
        provider = CascadeProvider(
            primary=primary,
            primary_model=model,
            fallback=fallback,
            fallback_model=fallback_model,
            tasks=tasks_by_name,
            pricing=pricing,
        )
        model = f"{model}+{fallback_model}"
    else:
        provider = build_provider(args.provider, settings=settings, tasks_by_name=tasks_by_name)
        if args.provider == "baseline":
            model = BASELINE_MODEL

    prompts_by_task = {}
    for task in tasks:
        prompts = task.load_prompts()
        if args.prompt not in prompts:
            raise DomainError(
                f"tarefa {task.name!r} não tem prompt {args.prompt!r}. "
                f"Disponíveis: {sorted(prompts)}"
            )
        prompts_by_task[task.name] = prompts[args.prompt]

    spec = RunSpec(
        tasks=task_names,
        provider=provider.name,
        model=model,
        prompt_name=args.prompt,
        repetitions=args.repetitions,
        seed=args.seed,
        split=Split(args.split),
        limit=args.limit,
    )
    cache = None if args.no_cache else CompletionCache(settings.cache_path)
    try:
        executor = Executor(
            provider=provider,
            pricing=pricing,
            cache=cache,
            max_concurrency=settings.max_concurrency,
        )
        if is_real_provider(provider.name) and not args.skip_preflight:
            first_task = tasks[0]
            first_item = first_task.load_items(Split(args.split))[0]
            request = first_task.build_request(
                first_item,
                prompts_by_task[first_task.name],
                model=spec.model,
                seed=spec.seed * 1000,
            )
            completion = executor.preflight(request)
            log.info(
                "provider.preflight.ok",
                provider=provider.name,
                model=completion.model,
                latency_ms=round(completion.latency_ms, 1),
            )
            if isinstance(provider, CascadeProvider):
                provider.reset_counters()
        result = executor.run(spec, tasks, prompts_by_task)
    finally:
        if cache is not None:
            cache.close()

    run_dir = write_run(result, settings.results_dir)
    if isinstance(provider, CascadeProvider):
        (run_dir / "cascade.json").write_text(
            json.dumps(
                {
                    "escalations": provider.escalations,
                    "total": provider.total,
                    "rate": provider.escalation_rate,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log.info("cascade.summary", escalation_rate=round(provider.escalation_rate, 4))
    print(
        f"rodada {spec.run_id} gravada em {run_dir} "
        f"({len(result.observations)} observações, ${result.total_cost_usd:.4f})"
    )
    return 0


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    tasks = load_tasks(settings.tasks_dir)
    context = build_context(
        results_dir=settings.results_dir,
        tasks=tasks,
        pricing=load_pricing(),
        seed=args.seed,
    )
    markdown_path, html_path, summary_path = write_reports(
        context, docs_dir=settings.docs_dir, site_dir=settings.site_dir
    )
    print(f"relatório: {markdown_path}\nsite: {html_path}\nresumo: {summary_path}")
    for point in context.frontier:
        print(
            f"fronteira: {point.label:<40} qualidade {point.quality * 100:5.1f}%  "
            f"custo ${point.cost_per_item_usd:.5f}"
        )
    return 0


def cmd_demo_matrix(args: argparse.Namespace, settings: Settings) -> int:
    """Gera controle positivo em diretórios fisicamente separados da matriz real."""
    demo = settings.model_copy(
        update={
            "results_dir": settings.results_dir.with_name("results-demo"),
            "docs_dir": settings.docs_dir.with_name("docs-demo"),
            "site_dir": settings.site_dir.with_name("site-demo"),
            "cache_path": settings.cache_path.with_name(".ptbr-benchmark-demo-cache.sqlite"),
        }
    )
    configurations = [("baseline", BASELINE_MODEL)] + [
        ("simulation", model) for model in sorted(PROFILES)
    ]
    for provider, model in configurations:
        for prompt in ("minimal", "optimized"):
            cmd_run(
                argparse.Namespace(
                    tasks="all",
                    provider=provider,
                    model=model,
                    prompt=prompt,
                    repetitions=args.repetitions,
                    seed=args.seed,
                    split="public",
                    limit=None,
                    no_cache=True,
                    skip_preflight=True,
                    cascade_to=None,
                ),
                demo,
            )
    return cmd_report(argparse.Namespace(seed=args.seed), demo)


def cmd_generate_fiscal(args: argparse.Namespace, settings: Settings) -> int:
    rng = random.Random(args.seed)
    target = (
        settings.tasks_dir
        / "fiscal_extraction"
        / ("holdout.jsonl" if args.holdout else "dataset.jsonl")
    )
    noise_cycle = ("clean", "clean", "ocr", "scrambled")
    with target.open("w", encoding="utf-8") as handle:
        for index in range(args.count):
            invoice = generate_invoice(rng, noise=noise_cycle[index % len(noise_cycle)])
            prefix = "fiscal-h" if args.holdout else "fiscal"
            record = {
                "id": f"{prefix}-{index + 1:04d}",
                "input": {"document": invoice.document},
                "expected": invoice.expected,
                "tags": list(invoice.tags),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"{args.count} notas gravadas em {target}")
    return 0


def cmd_holdout(args: argparse.Namespace, settings: Settings) -> int:
    """Gera holdout local para as tarefas com gerador. Tarefas curadas à mão avisam."""
    generated = 0
    for name in _parse_tasks(args.tasks):
        if name == "fiscal_extraction":
            sub = argparse.Namespace(seed=args.seed + 1, count=args.count, holdout=True)
            cmd_generate_fiscal(sub, settings)
            generated += 1
        else:
            print(
                f"{name}: holdout precisa de curadoria manual; "
                f"crie tasks/{name}/holdout.jsonl localmente"
            )
    return 0 if generated else 1


def cmd_judge_validate(args: argparse.Namespace, settings: Settings) -> int:
    tasks = load_tasks(settings.tasks_dir, (args.task,))
    task = tasks[0]
    items = {item.id: item for item in task.load_items(Split.PUBLIC)}
    provider = build_provider(args.provider, settings=settings, tasks_by_name={task.name: task})
    judge = LlmJudge(provider, model=args.model)
    validation = validate_judge(
        judge,
        task_name=task.name,
        items=items,
        human_labels=load_human_labels(Path(args.labels)),
        validated_at=utc_now().strftime("%Y-%m-%d"),
    )
    target_dir = settings.results_dir / "judge_validation"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{task.name}.json"
    target.write_text(
        json.dumps(validation.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    status = "aceito" if validation.accepted else "rejeitado"
    print(
        f"kappa {validation.kappa:.3f} ({validation.interpretation}) "
        f"em {validation.sample_size} itens: {status}"
    )
    return 0 if validation.accepted else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ptbr-benchmark",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ptbr-benchmark {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="valida datasets e prompts")
    validate.add_argument("--tasks", default="all")
    validate.set_defaults(func=cmd_validate)

    run = sub.add_parser("run", help="executa uma rodada")
    run.add_argument(
        "--provider",
        default="baseline",
        choices=("baseline", "simulation", "anthropic", "openai"),
    )
    run.add_argument("--model", default=BASELINE_MODEL)
    run.add_argument("--tasks", default="all")
    run.add_argument("--prompt", default="minimal")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--split", default="public", choices=("public", "holdout"))
    run.add_argument("--limit", type=int, default=None, help="amostra N itens por tarefa")
    run.add_argument("--no-cache", action="store_true")
    run.add_argument(
        "--skip-preflight",
        action="store_true",
        help="pula a chamada de fumaça; não recomendado para rodadas pagas",
    )
    run.add_argument(
        "--cascade-to",
        default=None,
        metavar="PROVEDOR:MODELO",
        help="escala itens duvidosos para outro modelo",
    )
    run.set_defaults(func=cmd_run)

    demo = sub.add_parser("demo-matrix", help="gera controle positivo em results-demo/")
    demo.add_argument("--repetitions", type=int, default=3)
    demo.add_argument("--seed", type=int, default=42)
    demo.set_defaults(func=cmd_demo_matrix)

    report = sub.add_parser("report", help="agrega rodadas e gera relatório e site")
    report.add_argument("--seed", type=int, default=42, help="seed do bootstrap")
    report.set_defaults(func=cmd_report)

    datasets = sub.add_parser("datasets", help="geração de datasets")
    datasets_sub = datasets.add_subparsers(dest="datasets_command", required=True)
    fiscal = datasets_sub.add_parser("generate-fiscal", help="regenera o dataset fiscal")
    fiscal.add_argument("--count", type=int, default=150)
    fiscal.add_argument("--seed", type=int, default=7)
    fiscal.add_argument("--holdout", action="store_true")
    fiscal.set_defaults(func=cmd_generate_fiscal)
    holdout = datasets_sub.add_parser("holdout", help="gera holdout local")
    holdout.add_argument("--tasks", default="all")
    holdout.add_argument("--count", type=int, default=50)
    holdout.add_argument("--seed", type=int, default=7)
    holdout.set_defaults(func=cmd_holdout)

    judge = sub.add_parser("judge-validate", help="valida juiz automático contra anotação humana")
    judge.add_argument("--task", required=True)
    judge.add_argument("--provider", default="anthropic", choices=("anthropic", "openai"))
    judge.add_argument("--model", required=True)
    judge.add_argument("--labels", required=True, help="JSONL com item_id, candidate, label")
    judge.set_defaults(func=cmd_judge_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    configure_logging(settings.log_level)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args, settings)
        return result
    except (DomainError, ProviderError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
