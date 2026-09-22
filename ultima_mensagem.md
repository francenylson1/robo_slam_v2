# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# +3,8° — A MALHA DE RUMO ESTÁ FUNCIONANDO

Mesmas condições das outras duas rodadas: 8% de potência, 6 segundos.

| Rodada | Desvio de rumo | Correção aplicada |
|---|---|---|
| Sem correção | **+40,5°** | — |
| P puro | +23,0° | 2,40% — **saturado** |
| **P + I (agora)** | **+3,8°** | 3,14% — **com folga** |

**Redução de 91%** em relação à linha de base.

## Os dois detalhes que tornam esse resultado confiável

**1. A correção não saturou.** Chegou a 3,14% de um limite de 6%. Isso significa
que a malha ainda tem reserva: se o robô encontrar um piso pior, uma carga
diferente ou a bateria mais fraca, ela tem de onde puxar. Uma malha que trabalha
no limite está sempre a um imprevisto de falhar.

**2. O integral fez o trabalho que o proporcional não conseguia.** Era a
previsão: contra uma perturbação constante, P puro deixa resíduo. Os números
confirmaram — 23° com P puro, 3,8° com P+I.

---

# O QUE EU PRECISO DE VOCÊ

## 1. A medida da trena

Quanto andou para a frente, e quanto saiu de lado?

Minha expectativa, pelos 3,8° de rumo: algo em torno de **3 a 5 cm** de desvio
lateral, contra os ~50 cm da primeira rodada. Se a sua medida vier nessa ordem,
as duas vias concordam pela terceira vez e o dado está fechado.

## 2. A rodada dos 2 metros

Falta o gate de verdade: a **reta de 2 metros**. As três rodadas até agora
cobriram só ~45 cm cada.

Sugiro **12% de potência por 15 segundos**, que deve dar algo entre 1,7 e 2,2 m.
Preciso saber:

- **Você tem 2 metros livres à frente?** (Antes você disse que sim; confirme,
  porque desta vez ele vai usar o espaço todo.)
- O LIDAR para sozinho a 0,50 m de qualquer obstáculo, então se faltar espaço
  ele para antes — não bate.

Se preferir ir por etapas, posso rodar **12% por 10 segundos** primeiro, ver
quanto ele cobre, e só então ir aos 15.

---

# Onde a Fase 3 está

| Etapa | Situação |
|---|---|
| A — primeiro movimento do v2 | ✅ fechada |
| B — encoders | ✅ diagnosticada (esquerdo OK, direito com defeito físico) |
| C — controle por TPS | ⛔ bloqueada até a bancada |
| **D — malha de rumo** | ✅ **funcionando: 40,5° → 3,8°** |
| **Gate: reta de 2 m** | ⬜ **é o que falta** |

Depois disso, a Fase 3 fecha com uma ressalva honesta: o **E-Stop físico** ficou
para depois do SLAM, por decisão sua, e o **encoder direito** é item de bancada.
Nenhum dos dois impede o gate, mas os dois ficam registrados como pendências.

---

Mande a medida da trena e me diga se posso ir para os 2 metros.
