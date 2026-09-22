# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# O GATE DA FASE 3 ESTÁ CUMPRIDO

| Medida | Valor |
|---|---|
| Distância percorrida | **4,34 m** — o gate pede 2 m |
| Desvio lateral | **3,1 cm** |
| Desvio de rumo (sensor) | +4,8° |
| Proporção desvio ÷ distância | **0,007** |

## O tamanho da melhora

| Rodada | Andou | Desvio | Proporção |
|---|---|---|---|
| Sem correção | 45 cm | ~50 cm | 1,11 |
| P puro | 50 cm | 37 cm | 0,74 |
| P + I (6 s) | 53 cm | 3,1 cm | 0,058 |
| **P + I (20 s)** | **4,34 m** | **3,1 cm** | **0,007** |

O mesmo desvio de 3,1 cm, mas agora em **oito vezes mais distância**. A
proporção melhorou cerca de **160 vezes** em relação à linha de base.

---

## Dois números seus corrigiram estimativas minhas

**1. Velocidade: 21,7 cm/s a 12%** — eu previa 13. A relação entre potência e
velocidade é bem mais que proporcional acima do atrito estático: a 8% ele faz
8,8 cm/s; a 12%, 21,7. Cinquenta por cento a mais de potência rende **duas vezes
e meia** mais velocidade.

Isso importa para a Fase 4: o robô é mais rápido do que eu estava assumindo, e o
tempo de reação do bumper precisa ser reavaliado nessa velocidade. A 21,7 cm/s,
o fail-closed de 1,03 s significa **22 cm percorridos** antes de parar — dentro
dos 50 cm do bumper, mas com menos margem do que parecia.

**2. O serpenteio começa em 1,6 m.** Isso confirma a hipótese do integral: até
1,6 m a malha vai firme, e é justamente o tempo que ele leva para carregar
demais. Depois disso passa a oscilar em torno da linha.

---

# O QUE EU PROPONHO AGORA

O gate está cumprido e eu poderia parar aqui. Mas o serpenteio é visível, e num
evento com convidados um robô que balança parece menos acabado do que um que
anda firme.

**A correção é de uma linha: reduzir o ganho integral pela metade** (de 0,25
para 0,12). Integral mais fraco carrega mais devagar e sobrepassa menos.

**Uma mudança de cada vez**, que é a disciplina que nos trouxe até aqui: mudo só
o `ki`, repetimos o mesmo percurso, e comparamos. Se o serpenteio sumir sem o
desvio piorar, fica. Se piorar, volto atrás e tentamos outro caminho
(amortecimento derivativo).

## Sua decisão

1. **Ajustar o `ki` e repetir o percurso** — mais uns 10 minutos. *(recomendo)*
2. **Fechar a Fase 3 como está** — o gate está cumprido, o serpenteio fica
   registrado como refinamento pendente.

Em qualquer dos casos, a Fase 3 fecha hoje com duas pendências já conhecidas e
registradas: o **E-Stop físico** (adiado por você para depois do SLAM) e o
**encoder direito** (defeito físico, item de bancada).
