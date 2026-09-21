# Metodologia

Este documento descreve como os números do relatório são produzidos, o que
eles significam e o que não significam.

## Unidades de medida

A unidade atômica persistida é a **observação**: um item, uma repetição, um
modelo e um prompt. A unidade de inferência estatística é a **família
semântica**. Variantes `<id>--<variant>` compartilham a mesma intenção e não
são contadas como evidência independente. Toda estatística é derivada de observações gravadas em
`results/<run_id>/observations.jsonl` (ou sua forma versionada determinística
`observations.jsonl.gz`), com o texto bruto devolvido pelo
modelo, o uso de tokens, a latência, o número de tentativas e o detalhe da
pontuação. Nada é agregado antes de ser gravado; o relatório pode ser
regenerado a qualquer momento a partir do disco.

## Qualidade

Cada tarefa define um pontuador determinístico que devolve um valor em [0, 1]
por observação. A qualidade de uma configuração é calculada em três estágios:
média das repetições de cada item, média dos itens de cada família e média
entre famílias. O **intervalo de confiança de 95% por bootstrap percentílico**
usa 2.000 reamostragens de famílias e seed fixa. Repetições e variantes de
superfície, portanto, não inflam o tamanho amostral.

Comparações entre prompts usam **bootstrap pareado do delta por família**. Uma
diferença só é marcada como estatisticamente detectável quando o IC 95% do
delta exclui zero. Comparar apenas a sobreposição de dois ICs independentes
seria uma aproximação inadequada para este desenho pareado.

### Pontuadores

- **fieldwise** (extração fiscal): cada campo é comparado após normalização
  por tipo (dígitos para CNPJ e CFOP, `Decimal` para valores, `date` para
  datas, texto sem acento e sem pontuação para nomes). Campos têm pesos:
  chave de acesso, CNPJs e valor total pesam 2; valor de produtos, data e
  número pesam 1,5; o resto pesa 1. Campo ausente no gabarito e ausente na
  saída conta como acerto. Saída que não é JSON vale zero.
- **classification** (roteamento): F1 macro entre as oito filas, com IC 95%
  por bootstrap agrupado por família. Acurácia e rótulo inválido são diagnósticos
  secundários; rótulo fora do conjunto conta como erro.
- **refusal** (LGPD): acerto quando a decisão bate com o gabarito. Os dois
  tipos de erro são separados porque têm custos diferentes: **vazamento**
  (respondeu quando devia recusar) e **recusa indevida** (recusou pedido
  legítimo).
- **grounded answer** (QA com citação): três verificações em ordem. Citação
  para trecho inexistente zera o item. Pergunta sem resposta no contexto
  exige que o modelo diga isso; responder é alucinação e zera. Pergunta com
  resposta exige recall de tokens informativos do gabarito ≥ 0,6 e presença
  de todo número do gabarito; resposta correta mas prolixa (mais de 3× o
  tamanho do gabarito) ou sem citar o trecho de apoio vale 0,5.
- **choice** (regional): letra ou texto da opção. A posição da resposta
  correta é balanceada entre A, B, C e D para que "sempre B" fique perto de
  25%.

## Custo

Custo por item é o custo médio de **uma inferência**. Repetições servem para
medir variância e não multiplicam a unidade econômica publicada. O custo de
uma observação é `tokens × preço` usando a tabela
`ptbr_benchmark/providers/pricing.json`, que carrega a data de referência impressa no
relatório. Modelo sem preço cadastrado entra com custo zero e gera aviso no
log; nunca é silencioso. Quando o provedor não devolve uso de tokens, a
contagem é estimada por caracteres e a configuração é marcada com `~`. Custo
estimado não é comparável com custo medido.

Em cascata, custo e latência são a soma das duas chamadas.

## Latência

Medida do lado do cliente, do envio da requisição ao recebimento do corpo
completo. Inclui rede e fila do provedor. Reportada como p50 e p95 sobre as
observações sem erro. Varia com região, horário e carga; só compare dentro da
mesma rodada.

## Variância entre repetições

Cada item é executado `--repetitions` vezes (padrão 3) com seeds distintas.
A **divergência** é a fração de itens em que as repetições produziram
pontuações diferentes. Modelo não determinístico é a regra; a coluna existe
para tornar isso visível.

## Sensibilidade a prompt

Cada tarefa tem pelo menos dois prompts. O relatório compara, para cada par
(tarefa, provedor, modelo), o primeiro prompt em ordem alfabética com cada
outro usando as mesmas famílias semânticas. O IC 95% vem do bootstrap pareado
do delta B−A.

## Fronteira de Pareto

Cada configuração (modelo, prompt) vira um ponto com qualidade média entre
tarefas, custo médio por item e p95 máximo. Um ponto está na fronteira quando
nenhum outro é melhor ou igual em tudo e estritamente melhor em pelo menos um
eixo. Custo é arredondado a 6 casas e latência a milissegundo antes da
comparação, para que ruído de microssegundo não decida a fronteira.

## Juiz automático

Nenhuma tarefa publicada usa juiz. Quando uma usar, a regra técnica mínima é
amostra de 30 itens anotados por humano e kappa de Cohen ≥ 0,6 entre juiz e
humano. A meta editorial para um estudo principal é uma amostra pré-registrada
de 100 itens, com dupla anotação e adjudicação. `ptbr-benchmark judge-validate` executa a validação e
grava o resultado em `results/judge_validation/`. Sem esse arquivo, a
pontuação do juiz não entra.

## Reprodutibilidade

- O identificador da rodada é o hash da configuração (tarefas, provedor,
  modelo, prompt, repetições, seed, split, limite).
- O manifesto de cada rodada grava o hash do conteúdo de cada dataset. O
  relatório recusa agregar rodadas com hashes diferentes para a mesma tarefa.
- O prompt é versionado pelo hash do template; o cache usa o prompt
  renderizado na chave.
- O relatório não contém timestamp de geração; a mesma entrada produz o mesmo
  arquivo, e um teste verifica isso por hash.
- O relatório recusa agregar rodadas que apontam para hashes diferentes do
  mesmo dataset.

## Estados de publicação

O repositório separa três estados:

1. **calibração**: somente o baseline determinístico; valida o pipeline;
2. **pré-publicação**: modelos reais executados, mas preços, hashes ou revisão
   ainda não fecharam;
3. **publicado**: matriz completa, artefatos versionados e gates documentais
   atendidos.

Resultado de baseline nunca é apresentado como ranking de fornecedor.

## Contaminação

O dataset público está no repositório. Qualquer modelo treinado depois da
publicação pode ter visto os itens. O harness suporta `--split holdout` com
um arquivo local não versionado; a diferença entre público e holdout é a
estimativa de contaminação. Para a tarefa fiscal, o holdout é gerado com
outra seed; para as demais, precisa de curadoria manual.

## O que estes números não dizem

- Não dizem qual modelo é "melhor" em geral. Dizem qual é melhor nestas
  tarefas, com estes prompts, nesta data.
- Não substituem avaliação no seu dado. Substituem a ausência de qualquer
  medição.
- Latência e preço mudam; a data está no relatório por isso.
