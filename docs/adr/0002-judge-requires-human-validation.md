# ADR 0002: Juiz automático só entra com kappa medido

Status: aceito

## Contexto

Usar um modelo para pontuar outro é conveniente para texto livre, e é onde a
maioria dos benchmarks esconde o erro. Um juiz não validado transfere o viés
do juiz para o ranking sem que ninguém perceba.

## Decisão

Toda tarefa publicada usa pontuador determinístico. Um juiz automático só
pode contribuir pontuação depois de `ptbr-benchmark judge-validate` medir kappa de
Cohen contra uma amostra anotada por humano (mínimo 30 itens) e obter pelo
menos 0,6. O resultado é gravado em `results/judge_validation/<tarefa>.json`
e impresso no relatório. Sem esse arquivo, a pontuação do juiz não é usada.

## Consequências

- As cinco tarefas atuais foram desenhadas para não precisar de juiz:
  extração estruturada, classificação, decisão binária, resposta curta com
  verificação de tokens, múltipla escolha.
- Adicionar tarefa de texto livre exige anotar 30 itens antes de publicar
  qualquer número. Isso é custo real e é intencional.
- O relatório sempre declara se algum número vem de juiz e com que kappa.
