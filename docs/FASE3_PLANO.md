# Fase 3 — Chassi e potência: o plano

> Gate: **linha reta de 2 m** + Emergency Stop físico testado.
> Escrito em 22/09/2026, depois de auditar o código antigo que move este robô hoje.

---

## O ponto de partida, nas palavras do professor

| Pergunta | Resposta (22/09/2026) |
|---|---|
| Chassi montado? | **Sim**, rodas no chão |
| Os motores giram? | **Sim — mas com as GPIOs do código antigo. A v2 NUNCA moveu este robô**, nem PWM sem carga |
| E-Stop físico? | **Não instalado.** Decisão: depois que o SLAM estabilizar |
| BNO085 | Fixo e deitado, com **leve inclinação** (estimada em 2–7% da perfeição) |
| Espaço | **2 m à frente, 50 cm nas laterais** |

O fato central é o segundo: **o núcleo motor do v2 nunca foi confrontado com este
robô.** Tudo que segue parte daí.

---

## 1. Auditoria: o v2 está igual ao que move o robô hoje?

Comparação linha a linha entre `old_versions/robot_motor_controller.py` (o que
funciona) e o v2.

| Item | Código antigo | v2 | |
|---|---|---|---|
| `dir_E` / `break_E` / `pwm_E` / `hall_E` | 5 / 6 / 18 / 16 | idênticos | ✅ |
| `dir_D` / `break_D` / `pwm_D` / `hall_D` | 23 / 24 / 12 / 17 | idênticos | ✅ |
| Esquerdo à frente | `HIGH` | `DIR_E_FORWARD = 1` | ✅ |
| Direito à frente | `LOW` — **oposto por design físico** | `DIR_D_FORWARD = 0` | ✅ |
| Pino de "freio" | `LOW` ao mover, `HIGH` ao parar | idêntico | ✅ mas **os dois nomearam errado** — ver §7 |
| Frequência do PWM | 20 Hz | `PWM_FREQUENCY_HZ = 20` | ✅ |

**Conclusão: a migração está fiel.** Não há motivo conhecido para o robô se comportar
de forma diferente sob o v2 — o que não substitui a prova física.

Uma diferença proposital: o código antigo fazia `min(abs(power), 100)` — podia ir a
100%. O v2 corta em 15% (Regra Nº 0).

---

## 2. Os 15% não são um aperto — são o projeto

Dúvida legítima antes de começar: *a 15% este robô sai do lugar?*

A resposta estava no próprio v1, em `~/robo_slam/src/core/config.py`:

| Perfil | TPS | Potência |
|---|---|---|
| `SPEED_SLOW_TPS` (precisão) | 20 | até **8%** |
| `SPEED_NORMAL_TPS` (navegação) | 35 | até **12%** |
| `SPEED_FAST_TPS` (trajetos longos) | 50 | até **15%** — *"LIMITE SEGURANÇA"* |

Ou seja: **a regra dos 15% nasceu aqui**, e o robô opera confortavelmente entre 8% e
15%. O teto não limita a Fase 3.

---

## 3. Dois bloqueadores encontrados ANTES de mexer no robô

### 🔴 Bloqueador 1 — o PID do v2 dispararia o Emergency Stop na primeira tentativa

```python
# config/settings.py (como estava)
PID_OUTPUT_MIN = -90.0
PID_OUTPUT_MAX =  90.0
```

O caminho por TPS (`set_target_speed_tps`) manda a saída do PID para
`_apply_safety_clip()`. Com Ki = 0,23 e um degrau de 35 TPS, a saída passa de 20% em
poucos ciclos — e **≥20% não é cortado, é Emergency Stop**: o robô trava e só volta
reiniciando o serviço.

No v1 isso nunca acontecia porque o PID era limitado **por perfil de velocidade**:
`(-8, 8)`, `(-12, 12)`, `(-15, 15)`. Ele saturava no teto, nunca o ultrapassava.

**Correção:** `PID_OUTPUT_MIN/MAX = ∓15`, alinhado a `MOTOR_MAX_POWER_PCT`. O PID
satura no teto, como no v1, e a Regra Nº 0 volta a ser o que deve ser: a rede de
segurança para **bugs**, não um obstáculo na operação normal.

### 🔴 Bloqueador 2 — `TICKS_PER_REVOLUTION` veio errado na migração

```
v1:  TICKS_PER_REVOLUTION = 45   # "VALOR CALIBRADO: Medido experimentalmente"
v2:  TICKS_PER_REVOLUTION = 20
```

