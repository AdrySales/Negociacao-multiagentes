# quare-ordem

Experimento: o quanto a **ordem de fala dos agentes** muda a discussão e o resultado
final de uma negociação multiagente de requisitos no estilo QUARE (Cheng et al., RE 2026).

## Desenho

- **Entradas:** os 5 casos do OpenRE-Bench (AD, ATM, Library, RollCall, Bookkeeping), em `data/cases/`.
- **Fase 1 congelada:** cada um dos 5 agentes de qualidade gera exatamente 7 requisitos uma única vez
  por caso. Todas as ordens partem desse mesmo conjunto.
- **Fase 2 (debate):** até 3 rodadas; em cada rodada os 5 agentes falam em sequência e cada um vê a
  transcrição inteira. O encerramento antecipado só é permitido a partir da rodada 2, quando todos
  concordam. Os agentes nunca são informados da própria posição de fala.
- **Síntese:** um orquestrador integra o resultado num modelo KAOS de 3 níveis, informando de quais
  requisitos iniciais cada requisito final deriva, quais foram descartados e quem prevaleceu em cada conflito.
- **Variável manipulada:** a ordem de fala. São 10 ordens num quadrado de Williams: cada agente
  fala em cada posição 2 vezes, e cada par "A logo antes de B" aparece 2 vezes (`quare-ordem ordens`).
- **Réplicas:** 5 por ordem, para medir o ruído do próprio LLM.
- **Total:** 5 casos × 10 ordens × 5 réplicas = 250 execuções.
- **Modelo:** `gpt-4o-mini-2024-07-18`, temperatura 0,7 (os mesmos do artigo QUARE).

## Proteções contra gasto indevido

| Proteção | Como funciona |
|---|---|
| Teto de gasto | Antes de cada chamada, o custo de pior caso precisa caber no teto (padrão US$ 8). Se não couber, nada é enviado. |
| Registro de gastos | Toda chamada paga vai para `runs/real/ledger.jsonl`, e o teto considera o gasto acumulado entre execuções. |
| Cache | Toda resposta fica salva em `runs/real/cache/`. Rodar de novo nunca paga duas vezes. |
| Retomada | Execuções já concluídas são puladas. |
| Erros | Só erros temporários (rede, limite de taxa, erro 5xx) são repetidos, no máximo 3 tentativas. Chave inválida, crédito esgotado ou requisição inválida param tudo. |
| Disjuntor | 3 execuções com falha param o experimento. Os detalhes ficam em `runs/real/failures.jsonl`. |
| Confirmação | `rodar` só envia algo com `--confirmo`. |

Recomendação extra: deixe a **recarga automática desligada** no painel da OpenAI.

## Passo a passo

```powershell
uv sync --all-groups
uv run pytest                      # 31 testes, sem custo
uv run quare-ordem simular         # experimento completo com LLM falso, sem custo

# crie o arquivo .env com: OPENAI_API_KEY=sk-...
uv run quare-ordem checar          # testa a chave e o modelo (~US$ 0,00001)
uv run quare-ordem piloto          # 2 execuções reais no AD (ordens o00 e o05, opostas)
uv run quare-ordem rodar           # mostra a projeção de custo; não envia nada
uv run quare-ordem rodar --confirmo
uv run quare-ordem status
uv run --extra metrics quare-ordem analisar   # métricas e testes, sem custo

# rodada complementar: mesma Fase 1, ordens e sementes, temperatura 0 (100 execuções, teto US$ 1,50)
uv run quare-ordem temp0 --confirmo
uv run --extra metrics quare-ordem analisar --temp0

# lista girada: refaz só a síntese das 250 execuções de runs/real, listando os requisitos
# iniciais numa de 5 rotações da ordem dos agentes (teto US$ 1,00)
uv run quare-ordem lista --confirmo
uv run --extra metrics quare-ordem analisar --lista
```

## Métricas (`analisar`)

| O que mede | Métrica |
|---|---|
| Discussão | Pauta de conflitos (pares de requisitos em conflito; distância de Jaccard entre execuções), fatia da pauta que envolve os requisitos de cada agente, quem abre cada conflito, concessões |
| Resultado | Sobrevivência: fração dos 7 requisitos de cada agente que chega ao conjunto final, por posição de fala; participação no conjunto final; distância entre conjuntos finais (Jaccard da rastreabilidade e similaridade textual TF-IDF com pareamento ótimo, algoritmo húngaro) |
| Estatística | PERMANOVA por caso (variação entre ordens vs. entre réplicas); regressão logística da sobrevivência com efeitos fixos de agente e caso e erros agrupados por execução: H0 (Wald conjunto), H1 (1ª posição > meio), H2 (última posição > meio); correção de Holm |

A validação usa a simulação: o LLM falso faz o agente na posição p perder cada requisito com
probabilidade 0,1 + 0,1·p, e `tests/test_analysis.py` exige que a análise detecte esse efeito sem
acusar uma curva em U.

## Saídas

- `runs/real/phase1/<caso>.json`: Fase 1 congelada.
- `runs/real/results/<caso>-oNN-rN.json`: transcrição completa, síntese final e custo de cada execução.
- `runs/real/analise/`: tabelas CSV (`runs`, `agents`, `requirements`, `conflicts`, `distances`,
  `tests`) e `resumo.md`.
- `runs/simulacao/`: saída da simulação. Os dados são falsos e o LLM falso favorece de propósito
  quem fala antes, servindo para testar se as métricas detectam um efeito plantado.
