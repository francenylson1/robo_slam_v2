# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# O QUE EU ACHO DO RESULTADO — e por quê

| | Andou | Desvio | Por metro |
|---|---|---|---|
| Rodada 1 | 4,90 m | 10,0 cm | **2,04 cm/m** |
| Rodada 2 | 4,80 m | 10,5 cm | **2,19 cm/m** |

**É reprodutível.** Duas rodadas independentes, 7% de diferença entre elas. Num
robô que passou a tarde inteira variando — o RMS foi de 1,6° a 4,7°, a
assimetria dos motores chegou a trocar de sinal — duas medidas assim juntas
significam que **a configuração domina a variabilidade**, e não o contrário.

Isso é o que separa "deu certo uma vez" de "funciona".

---

## De onde vêm esses 10 cm — a conta fecha

O desvio lateral é o acúmulo do erro de rumo ao longo do caminho. A matemática:

```
desvio ≈ distância × seno(erro médio de rumo)
```

Invertendo, com os números medidos:

```
10,2 cm em 4,85 m  →  erro médio de rumo ≈ 1,2°
```

E o RMS que o sensor mediu nas duas rodadas foi **1,3°** e **2,5°**.

**Os números independentes batem.** Isso quer dizer que não há nada inexplicado
acontecendo: o desvio que sobrou é exatamente o que o erro de rumo residual
produz. Não é folga mecânica, não é escorregamento, não é um bug escondido.

---

## O que mudou entre o começo e o fim da tarde

| | Início | Agora | Fator |
|---|---|---|---|
| Desvio por metro | 111 cm/m | **2,1 cm/m** | **53×** |
| RMS do rumo | 10,8° | **1,3° a 2,5°** | ~5× |
| Transiente na largada | 18 a 22 cm | praticamente sumiu | — |
| Correção usada | saturava em 6% | 2,7% a 5,1% | sobra reserva |

O transiente de largada — que resistiu ao trim e à partida suave — acabou
resolvido pela combinação certa: **proporcional forte** reage nos primeiros
graus, **integral com capacidade cheia** absorve o viés constante. Nenhum dos
dois sozinho dava conta.

---

## O limite que sobrou, e ele não é ajustável

Os 10 cm restantes vêm de um erro médio de rumo de ~1,2°. Para reduzi-los seria
preciso baixar esse erro abaixo de 1° — e aí esbarramos em duas coisas:

1. **A variabilidade do próprio robô.** A assimetria dos motores oscila numa
   faixa de 7 pontos percentuais e troca de sinal. A malha corre atrás de um
   alvo que se mexe.

2. **Rumo não é posição.** Esta é a barreira de verdade. A malha mantém o robô
   **apontado** na direção certa; ela não tem como saber que ele está 10 cm ao
   lado da linha, porque **nenhum sensor nosso mede isso**. Um erro minúsculo de
   rumo, mantido por metros, vira centímetros — e não há como recuperá-los sem
   saber onde a linha está.

**É por isso que eu pararia de refinar aqui.** Não por cansaço: porque o próximo
ganho real não vem de ajustar ganho nenhum. Vem do **Aurora, na Fase 4**, que
mede a posição do robô no mapa e fecha a segunda malha — a de trajetória.

O trabalho desta malha de rumo era deixar o robô **estável e previsível entre
as correções de posição**. Ela faz isso agora.

---

## O que 2,1 cm/m significa na prática, no seu salão

- Atravessar um salão de **10 metros** em linha reta, sem nenhuma correção de
  posição: chega **21 cm** ao lado do alvo.
- O robô tem **42 cm** de largura. Num corredor de 1 metro, ele passa com folga.
- Para **encostar numa mesa** e entregar um pedido, 21 cm é demais — mas esse é
  precisamente o trabalho da navegação da Fase 4, não da malha de rumo.

Ou seja: **para o que esta camada existe, o resultado é adequado.** Ela entrega
um robô que anda reto o suficiente para a navegação por mapa fazer o resto.

---

# MINHA RECOMENDAÇÃO

**Fechar a Fase 3 com esta configuração.**

```
HEADING_KP_PCT       = 0,45
HEADING_KI_PCT       = 0,25
HEADING_INTEGRAL_MAX = 24,0 graus·s
HEADING_MAX_CORR_PCT = 6,0
HEADING_INVERT       = False
partida suave        = desligada
```

E **ligar a malha por padrão** (`HEADING_ASSIST_ENABLED = True`), que até agora
está desligada porque não havia medida que justificasse ligá-la. Agora há: duas
rodadas reprodutíveis, 53 vezes melhor que sem ela.

Se você concordar, eu faço o fechamento: ligo a malha, atualizo a documentação
da fase com todos os números, registro as três pendências de bancada e escrevo o
prompt de retomada para a próxima sessão.
