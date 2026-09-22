# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# 2ª RODADA FEITA — a malha funciona, mas está fraca

| | Desvio de rumo | Correção aplicada |
|---|---|---|
| **Sem correção** | **+40,5°** | — |
| **Com correção** | **+23,0°** | **+2,40% — saturou** |

**Queda de 43%.** A malha age na direção certa: o sinal está correto, a
referência trava e solta como deve, e o robô desviou bem menos. Isso prova que
toda a mecânica da Fase 3 está funcionando.

**Mas ela bateu no teto.** "Saturou" quer dizer que a correção chegou ao limite
máximo configurado (2,4%) e ficou presa lá — ela queria corrigir mais e não
podia.

---

## O que os números dizem, com conta

- Sem correção o robô gira **6,75°/s** (40,5° em 6 s).
- Com 2,4% de correção, gira **3,83°/s** (23° em 6 s).
- Ou seja: **2,4% de diferença entre as rodas compra 2,9°/s** de correção.
- Para cancelar os 6,75°/s seriam necessários cerca de **5,6%**.

Estamos com menos da metade da autoridade necessária.

---

## E há um problema mais fundo que só aumentar o limite

A correção atual é **proporcional**: ela só existe enquanto existe erro. Contra
um desvio **constante** — que é o caso, um motor é sistematicamente mais forte
que o outro — um controle proporcional puro **sempre deixa um erro residual**.
Ele nunca zera o desvio; apenas o reduz.

O v1 não sofria disso porque tinha o **PID de velocidade por roda** embaixo, que
eliminava a assimetria na origem. Nós não temos essa camada, porque ela exige os
dois encoders e o direito está com defeito.

## A correção certa, então, são três coisas

**1. Termo integral (PI em vez de P).** O integral acumula o erro persistente e
aprende a compensar o desvio constante sozinho — é exatamente o remédio para
uma perturbação constante. Com anti-windup, para não acumular além do útil.

**2. Mais autoridade.** Subir o limite da correção dos atuais 2,4% para algo em
torno de 6%.

**3. Uma proteção nova, que o item 2 exige.** Hoje a correção SOMA ao comando
base. Com 15% de base e 6% de correção daria 21% — e **≥20% dispara o Emergency
Stop**, travando o robô em operação normal. Então a malha vai passar a
**rebaixar os dois lados juntos** quando a soma estourar o teto, preservando a
diferença entre eles (que é o que faz o robô virar) e sacrificando um pouco de
velocidade. Assim fica impossível, por construção, a correção provocar uma
emergência.

---

# O QUE EU PRECISO DE VOCÊ AGORA

## 1. A medida da trena desta rodada

Quanto ele andou para a frente e quanto saiu de lado, desta segunda vez? Serve
para confirmar a queda de 43% também no chão, não só no sensor.

## 2. Autorização para mexer na malha

Vou implementar os três itens acima e rodar os quatro harnesses. Nada disso move
o robô — é só código. Depois repetimos o par de medidas.

Se preferir parar por aqui e retomar depois, também está bem: a Etapa D já
provou que a malha funciona; o que falta é ajustar a força dela.

---

## Observação sobre velocidade, para ajustar expectativa

Você mediu **45 cm em 6 segundos** — cerca de 7,5 cm/s a 8% de potência. Minha
estimativa anterior (~1,4 m) estava errada: a tabela do v1 mapeia *setpoints de
TPS* para a potência que o PID precisa, e não "8% de duty produz 20 TPS". Em
malha aberta, como estamos rodando, a relação é outra.

Consequência prática: para cobrir os **2 metros** do gate vamos precisar de mais
tempo (uns 27 s a 8%) ou de mais potência (12%, ainda dentro do teto de 15%).
Sugiro **12% e 10 segundos** na próxima medida — deve dar perto de 1,5 m, com
folga para o LIDAR parar antes de qualquer coisa.
