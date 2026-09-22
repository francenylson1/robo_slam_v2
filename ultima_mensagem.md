# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# A SUA MEDIDA CORRIGIU A MINHA CONCLUSÃO

Eu tinha escrito "o limite 12 fica", olhando para as métricas de rumo:
oscilação zerada, amplitude de 35° para 21,7°, correção sem saturar.

**No chão, piorou.** 28 cm na rodada 1, **52 cm** na rodada 2.

## Onde eu errei

O desvio lateral é o **acúmulo** do erro de rumo ao longo do caminho. Quem o
prevê não é o **pico** do erro — é o **desvio médio quadrático**, que mede quanto
tempo o robô passou torto.

| | Pico do rumo | RMS do rumo | Desvio lateral |
|---|---|---|---|
| Limite 24 | 25,9° | 10,8° | 28 cm |
| Limite 12 | **21,7°** (melhor) | **12,9°** (pior) | **52 cm** (pior) |

O pico melhorou e o resultado piorou. Os que andaram juntos foram o **RMS** e os
**centímetros**.

Faz sentido: com o integral mais fraco o robô **demora mais para endireitar**. O
pico é menor, mas ele fica torto por mais tempo — e é o tempo torto que vira
centímetros.

**Eu estava otimizando a métrica errada.** Oscilação de rumo é desconforto
visual; RMS é o que sai em centímetros no chão. A partir de agora o número que
eu persigo é o RMS.

---

# PRECISO DE UM NÚMERO PARA FECHAR A CONTA

**Quantos metros ele andou na rodada 2?**

Sem isso não sei se os 52 cm são piores *proporcionalmente* ou só efeito de ter
andado mais longe — ele parou pelo LIDAR, ou seja, chegou ao fim da pista.

- Rodada 1: 28 cm em 2,64 m = **10,6 cm por metro**
- Rodada 2: 52 cm em **? m** = ?

Se ele andou 4,9 m, a proporção é praticamente a mesma (10,6 cm/m) e as duas
configurações empatam. Se andou 3 m, piorou de verdade.

---

# A PROPOSTA SEGUINTE — agora com mais razão ainda

Aumentar o **`kp`** de 0,105 para **0,45**.

Hoje o `kp` é fraco demais: o robô precisa desviar **53 graus** para ele sozinho
produzir a correção que o desvio natural pede (~5,6%). Por isso quem faz o
trabalho é o integral — e o integral é lento por natureza, porque precisa
**acumular** erro antes de agir.

| Erro de rumo | `kp` hoje (0,105) | `kp` proposto (0,45) |
|---|---|---|
| 5° | 0,53% | **2,25%** |
| 12° | 1,26% | **5,40%** |

Com o `kp` forte, o robô reage **nos primeiros graus** em vez de esperar o
integral carregar. Isso ataca diretamente o RMS — que é o número que vira
centímetros — e não só o pico.

**Risco:** `kp` alto demais faz o robô corrigir rápido, passar do ponto e
corrigir de volta — oscilação. Agora temos como ver isso na hora: se os
cruzamentos de rumo voltarem e a amplitude subir, recuo para 0,25.

---

# O QUE EU PRECISO DE VOCÊ

1. **A distância da rodada 2** (o número que falta na conta acima).
2. **Robô na linha de partida** e um **"pode"** para a rodada com `kp = 0,45`.

O que espero: RMS bem abaixo de 10,8°, e o desvio lateral por metro caindo junto.
