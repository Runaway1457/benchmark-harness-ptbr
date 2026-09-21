# ticket_routing

Roteamento de ticket de suporte de um produto SaaS brasileiro em oito filas.

## Categorias

`cobranca`, `acesso_login`, `bug_tecnico`, `cancelamento`, `duvida_produto`, `comercial`, `elogio`, `fraude_seguranca`. Seis itens por categoria.

## Saída esperada

`{"category": "<categoria>", "confidence": <0 a 1>}`. A confiança alimenta a cascata: abaixo de 0,6, ou rótulo inválido, o item escala.

## Casos ambíguos de propósito

Tags marcam onde a regra de desempate importa: cancelamento que reclama de cobrança (`ambiguo_cancelamento`), problema de senha descrito como "erro" (`usa_palavra_erro`), pergunta de preço antes de comprar (`preco_antes_de_comprar`), transação não reconhecida que parece cobrança.

## Baseline

Contagem de palavras-chave por categoria, com confiança derivada da margem entre a primeira e a segunda colocadas.
