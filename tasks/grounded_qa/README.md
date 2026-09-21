# grounded_qa

Responder pergunta usando exclusivamente trechos identificados de um documento interno, citando os trechos usados.

## Entrada

`input.passages`: lista de `{id, text}`. `input.question`: a pergunta.

## Saída esperada

`{"answer": "<texto ou null>", "citations": ["<id>", ...]}`.

## Pontuação

Em ordem:

1. Citação para id inexistente zera o item, independentemente da resposta.
2. Pergunta sem resposta no documento exige `answer: null`. Responder é alucinação e zera.
3. Pergunta com resposta exige recall de tokens informativos do gabarito ≥ 0,6 e presença de todo número do gabarito. Resposta correta mas prolixa (mais de 3× o gabarito), ou sem citar o trecho de apoio, vale 0,5.

## Documentos

Quatro documentos sintéticos: política de reembolso de despesas, manual de férias e ponto, contrato de prestação de serviço com SLA, instruções operacionais de loja. 42 perguntas, 8 sem resposta. Tags marcam itens que exigem dois trechos (`multi_trecho`), cálculo (`raciocinio`) ou que são armadilha plausível (`armadilha`).

## Baseline

Escolhe o trecho com maior sobreposição lexical com a pergunta e devolve o trecho inteiro. Acerta a citação com frequência e é penalizada por prolixidade; abstém quando a sobreposição é baixa.
