# Etapa B — os encoders Hall: o que medimos e o que preciso saber

> Fase 3, 22/09/2026.
>
> **O resultado e o diagnóstico estão no FIM do arquivo** ("RESULTADO FINAL").
> O que vem antes é o caminho até lá, na ordem em que aconteceu — inclusive as
> perguntas que ficaram abertas no meio e foram respondidas refazendo a medida,
> em vez de por memória.

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

---

# RESULTADO FINAL (22/09/2026)

Refeito com janela de 2 minutos e o professor girando sem parar:

```
ESQUERDO: 1282 ticks  ->  28,5 voltas   OK
DIREITO :    0 ticks  ->   0,00 voltas  FALHA
```

Antes, o teste de nível bruto (também 2 minutos, rodas girando):

```
ESQUERDO (GPIO 16): 57.471 amostras · níveis [0, 1] · 1.509 transições
DIREITO  (GPIO 17): 57.471 amostras · nível  [0]    ·     0 transições
```

## O diagnóstico

**O software está correto.** O lado esquerdo contou 1.282 ticks limpos — isso
prova o laço de leitura, o debounce de 10 ms, a detecção de borda de subida, o
pull-down como configuração certa para este sensor, e a coerência de
`TICKS_PER_REVOLUTION = 45` (28,5 voltas em 2 min de empurra-e-puxa batem com o
espaço disponível).

**O encoder direito tem defeito físico.** Dois testes independentes, 4 minutos
no total, com a roda comprovadamente girando: zero transições no nível bruto e
zero ticks na contagem. O mesmo código que conta 1.282 de um lado conta 0 do
outro.

Causas possíveis, todas de bancada, todas no lado direito:

1. fio de sinal solto ou rompido entre o sensor e o **GPIO 17**;
2. sensor sem alimentação (3,3 V ou terra comum);
3. sensor Hall queimado;
4. fio no pino errado.

---

# A pergunta do professor: o caminho alternativo é pior?

> "Quando você diz '...é menos fiel ao v1 mas resolve o problema real...',
> significa que essa alternativa é menos precisa? Vai perder qualidade na
> navegação SLAM? Navegação autônoma com risco de acidentes?"

Três perguntas diferentes, três respostas diferentes.

## 1. É menos precisa na reta? Um pouco, e de um jeito específico

Nos **dois** caminhos quem mede se o robô vai reto é o **BNO085, a 100 Hz**. A
malha de rumo é a mesma. A diferença está na malha **interna**:

| | Com TPS + PID | Só com potência (%) |
|---|---|---|
| Cada roda regulada para uma **velocidade** alvo | sim | não |
| Bateria caindo, tapete, carga mudando | absorvidos **antes** de virarem desvio | viram desvio, e o BNO corrige **depois** |
| Comportamento | corrige **preventivamente** | corrige **reativamente** |

O robô anda reto nos dois casos. Sem a malha interna ele oscila um pouco em
torno da linha em vez de seguir um traço mais firme, e o ganho da correção
precisa ser mais suave para não oscilar. Numa reta de 2 m a ≤15%, a diferença é
pequena.

## 2. Perde qualidade no SLAM? NÃO

