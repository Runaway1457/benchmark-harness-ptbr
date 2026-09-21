# ADR 0001: Adaptadores HTTP sem SDK de provedor

Status: aceito

## Contexto

Comparar modelos de fornecedores diferentes exige que o único fator variável
seja o modelo. SDKs oficiais trazem comportamentos próprios: retry embutido
com política opaca, contagem de tokens diferente, defaults de temperatura,
formatação de mensagem. Além disso, cada SDK arrasta dependências e ritmo de
atualização próprios.

## Decisão

Cada provedor é um adaptador fino sobre `httpx` que conhece um endpoint, um
formato de requisição e um formato de resposta. Retry, cache e contagem de
custo vivem no harness, iguais para todos.

## Consequências

- O mesmo prompt, o mesmo parser e o mesmo pontuador valem para todo modelo.
- Adicionar um provedor é escrever uma classe com `complete()`.
- O harness precisa acompanhar mudanças de API por conta própria. Os
  adaptadores são pequenos e têm teste com transporte simulado, o que torna
  isso barato.
- Recursos específicos de um fornecedor (ferramentas, cache de prompt) ficam
  de fora por padrão. Quando entrarem, entram como opção explícita e
  documentada, não como default de um SDK.