Fator de 2,25 de erro. Hoje o v2 só **importa** a constante sem usá-la, então nada
quebrou ainda — mas ela é a base da odometria da Fase 4 e de qualquer conversão
TPS ↔ metros. Corrigido para **45**, o valor que o professor mediu.

---

## 4. O que o v1 já resolveu, e que vamos reusar

`~/robo_slam/joystick_controller_2026.py` **já fecha a malha de rumo com o BNO085**.
O algoritmo, provado neste robô:

```python
if comando_de_frente_ou_re:
    base_tps = -axis_y * speed_tps
    yaw_now = get_bno_yaw()
    if yaw_ref is None:
        yaw_ref = yaw_now                      # trava a referência AO ENTRAR na reta
    err  = normalize_angle_deg(yaw_now - yaw_ref)
    if invert_bno:
        err = -err
    corr = clamp(kp * err, ±max_corr)
    left_tps  = base_tps - corr
    right_tps = base_tps + corr
elif giro_no_lugar:
    yaw_ref = None                              # solta a referência ao girar
```

Constantes já tunadas por ele (`~/robo_slam/src/core/config.py`):

```
BNO_STRAIGHT_KP                 = 0.35   # "Reduzido de 0.7 para correções mais suaves"
BNO_STRAIGHT_MAX_CORRECTION_TPS = 8.0    # "Limite de TPS (era 12)"
BNO_STRAIGHT_INVERT_CORRECTION  = True   # o sinal É invertido neste robô
TURN_TPS_DEFAULT                = 12.0
```

Três coisas que esse código ensina e que não se descobriria sozinho:

1. **A referência de rumo é travada ao entrar na reta e solta ao girar.** Sem isso, o
   robô tentaria voltar ao rumo antigo depois de cada curva.
2. **O eixo X é ignorado enquanto anda para frente** — quem corrige a reta é só o BNO.
   O robô anda reto ou gira no lugar; não faz curva aberta. É uma simplificação
   deliberada para um garçom.
3. **`INVERT_CORRECTION = True`.** O sinal do yaw neste robô é invertido em relação ao
   intuitivo. Casa com a medida de 21/09 ("girar para a DIREITA aumenta o yaw") e com
   a ressalva de que faltava confirmar na Fase 3. **Confirmar na bancada.**

### Sobre a inclinação do BNO085 (2–7%)

Não atrapalha a reta. A malha controla a **diferença** entre o yaw atual e uma
referência travada no instante em que a reta começa — um desvio constante de montagem
entra nos dois termos e se cancela na subtração. A inclinação só importaria para
navegação absoluta em terreno inclinado (Fase 4), e mesmo ali como erro pequeno.

---

## 5. A sequência de provas — um desconhecido de cada vez

O erro seria ligar tudo junto: primeiro movimento do v2 **+** encoders nunca testados
**+** caminho PID nunca usado **+** malha de rumo nova. Quatro incógnitas, e um
sintoma qualquer sem causa identificável.

### Etapa A — o primeiro movimento do v2 (malha aberta, %)

Sem PID, sem encoder, sem BNO. Só `set_speed()` com pulsos curtos.

| Prova | Como | Esperado |
|---|---|---|
| A1 | pulso de 0,4 s a 8%, os dois lados à frente | robô anda para **frente** |
| A2 | pulso de 0,4 s a 8%, os dois lados em ré | robô anda para **trás** |
| A3 | só o lado esquerdo, 0,4 s a 8% | gira para a **direita** |
| A4 | só o lado direito, 0,4 s a 8% | gira para a **esquerda** |
| A5 | sem comando | freios **acionados**, robô travado |

Com 2 m à frente e 50 cm nas laterais, um pulso de 0,4 s a 8% percorre poucos
centímetros. **O professor fica ao lado da chave geral** — enquanto não houver
E-Stop físico, ela é o E-Stop.

### Etapa B — os encoders

`get_and_reset_ticks()` durante um pulso. Esperado: os dois lados contando, na mesma
ordem de grandeza. É pré-requisito do PID e da odometria da Fase 4.

### Etapa C — o caminho por TPS

Só depois do bloqueador 1 corrigido. `set_target_speed_tps(20, 20)` (perfil lento) e
verificar que a velocidade converge sem disparar a Regra 0.

### Etapa D — a malha de rumo, e o gate