**A pose da Fase 4 vem do Slamtec Aurora**, que faz SLAM visual-laser e estima a
própria posição (`docs/PROPOSTA_PRODUCAO_COMERCIAL.md`: *"o Aurora resolve a
pose"*; `AURORA_MOUNT_HEIGHT_CM = 30` no settings).

Mais direto: `get_and_reset_ticks()` hoje **não é chamado por ninguém** — o
`slam_nav.py` só sabe chamar `stop()`. Os encoders nunca foram a fonte de pose
deste projeto.

## 3. Risco de acidente na navegação autônoma? NÃO por causa disso

Nenhuma camada de segurança lê encoder ou depende do modo de controle:

| Camada | Depende de encoder? |
|---|---|
| Bumper do LIDAR (fail-closed) | não |
| Teto de 15% / E-Stop em 20% | não |
| Watchdog do loop de 50 Hz | não |
| `/api/stop` e E-Stop da frota | não |
| Timeout do joystick | não |

**Mas há uma perda real, que não deve ser minimizada.** Com os dois encoders dá
para detectar **roda travada**: "estou mandando potência e a roda não gira".
Isso pega um motor falhando, uma roda presa, ou o robô encostado em algo que o
LIDAR não enxerga — um cabo no chão, um pé, um degrau baixo. Hoje isso não está
implementado, mas é a proteção natural para os 30 minutos autônomos sem
supervisão da Fase 4, e **precisa dos dois lados**.

## Recomendação

Seguir agora pelo caminho do BNO085 e fechar o gate da Fase 3 — não há motivo
para parar o desenvolvimento. E **resolver o encoder direito na bancada antes da
Fase 4**, junto com o ADS1115, que já está nessa lista pelo mesmo motivo:
operação autônoma sem ninguém olhando.

---

# DIAGNÓSTICO (23/09/2026) — a saída S da ZS-X11H direita está ABERTA (morta)

O circuito de cada lado é: **pino S da ZS-X11H → entrada do optoacoplador (5 V)
→ saída do opto (3,3 V) → GPIO** (16 esquerdo, 17 direito). A Pi fica isolada.

| Teste | Resultado | O que prova |
|---|---|---|
| Fios S **trocados** na entrada do opto; roda **direita** girando | GPIO 16 e 17: **0 transições** | O defeito está **antes** do opto |
| Mesma troca; roda **esquerda** girando | GPIO 17: **74–91 transições/s** | Canal direito do opto, fio até o pino 11 e GPIO 17 **bons** |
| Multímetro no S da placa direita, roda girando | **0 V parado** | A placa não gera pulso |
| Resistência S↔GND, bateria desligada, placa sozinha | direita **0.L (aberto)** · esquerda **67 kΩ / 6,67 MΩ** (um sentido / outro) | **Saída S da placa direita aberta** |
| Fio S velho, solto das duas pontas, ↔ GND | **0.L (aberto)** | **O fio está bom** |

O motor direito gira (a placa lê os Hall para comutar); morreu só a saída de pulso.
**Solução:** trocar a ZS-X11H direita (45 pulsos/volta nos dois lados, sem mudar
software). Placa nova testada fora do robô: S↔GND **67,4 kΩ / 6,67 MΩ** — igual à
esquerda. Aprovada.

⚠️ **A armadilha do visor que custou uma hora:** este multímetro mostra o infinito
como **"0.L"**, que foi lido como "0". Por um tempo concluímos "curto na placa e no
fio" e decidimos trocar o fio. Desfeito quando a placa nova, **solta de tudo**,
"deu 0" contra o fio DIR — impossível. **Sempre ler o visor inteiro: "0.L" =
aberto; curto é "0.00".**

**Nota de método:** com o opto no caminho, o teste de trocar o pull-down por
pull-up na Pi **não prova nada** — o resistor da própria placa do opto domina o
pull-up interno de ~50 kΩ. Os dois lados leram 0 com pull-up, inclusive o bom.

## RESOLVIDO (23/09/2026, ~19h) — placa direita trocada

- ZS-X11H nova testada fora do robô (S↔GND 67,4 kΩ / 6,67 MΩ), instalada com
  fases e Hall na ordem antiga; S soldado de novo (S↔GND depois de soldar: 67,4 kΩ).
- **GPIO 17 com a roda direita girando à mão: 135–230 transições/s.** ✅
- Pulso A4 (só direito, 8%, 0,4 s), duas vezes: a roda direita gira **para frente**. ✅
- Harnesses na Pi: 80/80, 74/74, 17/17, 37/37.
- **Falta:** a prova de retenção da roda direita (segura parada, solta depois de
  30 s) e medir `TICKS_PER_REVOLUTION` do lado direito (esperado 45, igual ao esquerdo).
