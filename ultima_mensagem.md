# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# TRÊS MEDIDAS, TODAS CONCORDANDO

| Rodada | Rumo (sensor) | Andou | Desvio lateral | Desvio ÷ distância |
|---|---|---|---|---|
| Sem correção | +40,5° | 45 cm | ~50 cm | 1,11 |
| P puro | +23,0° | 50 cm | 37 cm | 0,74 |
| **P + I** | **+3,8°** | **53 cm** | **3,1 cm** | **0,058** |

**Queda de 94%** na proporção desvio ÷ distância.

Sua trena e o BNO085 concordaram nas três rodadas, medindo por vias
completamente diferentes. O dado está fechado.

## Um efeito secundário que vale notar

Ele andou **mais longe** a cada rodada — 45, depois 50, depois 53 cm — com a
mesma potência e o mesmo tempo. Faz sentido: energia que antes ia para a curva
agora vai para a frente. Um robô que anda reto é também um robô mais rápido.

---

# PRECISO RESOLVER UM PROBLEMA DE ESPAÇO ANTES DO GATE

O gate da Fase 3 é a **reta de 2 metros**. Mas o LIDAR para o robô a **0,50 m**
de qualquer obstáculo.

Então, para ele *percorrer* 2 metros, é preciso ter **2,5 metros livres** à
frente — os 2 m do percurso mais os 0,5 m em que o bumper vai intervir.

Com os 2 m que você tem hoje, o robô andaria no máximo **~1,5 m** e o LIDAR o
pararia. O que não é falha: é o bumper funcionando.

## Três caminhos, escolha um

**1. Arrumar 2,5 m de espaço livre.** É o único jeito de provar o gate exatamente
como está escrito. Tem corredor, pátio ou sala onde caiba?

**2. Provar a reta em 1,5 m e registrar a ressalva.** A qualidade do controle já
está demonstrada — 0,058 de desvio por metro percorrido significaria, numa reta
de 2 m, cerca de **12 cm de desvio**. É uma extrapolação honesta, mas
extrapolação.

**3. Fazer o percurso em duas pernas.** 1,5 m, virar o robô 180° na mão, mais
1,5 m. Prova 3 metros de controle contínuo, mas com uma interrupção no meio —
menos elegante que uma reta única.

**Minha recomendação: a opção 1**, se você tiver onde. É a única que fecha o
gate sem asterisco, e um robô garçom vai operar em corredores bem mais longos
que 2 metros — vale saber como ele se comporta numa distância real.

---

# Se você escolher a opção 1

Preciso saber:

- **Quantos metros livres** você consegue, à frente e nas laterais;
- se o **piso é o mesmo** (piso diferente muda o atrito e, portanto, a
  assimetria que a malha compensa).

Aí eu calculo a potência e o tempo. Como referência: a 8% ele faz ~8,8 cm/s, e a
12% deve fazer ~13 cm/s — 2 metros dariam uns 15 segundos.

---

# Onde a Fase 3 está

| Etapa | Situação |
|---|---|
| A — primeiro movimento do v2 | ✅ fechada |
| B — encoders | ✅ diagnosticada (esquerdo OK, direito com defeito) |
| C — controle por TPS | ⛔ bloqueada até a bancada |
| D — malha de rumo | ✅ **provada: 40,5° → 3,8°** |
| **Gate: reta de 2 m** | ⬜ depende do espaço |
