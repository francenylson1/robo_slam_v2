# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# TRÊS RODADAS IDÊNTICAS — e o trim fixo está descartado

| Rodada | RMS do rumo | **Correção em regime** | Excursão |
|---|---|---|---|
| A | 3,9° | **+6,00%** (saturada) | −2,4° a +12,4° |
| B | 2,7° | **−3,04%** | −8,4° a +4,1° |
| C | 4,7° | **+3,90%** | −0,8° a +13,4° |

Mesma configuração, mesmo percurso, nada alterado entre elas.

**A assimetria oscila numa faixa de quase 7 pontos percentuais e troca de
sinal.** Essa faixa é *maior* que a própria autoridade de correção (6%).

## Por que isso encerra a ideia do trim

Qualquer valor fixo que eu escolhesse estaria errado — **com o sinal trocado** —
em boa parte das rodadas. Nessas, ele empurraria **a favor** do erro, piorando
exatamente o que deveria corrigir.

O trim fica em **zero**, e a adaptação passa a ser feita inteiramente pelo
integral, que reaprende a cada reta. Registrei isso no código não como "parâmetro
a ajustar depois", mas como **caminho fechado, com medida** — para ninguém
tentar de novo daqui a seis meses.

Foi um bom investimento mesmo assim: a ideia era razoável, a medição foi barata,
e agora sabemos.

---

# A HIPÓTESE NOVA, E COMO TESTÁ-LA

Se a assimetria fosse dos motores, ela não trocaria de sinal — motor mais forte
é sempre o mais forte. Então provavelmente **não é só dos motores**.

Duas causas possíveis:

**1. A bateria.** Você mediu **39 V**. Na escala do projeto (30 a 42 V) são ~75%
da faixa útil, depois de uma tarde inteira de percursos. Se os dois drivers
perdem torque em proporções diferentes conforme a tensão cai, o desequilíbrio
muda ao longo do dia — e num evento de 4 horas o robô passaria por toda a faixa.

**2. O piso.** Se a sala tiver um caimento, por menor que seja, o robô escorrega
para o lado baixo. E aí a direção do desvio depende de **como ele está
posicionado** em relação ao caimento, não dos motores.

## O teste que separa as duas — e é barato

**Rodar o mesmo percurso com o robô virado 180°**, andando na direção oposta,
na mesma pista.

- Se o desvio **inverter de lado** em relação ao robô, é o **piso**: ele sempre
  escorrega para o mesmo lado da sala.
- Se o desvio **continuar para o mesmo lado** do robô, é dos **motores** (ou da
  bateria).

Um percurso, e a causa fica identificada.

---

# O QUE EU PRECISO DE VOCÊ

1. **O desvio em centímetros** das duas últimas rodadas, se anotou. Preciso deles
   para fechar a faixa em centímetros, não só em graus.

2. **Autorização para o teste dos 180°** — robô virado, mesma pista, mesmo
   comando. Se preferir encerrar por hoje, também está ótimo: isso é
   investigação de causa, não requisito do gate.

**O gate da Fase 3 já está cumprido** desde o percurso de 4,34 m. Tudo o que
fizemos depois foi refinamento, e o refinamento já rendeu: de 10,6 cm/m para
6,8 cm/m, com o RMS do rumo caindo de 10,8° para uma faixa de 2,7° a 4,7°.