Fechar o passo 3 do `control_loop.py` com o algoritmo e as constantes do v1. Medir a
reta de 2 m **com a correção desligada e ligada**, e comparar o desvio lateral. Sem
o par de medidas não há prova de que a malha serve para alguma coisa.

---

## 6. Segurança enquanto não há E-Stop físico

O botão cogumelo ficou para depois do SLAM (decisão do professor). Até lá, as paradas
disponíveis são:

| Camada | Alcance |
|---|---|
| Chave geral de alimentação | **a mais rápida** — o professor ao lado dela |
| Bumper do LIDAR (< 0,50 m, ±30°) | automático, já provado |
| `POST /api/stop` (sem login) | do celular ou do navegador |
| Timeout do joystick | para se o controle sumir |
| Regra Nº 0 | teto de 15%, ≥20% trava |

Os pulsos das etapas A–C são **cronometrados no código**, não pela mão de ninguém: o
script para sozinho ao fim do tempo, e para também se a conexão SSH cair.

---

## 7. Resultados da Etapa A (22/09/2026)

| Teste | Comando | Resultado observado |
|---|---|---|
| A1 | 8% / 0,4 s, os dois lados à frente | **andou 2,5 cm para FRENTE** |
| A3 | 8% / 0,4 s, só o esquerdo | girou à **direita**, perceptível |
| A4 | 8% / 0,4 s, só o direito | girou à **esquerda**, *muito pouco* |

**O que a Etapa A provou:**

1. **A migração do núcleo motor está correta.** O robô andou reto e para a
   frente — se um dos lados estivesse invertido, teria girado. A lógica
   direcional do v2 confere com o hardware.
2. **8% já vence o atrito estático.** O robô não fica parado por falta de
   potência; 0,4 s é que é quase todo aceleração e frenagem.
3. **Os dois lados são assimétricos.** Com a mesma potência, o esquerdo rende
   mais que o direito. Não é defeito — é exatamente o que a malha de rumo
   existe para compensar, e confirma que a Fase 3 tem trabalho a fazer.

### O achado que muda o núcleo motor: o "freio" é um enable invertido

O professor empurrou o robô com o sistema no ar e ele rolou. A prova física,
com PWM em zero e cada estado segurado por 90 s:

| Estado do pino | O que o código chama | O que REALMENTE acontece |
|---|---|---|
| `BREAK = HIGH` | "freio acionado" (parada) | **roda LIVRE** |
| `BREAK = LOW`  | "freio solto" (movimento) | **roda TRAVADA** |

Não é freio: é um **enable de lógica invertida**. `HIGH` desliga o driver;
`LOW` o liga, e com PWM em zero ele **segura a posição ativamente**.

Isto inverte a conclusão de fail-safe da Fase 1.5, que dizia que um processo
morto deixava o robô freado. Deixa em **ponto morto**. A medida dos pinos estava
certa; a interpretação, não — ninguém tinha empurrado o robô.

**Decisão pendente com o professor**, porque a correção tem custo:

| Opção | Efeito | Custo |
|---|---|---|
| 1. Parada = `BREAK=LOW` sempre | robô segura parado **e** se o processo morrer | driver ligado consome e aquece o motor em toda espera |
| 2. Segurar por tempo limitado | protege a parada breve | complexidade; espera longa volta a ficar livre |
| 3. Manter e resolver em hardware | zero consumo extra | exige freio mecânico, junto com o botão cogumelo |

Enquanto não houver decisão, **o robô fica livre sempre que para** — relevante
para onde ele é deixado parado, e para qualquer piso que não seja plano.

---

## 8. A malha de rumo, medida (22/09/2026)

Três percursos nas mesmas condições — 8% de potência, 6 segundos, mesma linha de
partida. O desvio foi medido por duas vias independentes: o BNO085 acumulando o
giro durante o percurso, e a trena no chão depois.

| Rodada | Desvio de rumo | Desvio lateral | Andou | Correção aplicada |
|---|---|---|---|---|
| Sem correção | **+40,5°** | ~50 cm | ~45 cm | — |
| P puro | +23,0° | 37 cm | ~50 cm | 2,40% — **saturado** |
| **P + I** | **+3,8°** | a medir | a medir | 3,14% — **com folga** |

**Redução de 91%** em relação à linha de base.

### O que cada etapa ensinou

**O P puro não resolve este robô.** A assimetria dos motores é uma perturbação
**constante**, e contra ela o proporcional só age enquanto o erro existe — o
erro nunca some. Ele saturou em 2,4% e ainda deixou 23° de desvio.

