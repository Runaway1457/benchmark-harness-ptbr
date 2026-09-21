# ADR 0004: Holdout existe, mas nunca é versionado

Status: aceito

## Contexto

Um dataset público em repositório aberto acaba em corpus de treino. Depois
disso, a pontuação mede memorização, não capacidade. A alternativa de manter
todo o dataset privado impede reprodução e revisão.

## Decisão

O dataset público fica no repositório e é o que qualquer pessoa pode rodar. O
harness suporta `--split holdout` lendo `tasks/<tarefa>/holdout.jsonl`, que
está no `.gitignore`. Para tarefas com gerador, `ptbr-benchmark datasets holdout`
produz um holdout local com outra seed. Para tarefas curadas, o holdout é
mantido fora do repositório. A diferença entre público e holdout é a
estimativa de contaminação publicada.

## Consequências

- Quem reproduz o benchmark reproduz o split público. O holdout serve para
  quem publica.
- Um teste de arquitetura falha se algum `holdout.jsonl` for versionado por
  engano; `holdout.example.jsonl` mostra o formato.
- O manifesto de cada rodada grava o split usado, então relatório nunca
  mistura os dois sem dizer.
