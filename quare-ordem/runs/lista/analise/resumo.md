# Experimento da lista girada (250 sínteses refeitas)

## Sobrevivência por agente

| agent | original (lista fixa) | lista girada |
|---|---|---|
| SafetyAgent | 0.844 | 0.745 |
| EfficiencyAgent | 0.659 | 0.624 |
| GreenAgent | 0.410 | 0.452 |
| TrustworthinessAgent | 0.591 | 0.649 |
| ResponsibilityAgent | 0.681 | 0.771 |

## Sobrevivência por posição na lista (todos os agentes)

| list_pos | sobrevivência |
|---|---|
| 1 | 0.743 |
| 2 | 0.666 |
| 3 | 0.628 |
| 4 | 0.619 |
| 5 | 0.582 |

## Sobrevivência por agente e posição na lista

| agent | lista 1ª | lista 2ª | lista 3ª | lista 4ª | lista 5ª |
|---|---|---|---|---|---|
| SafetyAgent | 0.833 | 0.844 | 0.757 | 0.709 | 0.579 |
| EfficiencyAgent | 0.616 | 0.684 | 0.716 | 0.595 | 0.509 |
| GreenAgent | 0.530 | 0.388 | 0.380 | 0.506 | 0.454 |
| TrustworthinessAgent | 0.775 | 0.615 | 0.553 | 0.626 | 0.676 |
| ResponsibilityAgent | 0.963 | 0.801 | 0.735 | 0.660 | 0.695 |

## Testes

| test | estimate | statistic | p |
|---|---|---|---|
| posição na lista não afeta a sobrevivência (Wald conjunto) | — | 99.572 | 0.000 |
| agente não afeta a sobrevivência, dada a posição na lista (Wald conjunto) | — | 412.339 | 0.000 |
| lista 2ª vs 1ª (pontos percentuais, IC 95% -10.2 a -5.2) | -7.704 | -5.942 | 0.000 |
| lista 3ª vs 1ª (pontos percentuais, IC 95% -14.4 a -8.5) | -11.492 | -7.616 | 0.000 |
| lista 4ª vs 1ª (pontos percentuais, IC 95% -15.6 a -9.3) | -12.412 | -7.700 | 0.000 |
| lista 5ª vs 1ª (pontos percentuais, IC 95% -19.4 a -12.7) | -16.051 | -9.403 | 0.000 |