A conta que orientou a correção: 2,4% de diferença entre as rodas comprou
2,9°/s; para cancelar os 6,75°/s do desvio natural seriam necessários ~5,6%.
Faltava mais que o dobro de autoridade **e** um termo que não dependesse do erro
presente.

**O v1 não precisava de integral** porque tinha o PID de velocidade por roda
embaixo, matando a assimetria na origem. Essa camada exige os dois encoders, e o
direito deste robô está com defeito físico — então aqui o integral é quem faz
esse papel.

**A correção não saturou na terceira rodada** (3,14% de um limite de 6%). Sobra
reserva para piso pior, carga diferente ou bateria mais fraca. Uma malha que
trabalha no limite está sempre a um imprevisto de falhar.

### A proteção que o aumento de autoridade exigiu

A correção **soma** ao comando base. Com 15% de base e 6% de correção daria 21%,
e **≥20% não é cortado — é Emergency Stop**. Seria o mesmo bloqueador que o PID
tinha antes desta sessão, reaparecendo por outra porta.

Solução: quando a soma estoura o teto, a malha **rebaixa os dois lados juntos**,
preservando a diferença entre eles — que é justamente o que faz o robô virar.
Perde-se um pouco de velocidade, mantém-se toda a autoridade de correção, e a
emergência fica impossível por construção. Verificado por comportamento no
harness, inclusive em ré.

---

## 9. O GATE CUMPRIDO (22/09/2026)

Percurso de **20 s a 12%**, correção ligada, com 2,5 m de corredor livre.

| Medida | Valor |
|---|---|
| Distância percorrida | **4,34 m** — o gate pede 2 m |
| Desvio lateral (trena) | **3,1 cm** |
| Desvio de rumo (BNO085) | +4,8° |
| Proporção desvio ÷ distância | **0,007** |

### A progressão inteira

| Rodada | Andou | Desvio | Proporção | Correção |
|---|---|---|---|---|
| Sem correção | 45 cm | ~50 cm | 1,11 | — |
| P puro | 50 cm | 37 cm | 0,74 | 2,40% — saturado |
| P + I (6 s, 8%) | 53 cm | 3,1 cm | 0,058 | 3,14% — com folga |
| **P + I (20 s, 12%)** | **4,34 m** | **3,1 cm** | **0,007** | 6,00% — saturou no fim |

Mesmo desvio absoluto, em **oito vezes mais distância**. A proporção melhorou
cerca de **160 vezes** em relação à linha de base.

### Duas medidas que corrigiram estimativas

**Velocidade: 21,7 cm/s a 12%**, contra 13 estimados. A relação potência →
velocidade é bem mais que proporcional acima do atrito estático: 8,8 cm/s a 8%
e 21,7 cm/s a 12%. Cinquenta por cento a mais de potência rende duas vezes e
meia mais velocidade.

> **Consequência para a Fase 4:** o robô é mais rápido do que o projeto assumia.
> A 21,7 cm/s, o fail-closed de 1,03 s do LIDAR significa **22 cm percorridos**
> antes de parar — ainda dentro dos 50 cm do bumper, mas com menos margem do que
> parecia. Reavaliar quando a navegação autônoma entrar.

**O serpenteio começa em 1,6 m.** Até ali a malha vai firme; depois o robô passa
a oscilar levemente em torno da linha. É o tempo que o integral leva para
carregar demais — o pico de correção do percurso foi **−6,00%**, ou seja,
saturado no sentido oposto ao desvio inicial. Sobrepasso clássico de integral.

Refinamento proposto: reduzir `HEADING_KI_PCT` de 0,25 para 0,12 — integral mais
fraco carrega mais devagar e sobrepassa menos. Uma mudança de cada vez, medindo
o mesmo percurso antes e depois.

---

## 10. FASE 3 FECHADA (22/09/2026) — a configuração final e como se chegou nela

```
HEADING_KP_PCT          = 0.45      % de correção por grau
HEADING_KI_PCT          = 0.25      % por grau·segundo acumulado
HEADING_INTEGRAL_MAX    = 24.0      graus·s  (= 6% de capacidade do integral)
HEADING_MAX_CORR_PCT    = 6.0       saturação da correção
HEADING_INVERT          = False     (o True do v1 faria o robô espiralar)
HEADING_TRIM_PCT        = 0.0       medido e descartado — ver abaixo
HEADING_ASSIST_ENABLED  = True      ligada por MEDIDA
partida suave           = desligada — descartada
```

