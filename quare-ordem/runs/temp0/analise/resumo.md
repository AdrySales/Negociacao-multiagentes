# Resumo da análise

Execuções analisadas: **100**. Gasto somado dos resultados: US$ 1.0434. Rodadas jogadas (média): 3.00. Encerramento antecipado: 0. Requisitos finais por execução (média): 20.0. Requisitos omitidos pela síntese (média): 0.23. Sínteses refeitas: 6.

## 1. Efeito de posição (todas as execuções)

Médias por posição de fala. *Sobrevivência*: fração dos 7 requisitos do agente que chegam ao resultado final. *Participação final*: fração dos requisitos finais derivados do agente. *Fatia da pauta*: fração dos conflitos que envolvem requisitos do agente.

| posição | sobrevivência | participação final | fatia da pauta | conflitos que abriu | concessões |
|---|---|---|---|---|---|
| 1 | 0.729 | 0.272 | 0.418 | 2.200 | 0.080 |
| 2 | 0.763 | 0.280 | 0.404 | 1.430 | 0.050 |
| 3 | 0.744 | 0.282 | 0.330 | 1.520 | 0.060 |
| 4 | 0.730 | 0.264 | 0.331 | 1.260 | 0.050 |
| 5 | 0.721 | 0.272 | 0.278 | 1.090 | 0.050 |

### Sobrevivência por caso e posição

| caso | pos 1 | pos 2 | pos 3 | pos 4 | pos 5 |
|---|---|---|---|---|---|
| AD | 0.571 | 0.600 | 0.586 | 0.514 | 0.557 |
| ATM | 0.721 | 0.750 | 0.757 | 0.786 | 0.743 |
| Bookkeeping | 0.886 | 0.879 | 0.829 | 0.800 | 0.807 |
| Library | 0.743 | 0.800 | 0.750 | 0.736 | 0.700 |
| RollCall | 0.721 | 0.786 | 0.800 | 0.814 | 0.800 |

### Sobrevivência por agente e posição

| agente | pos 1 | pos 2 | pos 3 | pos 4 | pos 5 |
|---|---|---|---|---|---|
| EfficiencyAgent | 0.729 | 0.879 | 0.771 | 0.764 | 0.786 |
| GreenAgent | 0.586 | 0.521 | 0.557 | 0.529 | 0.414 |
| ResponsibilityAgent | 0.671 | 0.714 | 0.800 | 0.757 | 0.721 |
| SafetyAgent | 0.900 | 0.936 | 0.893 | 0.936 | 0.957 |
| TrustworthinessAgent | 0.757 | 0.764 | 0.700 | 0.664 | 0.729 |

## 2. Quem pauta a discussão

Posição de quem levantou primeiro cada conflito (fração de todos os conflitos):

| posição de quem abriu | fração |
|---|---|
| 1 | 0.293 |
| 2 | 0.191 |
| 3 | 0.203 |
| 4 | 0.168 |
| 5 | 0.145 |

Posição de quem levantou o primeiro conflito de cada execução: pos 1: 90, pos 2: 1, pos 3: 5, pos 5: 1 (é esperado que seja quase sempre a posição 1, que fala antes; o indicador de pauta que importa é a *fatia da pauta* por posição, na seção 1).

## 3. Quanto discussão e resultado mudam entre ordens

Distâncias de 0 (idênticos) a 1. Se a ordem importa, a distância entre ordens diferentes supera a distância entre réplicas da mesma ordem (ruído do modelo). R² = fração da variação explicada pela ordem.

