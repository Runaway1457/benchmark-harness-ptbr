# Resultados

Harness `ptbr-benchmark 0.2.0`. Preços de referência em 2026-09-15. Rodadas concluídas até 2026-09-21 17:05 UTC.

Toda métrica principal vem com intervalo de confiança de 95% por bootstrap sobre famílias semânticas. Diferenças de prompt usam bootstrap pareado do delta nas mesmas famílias. Custo marcado com `~` é estimado a partir de contagem de caracteres, porque o provedor não devolveu uso de tokens.

> **Estado: calibração do harness.** Este snapshot contém somente o baseline determinístico. Ele valida o pipeline e não sustenta comparação entre fornecedores.

### Portões de calibração

| Gate | Estado | Evidência |
|---|:---:|---|
| 750 itens públicos | passou | 750 itens em 5 tarefas |
| Controle baseline concluído | passou | 5/5 tarefas |
| Duas variantes de prompt no baseline | passou | 2 variantes de prompt |
| Cada prompt baseline cobre todas as tarefas | passou | 2/2 configurações completas |
| Três observações baseline por item | passou | mínimo exigido: 3 |
| Taxa de erro do baseline em até 2% | passou | máximo observado: 0.0% |

## Fronteira de Pareto

Qualidade média entre tarefas, custo médio por item e p95 de latência.

| Configuração | Qualidade | Custo por item | p95 (ms) | Fronteira |
|---|---:|---:|---:|:---:|
| baseline-rules / minimal | 64.6% | $0.00000 | 6 | sim |
| baseline-rules / optimized | 64.6% | $0.00000 | 6 | sim |

## fiscal_extraction

Extração de campos estruturados de DANFE em texto.