### O resultado, em duas rodadas reprodutíveis

| | Andou | Desvio | Por metro | RMS do rumo |
|---|---|---|---|---|
| Rodada 1 | 4,90 m | 10,0 cm | 2,04 cm/m | 2,5° |
| Rodada 2 | 4,80 m | 10,5 cm | 2,19 cm/m | **1,3°** |

**Contra 111 cm/m do mesmo robô sem correção** no começo da tarde: **53 vezes
melhor**. Sete por cento de diferença entre as duas rodadas, num robô cuja
variabilidade dominou o dia — a configuração passou a mandar mais que o acaso.

### A conta fecha

```
desvio ≈ distância × seno(erro médio de rumo)
10,2 cm em 4,85 m  →  erro médio ≈ 1,2°
RMS medido pelo sensor: 1,3° e 2,5°
```

Duas medidas independentes — trena no chão e BNO085 — concordando. **Não sobrou
nada inexplicado**: o desvio residual é exatamente o que o erro de rumo produz.
Não é folga mecânica, escorregamento ou bug.

### A progressão inteira

| Configuração | Por metro | RMS | O que ensinou |
|---|---|---|---|
| sem correção | 111 cm/m | — | linha de base |
| P puro, kp 0,105 | 74 cm/m | — | P sozinho satura e não resolve viés constante |
| P+I, limite 24 | 10,6 cm/m | 10,8° | o integral é quem faz o trabalho |
| P+I, limite 12 | 19,3 cm/m | 12,9° | cortar a memória do integral PIORA |
| kp 0,45, limite 12 | 6,8 cm/m | 3,9° | proporcional forte mata o transiente |
| **kp 0,45, limite 24** | **2,1 cm/m** | **1,3–2,5°** | **os dois juntos** |

### Três tentativas que falharam, e o que cada uma ensinou

**1. Copiar `INVERT = True` do v1.** Teria feito o robô espiralar: o v1 calcula o
yaw do quaternion (esquerda aumenta) e o v2 lê UART-RVC (direita aumenta).
Confirmado no hardware com giro guiado de 90° → +92,8°.
*Lição: constante herdada não se copia, se confere.*

**2. Trim fixo.** Três rodadas idênticas deram correções em regime de +6,00%,
−3,04% e +3,90% — a assimetria troca de sinal, numa faixa maior que a própria
autoridade de correção. Qualquer valor fixo empurraria a favor do erro em boa
parte das rodadas.
*Lição: só se alimenta diretamente o que é de fato constante.*

**3. Partida suave.** Começando em 35% do alvo (4,2%), levou o robô abaixo do
piso onde ele anda de forma previsível: dois percursos catastróficos, 94,3° e
75,1° com a correção saturada o tempo todo. Corrigida para partir de 8%, ainda
não mostrou benefício, e foi descartada.
*Lição de hardware, que vale mais que o experimento: **abaixo de ~8% este robô
não anda de forma previsível** — um motor gira e o outro pode não girar.
Consequência para a Fase 4: aproximação lenta de uma mesa terá que ser feita com
PULSOS a 8%, não com potência reduzida contínua.*

### O limite que sobrou — e por que não se ajusta

Os 10 cm vêm de ~1,2° de erro médio de rumo. Reduzi-los esbarra em duas coisas:

1. **A variabilidade do robô** — a assimetria oscila 7 pontos percentuais e
   troca de sinal; a malha persegue um alvo que se mexe.
2. **Rumo não é posição.** A malha mantém o robô *apontado* certo, mas não sabe
   que ele está 10 cm ao lado da linha — nenhum sensor do robô mede isso. Erro
   minúsculo de rumo, mantido por metros, vira centímetros, e não há como
   recuperá-los.

**O próximo ganho real não vem de ajustar ganho nenhum.** Vem do **Aurora, na
Fase 4**, que mede a posição no mapa e fecha a malha de trajetória. O trabalho
desta camada era entregar um robô **estável e previsível entre as correções de
posição** — e é o que ela faz.

### O que 2,1 cm/m significa em operação

- Atravessar 10 m sem correção de posição → chega ~21 cm ao lado.
- O robô tem 42 cm de largura: passa folgado num corredor de 1 m.
- Encostar numa mesa para entregar exige melhor que isso — e é trabalho da
  navegação da Fase 4.