| caso | métrica | execuções | dist. mesma ordem | dist. ordens diferentes | pseudo_F | p | R2 |
|---|---|---|---|---|---|---|---|
| AD | agenda | 20 | 0.898 | 0.945 | 1.146 | 0.142 | 0.508 |
| AD | traceability | 20 | 0.366 | 0.351 | 0.836 | 0.744 | 0.429 |
| AD | text | 20 | 0.385 | 0.405 | 1.085 | 0.340 | 0.494 |
| ATM | agenda | 20 | 0.469 | 0.780 | 3.688 | 0.001 | 0.768 |
| ATM | traceability | 20 | 0.374 | 0.358 | 0.857 | 0.701 | 0.435 |
| ATM | text | 20 | 0.505 | 0.484 | 0.767 | 0.775 | 0.408 |
| Bookkeeping | agenda | 20 | 0.786 | 0.870 | 1.461 | 0.002 | 0.568 |
| Bookkeeping | traceability | 20 | 0.258 | 0.243 | 0.814 | 0.778 | 0.423 |
| Bookkeeping | text | 20 | 0.354 | 0.354 | 0.979 | 0.553 | 0.468 |
| Library | agenda | 20 | 0.887 | 0.906 | 1.106 | 0.199 | 0.499 |
| Library | traceability | 20 | 0.284 | 0.263 | 0.832 | 0.730 | 0.428 |
| Library | text | 20 | 0.397 | 0.373 | 0.887 | 0.693 | 0.444 |
| RollCall | agenda | 20 | 0.720 | 0.864 | 1.831 | 0.001 | 0.622 |
| RollCall | traceability | 20 | 0.335 | 0.330 | 0.904 | 0.538 | 0.449 |
| RollCall | text | 20 | 0.540 | 0.527 | 0.905 | 0.587 | 0.449 |

## 4. Testes (com correção de Holm sobre a família inteira)

| teste | estimativa | estatística | p | p (Holm) |
|---|---|---|---|---|
| PERMANOVA AD / agenda | 0.5077 | 1.1459 | 0.1420 | 1.0000 |
| PERMANOVA AD / traceability | 0.4294 | 0.8363 | 0.7440 | 1.0000 |
| PERMANOVA AD / text | 0.4940 | 1.0850 | 0.3400 | 1.0000 |
| PERMANOVA ATM / agenda | 0.7685 | 3.6884 | 0.0010 | 0.0180 |
| PERMANOVA ATM / traceability | 0.4354 | 0.8567 | 0.7010 | 1.0000 |
| PERMANOVA ATM / text | 0.4084 | 0.7669 | 0.7750 | 1.0000 |
| PERMANOVA Bookkeeping / agenda | 0.5680 | 1.4610 | 0.0020 | 0.0320 |
| PERMANOVA Bookkeeping / traceability | 0.4227 | 0.8136 | 0.7780 | 1.0000 |
| PERMANOVA Bookkeeping / text | 0.4685 | 0.9792 | 0.5530 | 1.0000 |
| PERMANOVA Library / agenda | 0.4988 | 1.1060 | 0.1990 | 1.0000 |
| PERMANOVA Library / traceability | 0.4280 | 0.8315 | 0.7300 | 1.0000 |
| PERMANOVA Library / text | 0.4440 | 0.8872 | 0.6930 | 1.0000 |
| PERMANOVA RollCall / agenda | 0.6224 | 1.8313 | 0.0010 | 0.0180 |
| PERMANOVA RollCall / traceability | 0.4486 | 0.9040 | 0.5380 | 1.0000 |
| PERMANOVA RollCall / text | 0.4488 | 0.9045 | 0.5870 | 1.0000 |
| H0: posição não afeta a sobrevivência (Wald conjunto) | — | 4.5935 | 0.3316 | 1.0000 |
| H1: 1ª posição sobrevive mais que as do meio (log-odds, unilateral) | -0.0980 | -0.8095 | 0.7909 | 1.0000 |
| H2: última posição sobrevive mais que as do meio (log-odds, unilateral) | -0.1417 | -1.6026 | 0.9455 | 1.0000 |
| Pauta: fatia da pauta muda com a posição (inclinação por posição) | -0.0365 | -5.1540 | 0.0000 | 0.0000 |
