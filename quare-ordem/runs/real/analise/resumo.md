# Resumo da análise

Execuções analisadas: **250**. Gasto somado dos resultados: US$ 2.5269. Rodadas jogadas (média): 3.00. Encerramento antecipado: 0. Requisitos finais por execução (média): 14.8. Requisitos omitidos pela síntese (média): 0.26. Sínteses refeitas: 13.

## 1. Efeito de posição (todas as execuções)

Médias por posição de fala. *Sobrevivência*: fração dos 7 requisitos do agente que chegam ao resultado final. *Participação final*: fração dos requisitos finais derivados do agente. *Fatia da pauta*: fração dos conflitos que envolvem requisitos do agente.

| posição | sobrevivência | participação final | fatia da pauta | conflitos que abriu | concessões |
|---|---|---|---|---|---|
| 1 | 0.638 | 0.319 | 0.439 | 2.372 | 0.116 |
| 2 | 0.636 | 0.316 | 0.417 | 1.600 | 0.028 |
| 3 | 0.630 | 0.312 | 0.340 | 1.564 | 0.012 |
| 4 | 0.628 | 0.313 | 0.333 | 1.412 | 0.004 |
| 5 | 0.653 | 0.320 | 0.299 | 1.344 | 0.000 |

### Sobrevivência por caso e posição

| caso | pos 1 | pos 2 | pos 3 | pos 4 | pos 5 |
|---|---|---|---|---|---|
| AD | 0.554 | 0.586 | 0.571 | 0.574 | 0.580 |
| ATM | 0.637 | 0.654 | 0.671 | 0.683 | 0.720 |
| Bookkeeping | 0.666 | 0.637 | 0.617 | 0.597 | 0.637 |
| Library | 0.611 | 0.640 | 0.597 | 0.620 | 0.637 |
| RollCall | 0.720 | 0.663 | 0.694 | 0.666 | 0.691 |

### Sobrevivência por agente e posição

| agente | pos 1 | pos 2 | pos 3 | pos 4 | pos 5 |
|---|---|---|---|---|---|
| EfficiencyAgent | 0.640 | 0.640 | 0.631 | 0.680 | 0.703 |
| GreenAgent | 0.374 | 0.374 | 0.417 | 0.417 | 0.469 |
| ResponsibilityAgent | 0.766 | 0.683 | 0.631 | 0.674 | 0.649 |
| SafetyAgent | 0.834 | 0.869 | 0.840 | 0.831 | 0.846 |
| TrustworthinessAgent | 0.574 | 0.614 | 0.631 | 0.537 | 0.600 |

## 2. Quem pauta a discussão

Posição de quem levantou primeiro cada conflito (fração de todos os conflitos):

| posição de quem abriu | fração |
|---|---|
| 1 | 0.286 |
| 2 | 0.193 |
| 3 | 0.189 |
| 4 | 0.170 |
| 5 | 0.162 |

Posição de quem levantou o primeiro conflito de cada execução: pos 1: 221, pos 2: 4, pos 3: 14, pos 4: 1, pos 5: 1 (é esperado que seja quase sempre a posição 1, que fala antes; o indicador de pauta que importa é a *fatia da pauta* por posição, na seção 1).

## 3. Quanto discussão e resultado mudam entre ordens

Distâncias de 0 (idênticos) a 1. Se a ordem importa, a distância entre ordens diferentes supera a distância entre réplicas da mesma ordem (ruído do modelo). R² = fração da variação explicada pela ordem.

| caso | métrica | execuções | dist. mesma ordem | dist. ordens diferentes | pseudo_F | p | R2 |
|---|---|---|---|---|---|---|---|
| AD | agenda | 50 | 0.900 | 0.905 | 1.049 | 0.301 | 0.191 |
| AD | traceability | 50 | 0.442 | 0.439 | 0.974 | 0.544 | 0.180 |
| AD | text | 50 | 0.612 | 0.603 | 0.879 | 0.835 | 0.165 |
| ATM | agenda | 50 | 0.816 | 0.859 | 1.479 | 0.001 | 0.250 |
| ATM | traceability | 50 | 0.429 | 0.427 | 0.995 | 0.504 | 0.183 |
| ATM | text | 50 | 0.649 | 0.643 | 0.911 | 0.710 | 0.170 |
| Bookkeeping | agenda | 50 | 0.884 | 0.919 | 1.376 | 0.001 | 0.236 |
| Bookkeeping | traceability | 50 | 0.470 | 0.460 | 0.846 | 0.784 | 0.160 |
| Bookkeeping | text | 50 | 0.671 | 0.662 | 0.896 | 0.713 | 0.168 |
| Library | agenda | 50 | 0.808 | 0.854 | 1.457 | 0.002 | 0.247 |
| Library | traceability | 50 | 0.422 | 0.418 | 1.029 | 0.407 | 0.188 |
| Library | text | 50 | 0.607 | 0.612 | 1.129 | 0.150 | 0.203 |
| RollCall | agenda | 50 | 0.851 | 0.912 | 1.592 | 0.001 | 0.264 |
| RollCall | traceability | 50 | 0.409 | 0.431 | 1.386 | 0.034 | 0.238 |
| RollCall | text | 50 | 0.645 | 0.664 | 1.282 | 0.082 | 0.224 |

## 4. Testes (com correção de Holm sobre a família inteira)

| teste | estimativa | estatística | p | p (Holm) |
|---|---|---|---|---|
| PERMANOVA AD / agenda | 0.1909 | 1.0486 | 0.3010 | 1.0000 |
| PERMANOVA AD / traceability | 0.1797 | 0.9739 | 0.5440 | 1.0000 |
| PERMANOVA AD / text | 0.1651 | 0.8789 | 0.8350 | 1.0000 |
| PERMANOVA ATM / agenda | 0.2497 | 1.4794 | 0.0010 | 0.0180 |
| PERMANOVA ATM / traceability | 0.1830 | 0.9954 | 0.5040 | 1.0000 |
| PERMANOVA ATM / text | 0.1702 | 0.9114 | 0.7100 | 1.0000 |
| PERMANOVA Bookkeeping / agenda | 0.2364 | 1.3761 | 0.0010 | 0.0180 |
| PERMANOVA Bookkeeping / traceability | 0.1599 | 0.8458 | 0.7840 | 1.0000 |
| PERMANOVA Bookkeeping / text | 0.1678 | 0.8960 | 0.7130 | 1.0000 |
| PERMANOVA Library / agenda | 0.2469 | 1.4568 | 0.0020 | 0.0300 |
| PERMANOVA Library / traceability | 0.1880 | 1.0291 | 0.4070 | 1.0000 |
| PERMANOVA Library / text | 0.2026 | 1.1292 | 0.1500 | 1.0000 |
| PERMANOVA RollCall / agenda | 0.2638 | 1.5923 | 0.0010 | 0.0180 |
| PERMANOVA RollCall / traceability | 0.2377 | 1.3861 | 0.0340 | 0.4501 |
| PERMANOVA RollCall / text | 0.2238 | 1.2816 | 0.0820 | 0.9840 |
| H0: posição não afeta a sobrevivência (Wald conjunto) | — | 4.4585 | 0.3475 | 1.0000 |
| H1: 1ª posição sobrevive mais que as do meio (log-odds, unilateral) | 0.0344 | 0.6032 | 0.2732 | 1.0000 |
| H2: última posição sobrevive mais que as do meio (log-odds, unilateral) | 0.1105 | 1.8501 | 0.0322 | 0.4501 |
| Pauta: fatia da pauta muda com a posição (inclinação por posição) | -0.0371 | -8.3411 | 0.0000 | 0.0000 |
