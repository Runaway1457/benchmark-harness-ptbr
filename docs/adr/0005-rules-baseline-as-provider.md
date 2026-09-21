# ADR 0005: A solução de referência por regras é um provedor

Status: aceito

## Contexto

Um benchmark sem piso não diz nada: 80% pode ser excelente ou pode ser o que
uma expressão regular faz. Além disso, um pipeline que só roda com chave de
API paga não pode ter teste de integração barato nem demonstração sem custo.

## Decisão

Cada tarefa implementa `baseline(item)`, uma solução determinística por
regras. `BaselineProvider` expõe isso pela mesma interface `Provider` que os
modelos usam, devolvendo JSON como texto. O resultado passa pelo mesmo parser
e pelo mesmo pontuador.

## Consequências

- O relatório sempre tem o piso ao lado dos modelos, na mesma escala.
- O pipeline inteiro roda sem rede: `make run` é um teste de integração
  completo em segundos.
- A baseline tem fraquezas conhecidas de propósito (blocos fora de ordem na
  nota fiscal, ausência de palavra-chave no ticket). Elas mostram onde um
  modelo precisa agregar valor para justificar o custo.
- Custo da baseline é zero e latência é desprezível, o que a coloca sempre
  na fronteira de Pareto. Isso é correto: se um modelo não supera a baseline
  em qualidade, não há por que pagar por ele.
