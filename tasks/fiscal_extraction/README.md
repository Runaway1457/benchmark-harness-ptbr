# fiscal_extraction

Extração de 14 campos de um DANFE (Documento Auxiliar da Nota Fiscal Eletrônica) renderizado como texto, como sairia de OCR ou de PDF nativo.

## Entrada

`input.document`: texto da nota. Três variantes marcadas em `tags`:

- `clean`: rótulos íntegros, separador `: `.
- `ocr`: acentos removidos e espaços colapsados nos rótulos; separadores variados. Valores nunca são alterados.
- `scrambled`: blocos (emitente, destinatário, produtos, impostos) fora de ordem.

## Saída esperada

JSON com os campos: `chave_acesso`, `numero`, `serie`, `data_emissao`, `natureza_operacao`, `cfop`, `emitente_cnpj`, `emitente_razao_social`, `emitente_uf`, `destinatario_cnpj`, `destinatario_razao_social`, `valor_produtos`, `valor_total`, `quantidade_itens`.

## Pontuação

Acurácia por campo após normalização por tipo, ponderada: chave de acesso, CNPJs e valor total pesam 2; valor de produtos, data e número pesam 1,5; o resto pesa 1. O relatório também mostra a acurácia por campo e a fração de documentos 100% corretos.

## Baseline

Expressões regulares sobre rótulos. Falha de propósito em `scrambled` (pega o primeiro CNPJ, que pode ser o destinatário) e em `ocr` quando o rótulo perde o acento. Um modelo precisa vencer isso para justificar o custo.

## Regenerar

```bash
ptbr-benchmark datasets generate-fiscal --count 150 --seed 7
```

Mudar a seed muda o hash do dataset e invalida comparações anteriores.
