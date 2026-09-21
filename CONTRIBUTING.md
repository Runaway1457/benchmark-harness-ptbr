# Contribuindo

## Ambiente

```bash
uv sync --extra dev
make check
```

`make check` roda Ruff, MyPy em modo estrito, Bandit, auditoria de
dependências e pytest com cobertura branch-aware mínima de 85%. Pull request
que não passa no gate não é revisado.

## Regras do repositório

- Todo módulo em `ptbr_benchmark/` precisa ser importado por outro módulo ou ser
  ponto de entrada. Há teste para isso (`tests/test_architecture.py`).
- `ptbr_benchmark/domain/` não importa infraestrutura. `ptbr_benchmark/tasks/` não importa
  `runner` nem `report`.
- Todo comando citado no README precisa existir na CLI.
- Nenhum `holdout.jsonl` é versionado.
- Nenhum número no relatório sem intervalo de confiança.
- Variantes de superfície compartilham o ID de família antes de `--` e não
  contam como amostras independentes.
- Preço desconhecido falha fechado; nunca publique custo silenciosamente zero.
- Baseline é controle de calibração, não modelo concorrente.

## Adicionar itens a um dataset

1. Adicione uma família semântica ou ajuste o gerador de variantes. Use
   `<familia>--<variante>` somente quando o gabarito for exatamente o mesmo.
2. `uv run ptbr-benchmark validate --tasks <tarefa>`.
3. Se for `regional_ptbr`, mantenha as posições de resposta balanceadas.
4. Abra o PR com o novo hash do dataset na descrição. Resultados antigos
   deixam de ser comparáveis; diga isso.
5. Se o gabarito depender de julgamento humano, registre autor, revisão e
   adjudicação; validação estrutural não equivale a dupla anotação.

## Adicionar uma tarefa

1. Crie `ptbr_benchmark/tasks/<nome>.py` herdando `TaskDefinition` e implemente
   `validate_item`, `prompt_variables`, `parse`, `score`, `baseline` e, se
   fizer sentido, `needs_escalation`.
2. Registre em `ptbr_benchmark/tasks/registry.py`.
3. Crie `tasks/<nome>/` com `dataset.jsonl`, `prompts/minimal.md`,
   `prompts/optimized.md` e `README.md`.
4. Se a pontuação exigir juiz, leia `docs/adr/0002` antes: você vai precisar
   de 30 itens anotados por humano.
5. Adicione testes em `tests/test_tasks.py` cobrindo parse, score, baseline
   e validação de item.

## Adicionar um provedor

1. Crie a classe em `ptbr_benchmark/providers/http.py` com `name` e `complete()`.
2. Classifique erros em retryable ou não via `ProviderError`.
3. Adicione o modelo em `ptbr_benchmark/providers/pricing.json` com a data.
4. Teste com `httpx.MockTransport` em `tests/test_providers.py`.
5. Registre a opção em `ptbr_benchmark/cli.py`.

## Estilo

Português brasileiro em documentação, mensagens de erro e comentários.
Nomes de código em inglês. Comentário explica por quê, não o quê.
