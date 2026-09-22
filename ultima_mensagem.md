# Última mensagem

> Arquivo de trabalho: eu escrevo aqui o que acabei de dizer no terminal, para
> você ler sem depender de rolar a tela. **É sobrescrito a cada mensagem** — o
> que vale é sempre o conteúdo atual.
>
> Atualizado em 22/09/2026.

---

# O GATE DA FASE 3 — a reta

É a primeira vez que este robô vai andar **sozinho e continuamente** sob o v2.
Até agora só demos pulsos de 0,4 segundo.

## O que vai acontecer

O robô anda para a frente a **8% de potência** por até **6 segundos** — cerca de
**1,4 metro**, pela tabela do seu próprio v1.

Ele para sozinho por uma de duas razões:

1. o tempo acabar (6 segundos);
2. **o LIDAR bloquear** — qualquer obstáculo a menos de 0,50 m à frente.

Com os seus 2 metros livres, o bumper é a rede de segurança.

## Vamos rodar DUAS vezes

| Rodada | Correção de rumo | Para que serve |
|---|---|---|
| **1ª** | **DESLIGADA** | medir o desvio natural — o quanto ele puxa para um lado sozinho |
| **2ª** | **LIGADA** | medir o desvio com a malha de rumo trabalhando |

**Sem o par de medidas não há prova de nada.** Um número sozinho não diz se a
malha ajudou. Por isso começamos pela rodada sem correção.

---

## O que você precisa fazer ANTES de eu disparar

1. **Marque a linha de partida no chão** e alinhe as rodas do robô nela.

2. **Marque a direção** — um barbante esticado, uma fita no chão, ou use a junta
   do piso. É daí que você vai medir o desvio depois.

3. Confirme o espaço: **2 metros livres à frente**, 1 metro de cada lado,
   ninguém no caminho.

4. **Fique ao lado da chave geral.** Enquanto não existe o botão cogumelo, ela é
   o E-Stop do robô.

## O que você faz DEPOIS que ele parar

5. **Meça com a trena** o quanto o centro do robô se afastou lateralmente da
   linha de direção que você marcou. Em centímetros.

6. Me diga esse número **e para qual lado** ele saiu (direita ou esquerda).

---

## O que eu meço em paralelo

Enquanto ele anda, estou acumulando pelo **BNO085** o quanto o rumo girou
durante todo o percurso. É o mesmo desvio, medido por uma via **independente**
da sua trena.

Se as duas concordarem — sua medida no chão e a minha no sensor — a medida é
sólida e o gate fica provado de verdade.

---

# O QUE EU PRECISO DE VOCÊ AGORA

Responda **"pode"** quando:

- a linha de partida estiver marcada,
- a direção estiver marcada,
- o caminho estiver livre,
- e você estiver com a mão na chave geral.

Aí eu disparo a **primeira rodada, com a correção DESLIGADA**.
