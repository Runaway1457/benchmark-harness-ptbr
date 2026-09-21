# regional_ptbr

Interpretação de expressão coloquial ou regional em português brasileiro, em múltipla escolha.

## Entrada

`input.sentence` (frase com a expressão), `input.options` (quatro interpretações), `input.region`.

## Regiões

`nordeste`, `sul`, `norte`, `sudeste_interior`, `centro_oeste`, `sudeste_capital`. 51 itens.

## Saída esperada

`{"answer": "<A, B, C ou D>"}`. O parser também aceita a letra sozinha.

## Pontuação

Acerto exato. A posição da resposta correta foi embaralhada com seed fixa para ficar balanceada (13/13/12/13); "sempre B" fica perto de 25%.

## Baseline

Escolhe a opção com maior sobreposição lexical com a frase. Fica um pouco acima do acaso.

## Limitação

Curadoria de uma pessoa, a partir de conhecimento próprio. A mesma expressão pode ter sentido diferente em outra cidade da mesma região. Contribuições de falantes das regiões são bem-vindas.