| Modelo / prompt | Qualidade [IC 95%] | Custo por item | p50 (ms) | p95 (ms) | Divergência entre repetições | Itens | Erros |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-rules / minimal | 96.6% [95.6%, 97.7%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |
| baseline-rules / optimized | 96.6% [95.6%, 97.7%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |

Acurácia por campo:

| Campo | baseline-rules / minimal | baseline-rules / optimized |
|---|---:|---:|
| cfop | 100.0% | 100.0% |
| chave_acesso | 100.0% | 100.0% |
| data_emissao | 100.0% | 100.0% |
| destinatario_cnpj | 88.0% | 88.0% |
| destinatario_razao_social | 90.0% | 90.0% |
| emitente_cnpj | 88.0% | 88.0% |
| emitente_razao_social | 92.7% | 92.7% |
| emitente_uf | 100.0% | 100.0% |
| natureza_operacao | 100.0% | 100.0% |
| numero | 100.0% | 100.0% |
| quantidade_itens | 100.0% | 100.0% |
| serie | 100.0% | 100.0% |
| valor_produtos | 100.0% | 100.0% |
| valor_total | 100.0% | 100.0% |

| Modelo / prompt | Documento 100% correto | Erro de parse |
|---|---:|---:|
| baseline-rules / minimal | 73.3% | 0.0% |
| baseline-rules / optimized | 73.3% | 0.0% |

## ticket_routing

Classificação de ticket de suporte em oito categorias.

| Modelo / prompt | Qualidade [IC 95%] | Custo por item | p50 (ms) | p95 (ms) | Divergência entre repetições | Itens | Erros |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-rules / minimal | 77.3% [65.6%, 86.7%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |
| baseline-rules / optimized | 77.3% [65.6%, 86.7%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |

| Modelo / prompt | F1 macro | Acurácia | Rótulo inválido |
|---|---:|---:|---:|
| baseline-rules / minimal | 77.3% | 80.0% | 0.0% |
| baseline-rules / optimized | 77.3% | 80.0% | 0.0% |

## lgpd_refusal

Recusa correta de pedidos que violariam a LGPD.

| Modelo / prompt | Qualidade [IC 95%] | Custo por item | p50 (ms) | p95 (ms) | Divergência entre repetições | Itens | Erros |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-rules / minimal | 72.9% [60.4%, 85.4%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |
| baseline-rules / optimized | 72.9% [60.4%, 85.4%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |

| Modelo / prompt | Vazamento (respondeu quando devia recusar) | Recusa indevida |
|---|---:|---:|
| baseline-rules / minimal | 22.0% | 4.0% |
| baseline-rules / optimized | 22.0% | 4.0% |

## grounded_qa

Resposta a pergunta com citação obrigatória de trecho.

| Modelo / prompt | Qualidade [IC 95%] | Custo por item | p50 (ms) | p95 (ms) | Divergência entre repetições | Itens | Erros |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-rules / minimal | 43.7% [31.9%, 55.7%] | $0.00000 | 0 | 6 | 0.0% | 150 | 0.0% |
| baseline-rules / optimized | 43.7% [31.9%, 55.7%] | $0.00000 | 0 | 6 | 0.0% | 150 | 0.0% |

| Modelo / prompt | Citação inventada | Resposta inventada | Erro de contrato |
|---|---:|---:|---:|
| baseline-rules / minimal | 0.0% | 18.7% | 0.0% |
| baseline-rules / optimized | 0.0% | 18.7% | 0.0% |

## regional_ptbr

Interpretação de expressão regional em múltipla escolha.

| Modelo / prompt | Qualidade [IC 95%] | Custo por item | p50 (ms) | p95 (ms) | Divergência entre repetições | Itens | Erros |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-rules / minimal | 32.4% [20.9%, 44.4%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |
| baseline-rules / optimized | 32.4% [20.9%, 44.4%] | $0.00000 | 0 | 0 | 0.0% | 150 | 0.0% |

| Modelo / prompt | Resposta fora do formato |
|---|---:|
| baseline-rules / minimal | 0.0% |
| baseline-rules / optimized | 0.0% |

## Sensibilidade a prompt

Mesma tarefa, mesmo modelo, prompts diferentes. O IC 95% é calculado sobre o delta pareado por família semântica; `significativo` quando esse intervalo exclui zero.

| Tarefa | Modelo | Prompt A | Prompt B | Qualidade A | Qualidade B | Delta | IC 95% do delta | Significativo |
|---|---|---|---|---:|---:|---:|---:|:---:|
| fiscal_extraction | baseline-rules | minimal | optimized | 96.6% | 96.6% | +0.0 pp | [+0.0, +0.0] pp | não |
| grounded_qa | baseline-rules | minimal | optimized | 43.7% | 43.7% | +0.0 pp | [+0.0, +0.0] pp | não |
| lgpd_refusal | baseline-rules | minimal | optimized | 72.9% | 72.9% | +0.0 pp | [+0.0, +0.0] pp | não |
| regional_ptbr | baseline-rules | minimal | optimized | 32.4% | 32.4% | +0.0 pp | [+0.0, +0.0] pp | não |
| ticket_routing | baseline-rules | minimal | optimized | 77.3% | 77.3% | +0.0 pp | [+0.0, +0.0] pp | não |

## Validação de juiz

Nenhum juiz automático foi validado contra anotação humana nesta publicação. Todas as pontuações acima vêm de pontuadores determinísticos.

## Datasets

| Tarefa | Itens públicos | Famílias semânticas | Hash do dataset |
|---|---:|---:|---|
| fiscal_extraction | 150 | 150 | `a208609f1afd12d5` |
| ticket_routing | 150 | 48 | `857490a078651162` |
| lgpd_refusal | 150 | 48 | `39e93b51b12c665b` |
| grounded_qa | 150 | 42 | `c39b7af883cb6ddc` |
| regional_ptbr | 150 | 51 | `b06a09ec3f061173` |

O hash muda quando qualquer item muda. Comparar resultados entre publicações exige o mesmo hash.
