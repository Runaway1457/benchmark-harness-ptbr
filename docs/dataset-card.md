# Dataset card

## Resumo

O Benchmark e Harness de Avaliação PT-BR contém **750 itens públicos** distribuídos igualmente em cinco tarefas. A unidade estatística, porém, é a família semântica: são **339 famílias independentes** e 411 variantes controladas de superfície. Essa distinção é parte do contrato do benchmark e aparece no relatório.

Todo conteúdo é sintético. Nenhum registro real de cliente, pessoa, empresa ou documento foi utilizado.

| Tarefa | Itens | Famílias | Variantes | Construção |
|---|---:|---:|---:|---|
| `fiscal_extraction` | 150 | 150 | 0 | Gerador determinístico, seed 7 |
| `ticket_routing` | 150 | 48 | 102 | Cenários autorais + variantes controladas |
| `lgpd_refusal` | 150 | 48 | 102 | Cenários autorais + variantes controladas |
| `grounded_qa` | 150 | 42 | 108 | Cenários autorais + variantes controladas |
| `regional_ptbr` | 150 | 51 | 99 | Cenários autorais + variantes controladas |
| **Total** | **750** | **339** | **411** | |

O arquivo `tasks/dataset-manifest.json` registra o método, a unidade estatística e as contagens. `ptbr-benchmark validate` recalcula os totais e hashes; todo manifesto de rodada preserva o SHA-256 de cada dataset.

## Construção

### Famílias semânticas

Uma família representa um problema independente com um único gabarito. O ID base é estável. Variantes controladas usam `<id>--<variant>`, o que permite que a agregação agrupe textos correlacionados.

### Variantes controladas

O script `scripts/build_surface_variants.py` gera, de forma idempotente:

- `formal`: registro corporativo mais formal;
- `noisy`: abreviações e ruído plausível de mensagem móvel;
- `context`: enquadramento conversacional adicional.

As transformações não alteram a intenção nem o gabarito. O bootstrap amostra famílias e calcula internamente a média das variantes, evitando pseudo-replicação.

### Extração fiscal

O gerador produz DANFEs textuais com 14 campos e três condições: `clean`, `ocr` e `scrambled`. Valores mantêm consistência contábil; CNPJs têm dígitos verificadores válidos; dados são fictícios.

### Roteamento de tickets

Oito filas operacionais, incluindo casos intencionalmente ambíguos. A métrica principal é F1 macro para não esconder classes fracas atrás de acurácia agregada.

### Recusa LGPD

75 itens pedem recusa e 75 permitem atendimento. As famílias cobrem dado de terceiro, exportação em massa, dado sensível, incompatibilidade de finalidade, cruzamento de bases, obrigação legal, titular autenticado e dado agregado.

### QA com documento

Cada item contém trechos identificados, pergunta, resposta curta ou `null` e IDs de suporte. Há perguntas sem resposta, citações múltiplas e raciocínio simples.

### Português regional

Expressões de Norte, Nordeste, Centro-Oeste, Sul, interior e capitais do Sudeste. A posição da alternativa correta é balanceada. O dataset mede compreensão contextual, não classifica a origem de uma pessoa.

## Formato

Um objeto JSON por linha:

```json
{
  "id": "ticket-001--noisy",
  "input": {"ticket": "..."},
  "expected": {"category": "..."},
  "tags": ["surface_variant", "noisy"]
}
```

- `id`: único e estável;
- `input`: único conteúdo entregue ao template;
- `expected`: gabarito usado pelo scorer;
- `tags`: condições para análise estratificada;
- o split é público por padrão; `holdout.jsonl` é local e ignorado pelo Git.

## Anotação e validação

Os gabaritos curados possuem atualmente **um autor primário**. Eles passam por validação estrutural, invariantes específicas da tarefa e testes automatizados, mas isso não equivale a concordância entre anotadores.

Consequências:

- nenhum material deve alegar “dupla revisão humana” no snapshot atual;
- dupla anotação independente e adjudicação são gates antes de estudos sobre ambiguidade humana;
- qualquer juiz LLM exige amostra humana separada e kappa registrado;
- mudanças em gabarito alteram o hash e invalidam comparações com rodadas anteriores.

## Contaminação

O split público pode ser ingerido por modelos treinados depois da publicação. O harness aceita `--split holdout`. O arquivo privado nunca é versionado; apenas métricas agregadas e o hash podem ser publicados.

Comparar público e holdout é obrigatório antes de afirmar generalização futura. A tarefa fiscal oferece geração por seed independente; as demais exigem curadoria manual para evitar variantes triviais.

## Limitações

- Variantes de superfície melhoram cobertura linguística, mas não adicionam novas famílias semânticas.
- O gerador fiscal não cobre a diversidade visual completa de documentos reais.
- Expressões regionais variam dentro da mesma região e podem mudar com contexto e geração.
- O benchmark não representa todos os setores, cargos ou riscos de uma organização.
- Dados sintéticos evitam exposição de PII, mas podem subestimar ruído operacional.

## Uso pretendido

Avaliação comparativa de modelos e prompts em tarefas corporativas PT-BR antes de validação nos dados da organização. Não é dataset de treinamento e não autoriza decisão automatizada sobre pessoas.

## Licença e manutenção

Código sob Apache-2.0. Datasets sintéticos acompanham a licença do repositório. Mudanças devem seguir [CONTRIBUTING.md](../CONTRIBUTING.md) e atualizar o manifesto, hashes e resultados.
