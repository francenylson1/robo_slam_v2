# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# O PADRÃO SE CONFIRMOU: o desvio nasce na largada

| Rodada | Andou | Desvio final | **Na largada** | Por metro |
|---|---|---|---|---|
| A (kp 0,45) | 3,24 m | 22 cm | ~22 cm | 6,8 |
| C (idêntica) | 3,25 m | 23 cm | **~18 cm** | 7,1 |

Duas rodadas iguais, resultados consistentes — e em ambas **quase todo o desvio
acontece nos primeiros instantes**. Depois disso o robô segura o paralelo.

---

# A SOLUÇÃO QUE NÃO DEPENDE DO SINAL

O trim atacaria exatamente esse transiente, mas foi descartado: o sinal da
assimetria troca entre rodadas (+6,00%, −3,04%, +3,90%).

**A partida suave resolve o mesmo problema sem precisar saber o sinal.**

O raciocínio: o desvio lateral cresce com a **velocidade**. Na largada, a malha
ainda não aprendeu nada — e é justamente quando o robô está mais rápido em
relação ao que ela sabe.

Se ele **arrancar devagar e acelerar em dois segundos**, a malha aprende durante
a fase lenta, quando cada grau de erro custa **milímetros** em vez de
centímetros. Quando chega à velocidade plena, a correção já está certa — não
importa para que lado ele esteja puxando hoje.

A rampa começa em 35% da potência alvo (acima do atrito estático, senão ele não
sai do lugar) e sobe até 100% no tempo configurado.

---

# O QUE EU PROPONHO

**Mesmo percurso, com partida suave de 2,5 segundos.** Tudo o mais idêntico:
12%, 20 s, `kp=0,45`, `ki=0,25`, limite 12, trim zero.

O que espero: o desvio na largada cair de ~18-22 cm para poucos centímetros, e
o desvio final acompanhar.

O que **não** espero mudar: o comportamento em regime, que já está bom — o robô
segura o paralelo com RMS de 2,7° a 4,7°.

---

# E há um teste de CAUSA, se você quiser entender a raiz

A assimetria trocar de sinal é estranho: motor mais forte deveria ser sempre o
mais forte. Duas explicações possíveis:

- **a bateria** (39 V, ~75% da faixa) — os dois drivers perdendo torque em
  proporções diferentes;
- **o piso** — se a sala tiver caimento, o robô escorrega para o lado baixo, e
  a direção depende de como ele foi posicionado.

**O teste que separa as duas:** rodar o mesmo percurso com o robô **virado
180°**, andando na direção oposta, na mesma pista.

- desvio **inverte de lado** em relação ao robô → é o **piso**;
- desvio **continua para o mesmo lado** do robô → são os **motores/bateria**.

Um percurso, e a causa fica identificada.

---

# O QUE EU PRECISO DE VOCÊ

Escolha o que prefere agora:

1. **Partida suave** — ataca o problema, melhora o número. *(recomendo)*
2. **Teste dos 180°** — entende a causa, não melhora nada hoje.
3. **Encerrar por hoje** — o gate já está cumprido desde o percurso de 4,34 m.

Se escolher 1 ou 2, ponha o robô na linha e diga "pode".
