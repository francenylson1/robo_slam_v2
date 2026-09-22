# Etapa B — os encoders Hall: o que medimos e o que preciso saber

> Fase 3, 22/09/2026. Este arquivo existe para você responder com calma, sem
> depender de rolar o terminal.

---

## Por que a Etapa B existe

Os encoders Hall **nunca foram lidos pelo v2**. Eles são pré-requisito de duas
coisas que vêm a seguir:

- o **controle por TPS** (ticks por segundo), que é como o v1 dirige este robô e
  como a malha de rumo da reta de 2 m vai funcionar;
- a **odometria da Fase 4** (SLAM), que estima quanto o robô andou.

Sem encoder, a Fase 3 fica presa no controle em malha aberta (potência %), que é
o que fizemos na Etapa A.

---

## O que foi feito, em dois testes

### Teste 1 — contagem de ticks (40 segundos)

O script soltou a retenção (rodas leves), zerou os contadores e contou enquanto
você deveria empurrar o robô. **Nenhum motor foi comandado.**

```
ESQUERDO: 0 ticks  ->  0.00 voltas
DIREITO : 0 ticks  ->  0.00 voltas
```

Zero nos dois lados. Mas zero não distingue três causas muito diferentes:

1. as rodas não giraram (ninguém empurrou);
2. o sinal do sensor não chega ao pino da Pi;
3. o sinal chega, mas a contagem tem bug.

Por isso veio o segundo teste.

### Teste 2 — nível BRUTO dos pinos (40 segundos)

Em vez de contar, este lê o nível elétrico dos dois pinos **500 vezes por
segundo**, sem contagem e sem debounce. É o teste que separa as três causas.

```
ESQUERDO (GPIO 16): 19.159 amostras · nível visto [1] · 0 transições
DIREITO  (GPIO 17): 19.159 amostras · nível visto [0] · 0 transições
```

---

## Como se lê esse resultado

O ponto que muda tudo: os dois pinos estão configurados com **pull-down**
(`GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)`). Isso significa que um
pino **sem nada ligado lê 0**.

| Lado | Leu | O que isso diz |
|---|---|---|
| **Esquerdo** | **1** | Alguma coisa está **puxando o pino para alto** contra o pull-down. Isso é evidência de que o sensor Hall esquerdo **está conectado e alimentado** |
| **Direito** | **0** | Compatível com sensor conectado em repouso **ou** com fio solto — o pull-down produz 0 nos dois casos |

E há um segundo detalhe: **os dois estão em níveis diferentes**. É exatamente o
que se espera de dois sensores funcionando, parados em posições diferentes em
relação ao ímã do motor.

**Conclusão honesta:** "zero transições em 40 segundos" é perfeitamente
compatível com *"os sensores estão bem, mas as rodas não giraram"*. Não dá para
acusar o hardware ainda.

---

## O que eu preciso que você responda

**1. No teste 2 (o último, de 40 segundos), você girou as rodas com a mão?**
   - Girou quantas voltas, mais ou menos?
   - Girou as duas, ou só uma?

**2. No teste 1 (o de contagem, também 40 segundos), você chegou a empurrar o
   robô pelo chão?**

> Observação: nas duas vezes a janela começava ~5 segundos depois de eu
> disparar, e minha mensagem só chega a você quando o comando termina. Se você
> não teve tempo de agir dentro da janela, **não há nada de errado com o robô** —
> é só refazer, e desta vez eu deixo a janela em 2 minutos.

---

## O que acontece depois da sua resposta

### Se você NÃO girou / NÃO empurrou

Refazemos os dois testes com janela de **2 minutos**, tempo de sobra. Minha
expectativa é que os encoders funcionem — o nível alto no lado esquerdo é um
bom sinal.

### Se você GIROU bastante e mesmo assim deu zero

Aí temos um problema real de sinal, e o caminho é este, na ordem:

1. **Conferir a fiação dos Hall no chassi.** Os pinos que o código usa são
   **GPIO 16 (esquerdo)** e **GPIO 17 (direito)** — numeração BCM, os mesmos do
   v1. Vale confirmar onde esses dois fios chegam fisicamente.
2. **Conferir a alimentação do sensor.** Hall precisa de 3,3 V e terra comum com
   a Pi. Se o sensor é alimentado pela placa do hoverboard e ela estiver
   desligada, o sinal não existe mesmo com a fiação certa.
3. **Trocar o pull-down por pull-up**, se os sensores forem de coletor aberto —
   nesse caso eles só puxam para baixo, e sem pull-up o pino fica flutuando.
4. **Testar com o multímetro** girando a roda devagar: a tensão no fio de sinal
   deve alternar entre ~0 V e ~3,3 V.

O item 3 é o mais provável se a fiação estiver certa e mesmo assim não houver
transição — e é correção de uma linha no código.

---

## Enquanto isso, o que NÃO está bloqueado

A Etapa A está fechada e a Fase 3 não para por causa disto:

| Prova (Etapa A) | Resultado |
|---|---|
| A1 frente, 8% / 0,4 s | **2,5 cm para frente** ✅ |
| A2 ré, 8% / 0,4 s | **~2 cm para trás** ✅ |
| A3 só o esquerdo | gira à **direita** ✅ |
| A4 só o direito | gira à **esquerda**, mais fraco ✅ |
| Retenção ao parar (opção 2) | **resistente 30 s, leve depois** ✅ |

O núcleo motor do v2 está validado neste robô: direção, ré, os dois lados, o
teto de 15% e a retenção.

**Se os encoders derem trabalho**, existe um caminho alternativo para a reta de
2 m: fechar a malha de rumo direto em **potência (%)** em vez de TPS, usando só
o BNO085. É menos fiel ao v1 — que controla em TPS com o PID — mas o gate da
Fase 3 (andar 2 m reto) é alcançável assim, e o encoder volta a ser obrigatório
só na Fase 4, para a odometria.
