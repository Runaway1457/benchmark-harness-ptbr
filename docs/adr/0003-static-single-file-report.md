# ADR 0003: Site de resultado é um arquivo HTML estático

Status: aceito

## Contexto

Um benchmark precisa de uma página de resultado que qualquer pessoa abra, que
funcione daqui a dois anos e que possa ser conferida contra os dados brutos.
Um aplicativo web com backend adiciona superfície de ataque, custo de
hospedagem, dependência de build e uma forma de o resultado divergir do dado.

## Decisão

`ptbr-benchmark report` gera um único `site/index.html`, sem JavaScript externo, sem
fonte externa, sem requisição de rede. O gráfico de Pareto é SVG gerado em
Python. O CSS é embutido a partir de `ptbr_benchmark/report/report.css`. A geração é
determinística: sem timestamp de geração, ordenação estável, e um teste
verifica que a mesma entrada produz o mesmo hash.

## Consequências

- Publicar é copiar um arquivo para qualquer host estático.
- O HTML pode ser regenerado a partir de `results/` a qualquer momento e
  comparado byte a byte com o publicado.
- Interatividade fica limitada a `<title>` em SVG e CSS. Se algum dia for
  preciso filtrar ou explorar, isso será um artefato separado, não uma
  dependência do relatório canônico.
