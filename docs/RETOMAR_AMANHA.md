# Retomada na Raspberry Pi — Fluxo de Desenvolvimento

> ⚠️ **Leia a seção "PROMPT DE RETOMADA", no fim, antes do resto.** As ETAPAS 0 a 3
> abaixo descrevem a preparação inicial da Pi, já concluída em 21/09/2026 — ficam como
> registro. O estado atual, as medidas de hardware e o que falta estão no prompt final
> e em `docs/SESSAO_2026-09-21.md`.
>
> Documento-guia para estabelecer o fluxo **Raspberry Pi → Cursor (SSH) → Git**.
> Complementa e atualiza o `GUIA_SETUP.md` nos pontos que mudaram na Fase 1.

---

## Respostas rápidas

**"Vou refazer na Pi o que fizemos no notebook?"**
**Não.** O código vive no Git. Hoje (notebook) empurramos para o GitHub; amanhã
(Pi) você **clona**. Nada é reescrito. A diferença é que na Pi o sistema roda em
**modo REAL** (GPIO + I2C + LIDAR), enquanto no notebook rodava em **MOCK**.
O `scripts/validate_phase1.py` continua provando a lógica em MOCK em qualquer máquina.

**"E quando eu usar a Pi 4?"**
**Mesmo fluxo, sem mudança.** Mesmo repositório e mesmo `requirements.txt`
(o `rpi-lgpio` roda em Pi 4 **e** Pi 5). Cada placa é uma máquina independente:
clona o repo, cria seu venv, instala, e o `settings.py` detecta `PI_MODEL`
automaticamente. Se você alterna entre as duas placas, basta dar `git pull` em cada.

---

## O conceito: onde o código "mora"

```
        HOJE (notebook)                       A PARTIR DE AMANHÃ
   ┌──────────────────────┐
   │  Notebook (Windows)  │  git push (1x)
   │  ~/Desktop/robo_..   │ ───────────────┐
   └──────────────────────┘                │
                                           ▼
                                  ┌──────────────────┐
                                  │     GITHUB        │  ← FONTE DA VERDADE
                                  │ robo_slam_v2 main │
                                  └──────────────────┘
                                       ▲        │ git clone / pull
                              git push │        ▼
                                  ┌──────────────────────────┐
                                  │  RASPBERRY PI 5 (ou 4)    │
                                  │  ~/robo_slam_v2           │  ← onde você
                                  │  (roda o robô de verdade) │     desenvolve
                                  └──────────────────────────┘
                                           ▲
                                           │ Cursor "Remote - SSH"
                                  ┌──────────────────────────┐
                                  │  Cursor no notebook       │  edita arquivos
                                  │  (só a tela; arquivos     │  que ESTÃO na Pi
                                  │   estão na Pi)            │
                                  └──────────────────────────┘
```

**Ideia-chave:** o **GitHub** é a fonte da verdade. A partir de amanhã, **a Pi é a
máquina de desenvolvimento** — o Cursor abre os arquivos *que estão na Pi* via SSH;
o notebook só fornece tela e teclado. Os `commit/push` passam a sair da Pi.

---

## ETAPA 0 — HOJE, no notebook (enviar o código para o GitHub)

> Faça isto antes de desligar hoje. Assim amanhã a Pi só precisa clonar.

```powershell
# No notebook, dentro de C:\Users\User\Desktop\robo_slam_v2

git init
git branch -M main
git add .
git commit -m "feat: Fase 1 (Percepção) — sensores validáveis em MOCK + loop 50Hz instrumentado"

# Criar o repositório no GitHub e enviar.
# Opção A (mais fácil) — GitHub CLI:
gh auth login                                   # autentica uma vez
gh repo create robo_slam_v2 --public --source=. --remote=origin --push

# Opção B — repositório criado manualmente em github.com (botão "New", vazio):
git remote add origin https://github.com/francenylson1/robo_slam_v2.git
git push -u origin main
```

> Posso preparar o `git init` + primeiro commit para você agora (ver fim do documento).

---

## ETAPA 1 — AMANHÃ, na Raspberry Pi 5 (preparar do zero)

> **SO recomendado: RaspiOS Lite 64-bit (sem desktop).** Menos processos = menos jitter
> (ajuda o Gate de 50Hz) e mais folga de CPU/RAM para o controle, o stream e o SLAM.
> O fluxo é todo por SSH + dashboard no navegador — o desktop na Pi seria peso morto.
> Os dois HDMI (carinha 7" / sinalização 15.6") entram só na Fase 3, via stack gráfico
> mínimo (pygame/SDL por KMSDRM ou navegador quiosque), **não** um desktop completo.

Conecte teclado/tela na Pi **ou** já entre por SSH do notebook (`ssh pi@IP_DA_PI`).
Descubra o IP com `hostname -I`. (Detalhes de SSH/IP fixo: `GUIA_SETUP.md`, Passos 4–5.)

```bash
# 1) Pacotes de sistema
sudo apt update
sudo apt install -y git python3-venv python3-pip i2c-tools

# 2) Habilitar I2C (uma vez):  Interface Options → I2C → Enable
sudo raspi-config

# 3) Clonar o projeto (a partir do GitHub)
cd ~
git clone https://github.com/francenylson1/robo_slam_v2.git
cd robo_slam_v2

# 4) Ambiente virtual (recomendado no RaspiOS Bookworm).
#    --system-site-packages deixa o venv enxergar libs de sistema (ex.: python3-opencv).
python3 -m venv --system-site-packages .venv
source .venv/bin/activate

# 5) Instalar dependências (rpi-lgpio funciona na Pi 4 e na Pi 5)
pip install -r requirements.txt
#    Se algum wheel pesado falhar (ex.: opencv), use o pacote de sistema:
#       sudo apt install -y python3-opencv   # e mantenha --system-site-packages

# 6) PROVA DE SOFTWARE — Gate da Fase 1 em MOCK (todas as verificações verdes, exit 0)
python3 scripts/validate_phase1.py
#    Aqui, NA PI, o jitter por-ciclo vira veredito real (Linux dedicado): confirme < 5ms.

# 7) PROVA DE HARDWARE — sensores no barramento I2C
i2cdetect -y 1
#    Esperado: 0x48 (ADS1115) apenas. O BNO085 migrou para UART-RVC — não
#    aparece no i2cdetect (fiação/teste: docs/BNO085_UART_RVC.md).

# 8) Rodar o sistema REAL (sem --mock) — GPIO/I2C/LIDAR ativos
python3 main.py --robot-id 1 --log DEBUG
#    Log esperado: "Ambiente: RASPBERRY PI (Pi 5) — modo real ativado."
#    Dashboard: http://IP_DA_PI:5000   (Ctrl+C para sair)
```

---

## ETAPA 2 — AMANHÃ, conectar o Cursor por SSH (desenvolver na Pi)

1. No Cursor (notebook): extensão **Remote - SSH** (Microsoft) instalada.
2. Ícone **`><`** (canto inferior esquerdo) → **Connect to Host** → `pi@IP_DA_PI`.
3. Plataforma **Linux**, senha da Pi. O Cursor instala o servidor remoto (1–2 min).
4. **File → Open Folder** → `/home/pi/robo_slam_v2`.
5. Abra o Claude Code (Ctrl+L) e cole o **prompt de retomada** (fim deste documento).

> A partir daqui, todo arquivo que você edita está **fisicamente na Pi**. O terminal
> integrado do Cursor também é o terminal da Pi — rode os testes ali.

---

## ETAPA 3 — Ciclo diário de desenvolvimento

```bash
# Início do dia (terminal do Cursor, na Pi)
cd ~/robo_slam_v2
source .venv/bin/activate
git pull origin main

# Trabalhe: Claude Code edita na Pi → você testa no terminal integrado
python3 scripts/validate_phase1.py        # regressão rápida
python3 main.py --mock --log DEBUG        # smoke sem mexer no hardware

# Commit só em milestone estável (uma por fase concluída)
git add .
git commit -m "feat: <descrição da milestone>"
git push origin main
git tag -a "fase-1-concluida" -m "Gate da Fase 1 verde (software + hardware)"
git push origin --tags
```

---

## Usando a Pi 4 (idêntico — com 2 notas)

1. Repita a **ETAPA 1** na Pi 4 (cada placa tem seu cartão, clone e venv próprios).
   Mesmo `requirements.txt`; o `rpi-lgpio` cobre as duas placas.
2. O `settings.py` detecta e loga `PI_MODEL = "Pi 4"`. Os pinos GPIO (numeração BCM)
   são iguais nas duas placas — o núcleo motor **não muda**.

> Única ressalva real (Fase 3, chassi): o PWM dos motores foi calibrado fisicamente
> no v1. Como `rpi-lgpio` usa software-PWM nas duas placas, a calibração deve se
> manter, mas confirme um teste de "linha reta 2m" em cada placa antes de fixar a frota.

---

## FIAÇÃO DO BNO085 (GY-BNO08x) — UART-RVC, cola de bancada

> Guia completo com diagrama, raspi-config, testes e troubleshooting:
> `docs/BNO085_UART_RVC.md`. Abaixo, o resumo para ter à mão ao soldar/fiar.

| Pino do GY-BNO08x | Liga em (Raspberry Pi)              | Função |
|-------------------|--------------------------------------|--------|
| **VCC**           | **3V3** — pino físico **1** (ou 17)  | Alimentação 3,3V — ⚠️ NUNCA 5V |
| **PS0**           | **3V3** — mesmo trilho do VCC        | Seletor = 1 → **ativa o modo UART-RVC** |
| **GND**           | **GND** — pino físico **6** (ou 9/14/20/25) | Terra comum |
| **PS1**           | **GND** — mesmo trilho do GND        | Seletor = 0 (explícito) |
| **SDA**           | **pino físico 10** (GPIO 15 / RXD)   | No modo RVC o SDA vira o **TX** do sensor |
| SCL / AD0 / CS / INT | — **não conectar**                | Sem função no RVC |
| RST               | — não conectar (opcional: botão p/ GND) | Reset manual (ativo baixo) |

**Regras de ouro:**
1. PS0/PS1 são lidos **somente na energização** — fiar antes de ligar;
   se mudar, desligar e ligar o módulo de novo.
2. Tudo a **3,3V** (o GPIO da Pi não tolera 5V).
3. Cabos curtos (< 20cm) e terra comum sólido.
4. Na Pi (uma vez): `sudo raspi-config` → Interface Options → Serial Port →
   login shell **NO**, hardware **YES** → reboot → deve existir `/dev/serial0`.
5. Teste rápido (bytes chegando a 100Hz, com `aa aa` a cada 19 bytes):
   ```bash
   python3 -c "
   import serial
   s = serial.Serial('/dev/serial0', 115200, timeout=1)
   print(s.read(38).hex(' '))"
   ```

---

## RPLIDAR C1 — validado no hardware em 21/09/2026

O C1 **não** fala como os A1/A2, e a biblioteca `rplidar` foi escrita para estes.
Duas diferenças, ambas já tratadas em `sensors/safety_bumper.py`:

| Item | A1 / A2 (padrão da lib) | **RPLIDAR C1** |
|---|---|---|
| Baud | 115200 | **460800** (`LIDAR_BAUDRATE` no `settings.py`) |
| Motor | `SET_PWM` (`A5 F0`) | **não implementa** — gira sozinho; controle por DTR |

Sintoma de qualquer um dos dois errados: `RPLidarException: Descriptor length
mismatch`. Com baud errado ele falha já no `get_info()`; com o `start_motor()`
padrão, os bytes da carga útil do `SET_PWM` são reinterpretados como comandos e o
protocolo sai de sincronia.

Valores medidos na Pi 5: `model=65` (0x41 = C1), firmware 1.2, health `Good`,
**~13,8 Hz** e **~275 pontos por varredura**; idade do dado no `SafetyBumper`
entre 0,001 s e 0,08 s — bem dentro de `LIDAR_FRESH_TIMEOUT_S` (0,5 s).

Teste rápido de bancada:

```bash
cd ~/robo_slam_v2 && source .venv/bin/activate
python3 -c "
from sensors.safety_bumper import SafetyBumper
import time
b = SafetyBumper(); b.start(); time.sleep(3)
print('blocked:', b.blocked_front, '| health:', b.health())
b.stop()"
```

> A primeira varredura leva ~2 s (conexão + `STOP` + DTR + revolução completa).
> Até lá, `blocked_front = True` — é o fail-closed funcionando, não um defeito.

### Provas FÍSICAS do bumper — aprovadas em 21/09/2026

Feitas com o robô montado, o operador à frente e o registro completo em
`~/bench_provas_fisicas_20260921.log` na Pi (1059 amostras a 2 Hz).

| Prova | Resultado medido |
|---|---|
| **Orientação**: 0° do C1 = frente do robô | ✅ mão à frente reportada entre **340° e 7°** — o arco de ±30° vigia a direção certa, sem correção de código |
| **Bloqueio** por obstáculo < 0,50 m | ✅ **18,5 s** contínuos a 0,22–0,29 m; libera em < 0,5 s ao afastar |
| **Fail-closed** ao perder o LIDAR | ✅ `blocked_front = True` **1,03 s** após puxar o USB |
| **Reconexão** automática | ✅ volta a `livre` sozinho **~7,3 s** após recolocar o cabo, sem reiniciar nada |

Composição do 1,03 s do fail-closed (medido cruzando o log com o `dmesg`):
**0,53 s** de dado residual que o driver ainda entrega depois do cabo sair, mais
os **0,5 s** de `LIDAR_FRESH_TIMEOUT_S`. A primeira parcela não dá para encurtar;
se um dia precisar de mais margem, o ajuste é no timeout.

Os ~7,3 s da recuperação são o esperado pelo projeto: backoff de até 5 s entre
tentativas + ~2 s da primeira varredura completa.

### Perfil angular de 360° — levantado em 21/09/2026

Fonte da geometria: `base-corpo-robo.pdf` (vista aérea da base). Base de **42 cm
de largura × 60 cm de profundidade**, C1 montado na **borda frontal, no eixo**,
e **três colunas de sustentação de 1,40 m**.

Posição prevista de cada coluna em relação ao sensor:

| Coluna | Ângulo previsto | Distância |
|---|---|---|
| 1 — imediatamente atrás do sensor | 180° | face a ~3,4 cm |
| 2 — traseira esquerda | 190° | ~51 cm |
| 3 — traseira direita | 170° | ~51 cm |

Perfil medido (mediana por grau sobre 250–300 varreduras,
`~/perfil_angular.py` e `~/reconstroi_coluna.py` na Pi):

| Medida | Resultado |
|---|---|
| **Superfície fixa** (coluna 1) | **145° a 204°** — 60° contínuos, a 3,6–5,0 cm |
| **Campo útil** do C1 no robô | **300°** (360° menos a sombra) |
| Largura vista da coluna | **4,83 cm** — o projeto prevê 4,73 cm |
| Distância da face ao sensor | **4,20 cm** |
| Centro lateral da coluna | **+0,49 cm** à direita do eixo do sensor |
| **Alinhamento do sensor** | normal da face em **181,0° ± 0,4°** — desvio de **1,0°** |
| Arco do bumper (330°–30°) | **limpo** — mínimo 119,9 cm, mediana 295,9 cm, nenhum grau com mediana < 50 cm |

**Três conclusões que mudam o que se acreditava antes:**

1. **O sensor NÃO está desalinhado.** O ajuste de reta na face plana da coluna
   (resíduo perpendicular médio de 0,118 cm) dá normal em 181,0°, ou seja, 1°
   de desvio — desprezível. O que víamos a "191°" era uma **protuberância de
   0,59 cm na face da coluna, entre 187° e 195°** (parafuso, abraçadeira ou
   cabo). Vale identificar a peça: se for cabo solto, pode se mover.
2. **A obstrução não é um ponto, é um setor de 60°.** A coluna tem 4,8 cm de
   largura a 4,2 cm do sensor — meia-largura angular de ~30°. Tudo que estiver
   além dela, naquele setor, é invisível.
3. **As colunas 2 e 3 nunca aparecem**: previstas em 170° e 190°, caem dentro da
   sombra da coluna 1. O perfil confirma — não há nenhum retorno a ~51 cm ali.

> Por que a medição isolada do "ponto mais próximo" enganava: a 4,2 cm, **1 cm de
> deslocamento lateral vale 11° de ângulo**. Qualquer conclusão sobre alinhamento
> tirada de um alvo tão perto é frágil. O que resolveu foi reconstruir a
> superfície em coordenadas cartesianas e ajustar a face inteira.

**O que fazer com isso (Fase 4 — SLAM/mapeamento):** mascarar o setor
**140°–210°** e descartar retornos abaixo de ~15 cm, senão as colunas viram
obstáculos permanentes que andam junto com o robô.

> ⚠️ **Nunca aplique o raio mínimo no caminho da segurança.** No bumper, ignorar
> retornos muito próximos seria falhar *aberto* — um pé encostado no robô
> deixaria de bloquear. A máscara é só para mapeamento. O arco do bumper está
> comprovadamente limpo e não precisa de filtro nenhum.

---

## FASE 1.5 (Blindagem) — FECHADA em 21/09/2026

Serviço systemd instalado e as três camadas de proteção provadas no hardware.

| Prova | Resultado |
|---|---|
| Serviço sobe e arma o watchdog | ✅ `[Watchdog] Armado (modo systemd)` — o `sd_notify` funciona |
| **Camada 2** — processo MORTO (`SIGKILL`) | ✅ volta sozinho; processo novo em ~2 s, serviço pronto em **8,2 s** |
| **Camada 1** — processo TRAVADO (`SIGSTOP`) | ✅ `Watchdog timeout (limit 5s)!` → `Killing process with SIGABRT` → pronto em **7,6 s** |
| Estado dos motores após `SIGKILL` | ⚠️ **os pinos mantêm o nível — mas o efeito era o oposto do que concluímos.** Ver a correção de 22/09 abaixo |
| Sobe sozinho no boot | ✅ `NRestarts: 0`, telemetria viva, LIDAR conectado |
| Dashboard | ✅ HTTP 200; `/api/status` com `watchdog.armed: true` |

**A camada 1 é a que justifica a fase.** Um processo *travado* continua vivo, então
`Restart=always` nunca o pegaria. O que o pega é o loop de 50 Hz deixar de alimentar
o `WATCHDOG=1` — e foi exatamente isso que o `SIGSTOP` provou.

> **Correção de expectativa:** a documentação anterior dizia "volta sozinho em ~2 s".
> São dois números diferentes: o processo é relançado em 2 s (`RestartSec`), mas o
> serviço só fica **pronto** em ~8 s, porque `Type=notify` espera o `READY=1`, que só
> vem depois de conectar o LIDAR, subir o waitress e iniciar o loop.

### Fail-safe dos motores — medido, não suposto

Após um `SIGKILL` (sem `GPIO.cleanup()`), os pinos **mantêm o estado**:

```
 6: op dh pn | hi   ← BREAK_E — freio ACIONADO
24: op dh pn | hi   ← BREAK_D — freio ACIONADO
18: op dl pn | lo   ← PWM_E — velocidade ZERO
12: op dl pn | lo   ← PWM_D — velocidade ZERO
```

### ⚠️ CORREÇÃO (22/09/2026) — a conclusão acima estava INVERTIDA

A medida dos pinos estava certa. **A interpretação, não.** Em 22/09 o professor
empurrou o robô com o sistema no ar, e ele rolou. A prova física, feita com PWM
em zero e cada estado segurado por 90 s:

| Estado do pino | O que o código chama | O que REALMENTE acontece |
|---|---|---|
| `BREAK = HIGH` | "freio acionado" (parada) | **roda LIVRE** |
| `BREAK = LOW`  | "freio solto" (movimento) | **roda TRAVADA** |

O pino não é um freio: é um **enable de lógica invertida**. `HIGH` desliga o
driver e a roda fica solta; `LOW` liga o driver, e com PWM em zero ele segura a
posição ativamente.

Consequências:

1. Hoje o robô fica **livre toda vez que para** — em piso plano fica pelo atrito;
   em rampa, ou se alguém esbarrar, ele anda.
2. Um processo morto deixa o robô em **ponto morto**, não freado. É o oposto do
   que este documento afirmava.
3. A correção (estado de parada = `BREAK=LOW`) melhora os dois casos, porque os
   pinos mantêm o último nível após um `SIGKILL` — mas **tem custo de bateria**
   (driver ligado segurando posição consome e aquece). **Decisão pendente com o
   professor**; ver `docs/FASE3_PLANO.md`.

> **A lição:** ler o nível de um pino não prova o efeito físico. Foi preciso
> alguém empurrar o robô. Toda afirmação de segurança precisa da prova no mundo,
> não no barramento.

### Bug corrigido no caminho

O `deploy/frota-robo.service` fixava `User=pi` e `/home/pi/robo_slam_v2`. Nesta Pi o
usuário é `amd` — o serviço falharia ao subir, e o mesmo valeria para qualquer placa
da frota com outro usuário. O arquivo virou **modelo** (`__USER__`,
`__PROJECT_DIR__`) e o `install_service.sh` substitui pelos valores reais.

---

## DECISÃO DE SEQUÊNCIA DOS SENSORES (21/09/2026) — aprovada pelo professor

Os dois sensores que faltam são ligados **depois**, cada um com seu prazo. Nenhum
deles bloqueia a Fase 2.

| Sensor | Quando ligar | Prazo limite | Por quê |
|---|---|---|---|
| **BNO085** (rumo) | ✅ **LIGADO E VALIDADO em 21/09/2026** | cumprido | 100,0 Hz, zero erro de checksum, erro de retorno de 0,63° |
| **ADS1115** (bateria) | Depois do BNO085 | **Antes da Fase 4** | Na Fase 4 são 30 min de operação autônoma sem supervisão; pack de hoverboard descarregado fundo se danifica |

**Por que dá para adiar os dois:** nenhum dos dois tem ação sobre o comportamento.
O rumo só vai para a telemetria (o passo 3 do `control_loop` ainda é um comentário) e
a bateria também — não há corte por tensão baixa, nem bloqueio, nem nada que leia
`state["battery"]` para decidir algo. Ambos são *fail-soft*: sua ausência não trava o
robô, ao contrário do LIDAR, que é *fail-closed*.

**Por que "para o final" seria tarde demais no caso do ADS1115:** na Fase 3 os testes
são curtos e supervisionados — multímetro resolve. Na Fase 4 os robôs andam sozinhos
por 30 minutos; sem telemetria de tensão, ninguém percebe a descarga profunda. O
trabalho de fiar é pequeno (I²C, dois fios mais alimentação); o que dá trabalho é
acertar o divisor resistivo e calibrar contra o multímetro.

### Placar honesto das provas físicas

| Fase | Prova | Estado |
|---|---|---|
| 1 | LIDAR / bumper (bloqueio, fail-closed, reconexão) | ✅ provado 21/09 |
| 1 | Bateria (±0,5 V contra multímetro) | ⏸️ **adiado por decisão** — antes da Fase 4 |
| 1 | BNO085 (3 níveis de teste) | ✅ **provado 21/09** — 100,0 Hz, checksum 0%, retorno 0,63° |
| 1.5 | Watchdog, systemd, fail-safe dos motores | ✅ provado 21/09 |

A **Fase 1.5 está fechada de verdade** — watchdog e systemd não dependem de sensor
nenhum. A **Fase 1 fica com dois itens em aberto por decisão de sequência**, não por
falha: ambos foram validados em MOCK (39/39) e só aguardam o hardware.

---

## BNO085 — o que faz, e quando é preciso ligar

**O que faz:** entrega o Yaw (rumo) a 100 Hz por UART-RVC, para o robô andar em
linha reta. Motores de hoverboard com drivers independentes sempre têm um lado
ligeiramente mais rápido; sem realimentação de rumo, um comando "reto" descreve
uma curva.

**O que ele faz HOJE: nada que afete o movimento.** O loop lê
`state["yaw_error"] = heading.get_yaw_error()` e publica na telemetria, mas o passo 3
de `core/control_loop.py` — "CORREÇÃO DE RUMO" — ainda é só um comentário
(`Implementação futura: micro-ajuste diferencial baseado em yaw_error`). Nenhum
motor é comandado a partir do rumo.

**A ausência dele é inofensiva.** Diferente do LIDAR, que é *fail-closed* (sem dado
→ robô bloqueado), o BNO085 é *fail-soft*: `healthy()` devolve `True` quando a porta
não está aberta, e nada no sistema age sobre o rumo. Verificado em 21/09/2026:
`/dev/serial0` recebeu **0 bytes** (sensor não ligado) e o serviço rodou normalmente.

**Quando passa a ser necessário: Fase 3**, cujo gate é justamente
**"linha reta 2 m"**. É ali que o rumo fecha a malha. Dá para chegar perto calibrando
o PWM de cada lado na tentativa e erro, mas quem sustenta a linha reta ao longo do
tempo — com bateria caindo, carga mudando, piso variando — é o BNO085.

Na Fase 4 ele ajuda, mas o SLAM em si vem do Slamtec Aurora, que estima a própria
pose.

**Recomendação prática:** ligar o BNO085 **na mesma ida à bancada** da correção do
chassi. Não há urgência, mas fiar e rodar os 3 níveis de teste agora tira uma
incógnita da Fase 3. Lembre que **PS0/PS1 só são lidos na energização** — fiar antes
de ligar. A serial já está habilitada (`/dev/serial0` → `ttyAMA10`).

---

## MOCK vs REAL — o que muda entre notebook e Pi

| Aspecto            | Notebook (hoje)        | Raspberry Pi (amanhã)               |
|--------------------|------------------------|-------------------------------------|
| `MOCK_MODE`        | `True` (auto)          | `False` (auto; `--mock` força MOCK) |
| GPIO / PWM         | desativado             | real, via `rpi-lgpio`               |
| Bateria (ADS1115)  | tensão simulada        | leitura I2C real                    |
| Bumper (RPLIDAR)   | varredura sintética    | LIDAR físico em `/dev/ttyUSB0`      |
| Heading (BNO085)   | yaw simulado           | UART-RVC 100Hz em /dev/serial0      |
| `validate_phase1`  | jitter informativo     | jitter = **veredito** (< 5ms)       |

---




## PROMPT DE RETOMADA — colar no Claude Code no início da próxima sessão

> Atualizado em 27/10/2026, ~18h30 (giro e parada afinados; ambiente novo
> pelo painel do começo ao fim; PLANTA FINA no /mapa com régua e desenho por
> medida — aprovada e conferida com trena). Próxima sessão: bloco B (modo
> sombra ao vivo) no PC, ou a porta de 85,5 cm (P3-corredor1) com o robô.

```
Olá! Retomando a Frota Mista v2 (robô garçom, Projeto Aluno Maker Digital).

COMO FALAR COMIGO: eu NÃO consigo ler mensagens longas no terminal — elas cortam.
Responda no terminal em poucas linhas. Explicações, tabelas, roteiros de bancada,
diagnósticos e conversas de decisão vão DIRETO para uma PÁGINA PUBLICADA
(Artifact), e o terminal só avisa com o link. Na bancada, UM PASSO POR MENSAGEM.
Seja OBJETIVO. Se uma instrução for ambígua, PERGUNTE. MEÇA antes de afirmar.

LEIA PRIMEIRO, nesta ordem:
  docs/PRD.md §0  — O CONTRATO DA V1 (decidido por mim em 02/10). Toda ideia
                    nova: dizer a qual objetivo serve ou marcar como futura.
  docs/SESSAO_2026-10-27.md · docs/SESSAO_2026-10-26.md · docs/SESSAO_2026-10-23.md
  docs/SPEC.md · docs/WORKFLOW.md
  Páginas: PLANTA FINA (27/10: problema, protótipo, proposta aprovada)
             https://claude.ai/artifact/7dCczMP3gYJLgVjmRPpw8R
           DIA 26/10 (6º ano: corredor; PLANO ATÉ A V1; L1/L2; bumper;
             margem; piloto do giro) https://claude.ai/artifact/GKuLFxzyxS42kzJL8N1ya8
           DIA 23/10 (P1b/P2, a caça à lentidão do Aurora, A1/A2, P3)
             https://claude.ai/artifact/R14dEDNvPr5aQYYEFibC3p
           DIA 22/10 (braço, coleta, prova dos 2 C1, N1–N6)
             https://claude.ai/artifact/EZfVuHfm1hLKQAhp2boMuQ
           TESTE DO MODO SOMBRA (5 etapas + E1–E5, 21/10)
             https://claude.ai/artifact/7PZiByH7yf4iktCmmZ3VMM
           bancada de 20/10 + 2º C1 https://claude.ai/artifact/PmTvehg9VDVKFkFKkmFDJL
           modo sombra https://claude.ai/artifact/HVNv8rJfHC6FK6Ys9amPJk
           preparação de 06/10 (expectativa + o feedback que ele vai dar)
             https://claude.ai/artifact/7UN9WZM4g6vhPERbVjCJYg
           base nova (estrutura + medição do antes)
             https://claude.ai/artifact/KjBi1hu2g5bXiV7fxHfDdn

ONDE O PROJETO ESTÁ:
  Fases 1, 1.5, 2, 3 ✅ · FASE 4 em andamento (robô 1 com Aurora).
  - PACOTE DE AMBIENTE: Etapa A (escolher/trocar, página /ambientes; trocar
    REINICIA o serviço) e Etapa B (MAPEAR PELO PAINEL: 1 passada para mapear →
    medir a fita → 2 passadas de coleta → concluir na fita; gera mapa, planta
    DA COLETA, mapas dos C1 e nota) — APROVADO na sala em 02/10 ("Sala 2":
    conferência 0,8 cm; nota C1 1,45 m 3,3 cm, os dois 2,4 cm; missões 3–8 cm).
  - Ambientes na Pi: sala_lab_20260925 (pronto, ATIVO; mapas C1 REFEITOS em
    22/10 com as passadas A/B e o C1 de cima: c1_143 + c1_22, nota 3,4 cm os
    dois; o antigo em antes-2026-10-22/),
    corredor_20261001 (rascunho), sala_2_20261002 (pronto).
  - MODO SOMBRA (objetivo 1.2): decidido S1–S4 (só C1 22 cm agora; Sala do lab;
    ligado sempre com chave; fantasma no /mapa + números no painel).
    slam/sombra.py + scripts/sombra_replay.py feitos (replay: 3,6 cm, mas ~0,7%
    >30 cm SEM perceber). AINDA NÃO ligado ao serviço.
  - BNO gira no sentido CONTRÁRIO ao rumo do Aurora (razão −0,99).
  - BASE NOVA PRONTA (20/10): reforço base–corpo soldado; 1 rodízio frente +
    1 trás, centrados, RÍGIDOS (sem mola). Testado 2 frente + 1 trás: pior
    (5 apoios, um fica no ar) → voltou a 1 + 1 ajustado. Giro a 8% sai dos
    rodízios retos nos dois lados com bateria cheia (~40 V; a 36,8 V travava).
    Motores simétricos (rodas no ar 92/92 × 88/88). Freada: meta ok (base
    0,87–1,08°); balanço lateral com empurrão acima da meta (4 Hz, 5–7°).
  - SUPORTE DO AURORA: tubo Ø35 × 37 cm, base do Aurora a 1,49–1,50 m; tubo a
    24,5 cm da traseira (5,5 cm atrás do centro) e 0,5 cm à direita.
  - BRAÇO DO AURORA (22/10, ce0d36a): (−0,032; +0,047) = média dos 2 sentidos
    (eles discordam ~5,6 cm na lateral: uma roda rende mais). 5 missões à
    base: trena 4,9 frente / 2,7 dir, e o robô SABE (diz 4–8 cm): o erro é
    onde ele PARA (antecipa 6 cm, base aceita 10), não a pose.
  - 2 C1 SEM AURORA (22/10, replay mapa A → teste B, 1.003 voltas): os dois
    3,2 cm mediana, p90 7,0, pior 12,5, 0 perdas; só 1,43 m 3,8; só 22 cm 3,9.
    Gabarito = Aurora. Modo sombra AINDA NÃO ligado ao serviço.
  - NAVE-MÃE N1–N5 (c53b28f): mapa_c1 monta c1_143 com o C1 de cima, nota com
    voltas reais, PLANTA pelo C1 de cima quando não há laser; montagem dos C1
    POR ROBÔ em /etc/frota.conf (FROTA_C1_GIRO_DEG=-1.8; FROTA_C1_TOPO_X_M
    -0.165, _Y_M -0.005, _GIRO_DEG -1.5); pose ≤ 0,12 s; sombra 150–222°;
    Rastreador(g22, g143). Scripts fora do serviço precisam das FROTA_C1_* no
    ambiente (ver SESSAO_2026-10-22 §6).
  - AURORA LENTO — RESOLVIDO (23/10, SESSAO_2026-10-23 §3–4): era a
    BIBLIOTECA DO SDK NA PI acumulando trabalho com o robô andando (sonda que
    só lê a pose: CPU 9 → 58 % em 12 min, cabo constante). NÃO era calor nem
    corredor nem o aparelho. A2 (6dad453): o serviço renova a sessão a cada
    120 s sem buraco → 25 min a 585–596 poses/min, 0 silêncios, 0 saltos.
    A1 (0edf429): modo só localização depois do Localizar (fica).
  - P1b + P2 (f5455ee): planta laser × C1 de cima conferida volta a volta
    (> 2 % fora → C1 de cima + aviso); nota principal "acompanhando"
    (Rastreador, 8 trechos × 30 voltas), "a frio" ao lado.
  - maker_corredor_20261022: coleta de 23/10; nota 2,4 cm / p90 6,3 / 0
    perdas; planta do C1 de cima com L1 + L2 (26/10; backups antes-2026-10-26/
    e antes-L2-2026-10-26/); áreas desenhadas (nav v8: M1 = escada; POIs
    P1–P5, P1-bancada, P2-curva1, P3-corredor1 sem caminho = porta 85,5 cm);
    PRONTO e ATIVO. nav v8: M2/M5 ajustadas por ele (mesas no lugar).
  - 26/10 (SESSAO_2026-10-26): L2 tira fantasmas da coleta (fração < 12 %);
    bumper firme: chanfro do planejador em numpy + LeitorC1 em bloco que
    realinha (a iter_scans da rplidar NÃO é mais usada); margem: planeja 0,50,
    vigia cancela < 0,42 (NAV_TOLERANCIA_M); GIRO > 10° = PILOTO DE
    VELOCIDADE (PI no BNO, MISSAO_PILOTO_*), pulsos só no acerto fino.
    No chão: 15–74° em 1,8–4,7 s; um 132° travou a 12 % → pulsos → 14 s.
  - 27/10 (SESSAO_2026-10-27): o 132° era a largada após 1 h parado (rodízios),
    não bateria. Preso no teto → pulsos em 1 s; pulso curto sem render sobe a
    força. Parada antecipada pela velocidade das RODAS (6 cm × (v/0,20)²): base
    5 cm (era 7). A 8 % o robô anda ~13–20 cm/s. AMBIENTE NOVO PELO PAINEL ok
    (sala_lab_teste_painel_20261027: nota 2,6/4,4, fita 2,0 cm, 16 missões
    3–8 cm). PLANTA FINA (slam/planta_fina.py: fino.png + paredes medidas; no
    fim de todo mapeamento) — /mapa com grade 50 cm, régua, encaixe 5 cm,
    "Posicionar pelas paredes"; régua = trena; P5/M2/M5 conferidas. /ambientes
    espera o reinício e diz "Pronto". Emenda de piso na sala-lab-teste: roda
    esquerda patinou 2× no giro (ele empurrou) — OBSERVAR (§6 da sessão).
  - ⚠️ A BATERIA SEPARADA DO AURORA acabou 2× em 23/10 (18:20, 18:45): ele
    some da rede sem aviso (eth0 NO-CARRIER).
  - 2º C1 INSTALADO (21/10): plaquinha a 1,43 m = PADRÃO DA FROTA (±1 cm;
    substitui o "1,45 m" do PRD/v_2_redondo); 11 cm ATRÁS do centro do tubo →
    (−0,165; −0,005) m do centro, 0° para a frente (97% das voltas caem nas
    paredes do mapa c1_145 na pose do Aurora; giro 0 ± 1°). Sombra do tubo
    353°–14° a ~11 cm. Séries: cima 0e84a5ca…, 22 cm 6ac67406….
  - BUMPER PELA SÉRIE (f7857e9): FROTA_LIDAR_PORT em /etc/frota.conf; com 2
    ttyUSB e nada configurado o bumper RECUSA ligar. No reboot de 21/10 os
    nomes TROCARAM (cima = ttyUSB0) — provado que era preciso.
  - LEITOR DO C1 DE CIMA (43bc965, sensors/c1_topo.py, E1–E5): thread própria
    fora da segurança; FROTA_LIDAR_TOPO_PORT; campo "c143" no gravador, 1/s,
    tubo 348–20° e <15 cm fora, cru. Provado: tirar o USB não afeta o bumper;
    recolocar reconecta e volta a gravar.
  - ⚠️ scripts/perfil_lidar.py e reconstroi_coluna.py abrem /dev/ttyUSB0 fixo
    (hoje é o C1 de CIMA) — passar a porta como argumento antes de usar.
  - O robô 1 fica com os 2 C1 permanentes, navegando pelo Aurora; o de cima
    grava o mapa da frota e é o fiscal (página
    https://claude.ai/artifact/KyTkWVhpF2DWwewFGtVXuG). Ambientes existentes
    vão precisar de NOVA COLETA com o C1 de cima.
  - A Pi perdeu energia às 17:06 de 20/10 (journal termina seco) — perguntar.
  - BATERIA lê 0,87 V a menos (36,77 × 35,90). Coluna atrás do C1 22 cm em
    160–217° (máscara C1_SOMBRA 140–210 → ~150–222, com aprovação). Cabo do
    C1 soltou 2× em 20/10 (preso com abraçadeira). BNO acordou mudo de novo
    (corte de 15 s em 05/10; proposta: aumentar BNO_POWER_OFF_S).

REGRESSÃO: CINCO harnesses antes de cada commit (docs/WORKFLOW.md).
  validate_phase1 129 · phase2 75 · phase25 17 · phase3 37 · phase4 432
  (instáveis por tempo, repetir: jitter da fase 1; "Sessão nova que DISCORDA"
  da fase 4 — investigar)
  No PC: `py -I scripts/validate_phaseN.py` (não há .venv nem `python` no PC).
  Scripts de análise no PC ou na Pi: exportar as FROTA_C1_* do robô 1 antes.
  (no PC o jitter da fase 1 às vezes falha por oscilação do Windows: repetir).

PLANO DA PRÓXIMA SESSÃO (28/10; plano até a V1 na página de 26/10, Parte 2:
A nave-mãe → B sombra ao vivo (bancada 03/11) → C navegação (04–10/11) →
D robô 2 (bancada dele, sugerido 29–30/10) → E prova 17–18/11):
  BLOCO A: FEITO (sessão 1 em 26/10; sessão 2 em 27/10). Falta só o texto em
     inglês para a Slamtec (quando ele pedir).
  0. Bateria do Aurora carregada; "Localizar na fita". Ativo: maker_corredor.
  1. ITEM "PORTA" NO /mapa (APROVADO 27/10, ~2 h): a margem 0,50 de cada lado
     exige vão ≥ 1,00 m — porta de 85 cm NUNCA passa, com qualquer planta.
     Medidas dele: 85 cm batente a batente, parede/batente 20 cm de fundo;
     a FOLHA fica aberta do lado DIREITO olhando para a rede (tira alguns cm:
     medir o vão livre na planta fina — o C1 de cima vê a folha). Projeto:
     operador marca os 2 batentes na planta fina; rota força ponto 80 cm antes
     e 80 cm depois no eixo da porta, reta, sem giro no vão, a 8 %; só dentro
     da porta a margem cai para meia largura + folga de localização (~0,30)
     e o vigia acompanha; fora dela segue 0,50. Bumper ok se centrado ±10 cm.
     Recusar porta estreita demais para o robô (largura + 2 × folga mínima).
     GENÉRICO para qualquer ambiente/robô (frota Ø46). Prova: P3-corredor1.
  2. Bloco B: modo sombra ao vivo (sombra_proc.py, processo à parte; fantasma
     no /mapa; medidor de dúvida no "perdido"); robô sem Aurora perdido PARA.
     ~2 h de código no PC + 1–1,5 h de bancada (03/11).
  3. Observar a EMENDA DE PISO (sessão 27/10 §6); se repetir, a proposta de
     patinação (encoder × BNO → sair da emenda) já está escrita.
  4. Parada: mais chegadas à base para ver se a antecipação de ~3 cm a 8 %
     pode cair (mediana 5 cm; meta ≤ 8).
  5. Levar corredor_longo.py / fantasma.py do scratchpad para scripts/.
  Pendentes menores: bateria 2 pontos; corte do BNO; PRD 1,45 → 1,43 m.

MODO SOMBRA (adiado desde 06/10; o plano continua valendo):
  PC (~3h30, sem o robô): harness primeiro → slam/sombra_proc.py (PROCESSO à
     parte: GIL) → o serviço entrega cada varredura do C1 (hoje o
     bumper.feed_scan só chama bumper.recorder), semeia a sombra quando
     "Localizar na fita" dá verde e recoloca ao perder (conta perdas) →
     telemetria "sombra" + fantasma no /mapa + números no painel + registro 1/s.
  BANCADA (~1h30, com ele): conferir BNO vivo + "Localizar na fita" → medir
     CPU e jitter na Pi → missões com o fantasma: sala arrumada, depois
     cadeiras fora do lugar / mochila / gente andando. Ele anota o que
     aconteceu e quando, olha o fantasma, mede com trena em paradas; decidimos
     juntos o erro aceitável e o que fazer ao se perder.
  Expectativa dita a ele: o 22 cm sozinho funciona quase sempre mas NÃO é
     seguro sozinho (vê pernas); o veredito vem com o 1,45 m (~10/10).
  Depois: mapear o corredor pelo painel; aviso "reiniciando" da página
  Ambientes (F5); robô 1 estável (cancelações de 01/10, "pose velha");
  desenho da PAUSA no obstáculo (objetivo 3); margem com a bandeja (10,3 cm
  de folga); E-Stop físico; robô 2 (C1 novos ~10/10).

CONVENÇÕES QUE CUSTARAM CARO:
  - "Robô na fita" = a FRENTE da base na linha; a pose é do CENTRO.
  - A fita no pacote é o PONTO DO AURORA medido; o main converte para o centro.
  - Laser do Aurora: origem 2,5 cm à frente / 3,0 cm à direita do ponto do Aurora.
  - Um cliente só no Aurora para COMANDOS: script de bancada que zera/carrega
    mapa = serviço PARADO. Uma 2ª sessão SÓ DE LEITURA (sonda) com o serviço
    no ar funcionou bem em 23/10.
  - Diagnóstico de lentidão: "no relógio do Aurora" no log NÃO prova que o
    atraso é do aparelho (pose que chega atrasada na Pi aparece igual).
    Separar por CPU POR PROCESSO + sonda em processo à parte.
  - NUNCA chamar o SDK para gerar planta dentro do serviço (SIGSEGV em 02/10).
    Cálculo pesado em Python (mapas, nota, sombra) = PROCESSO à parte.
  - scipy da Pi não importa com o numpy 2 do .venv: usar numpy puro.
  - Mapear: pelo painel (Ambientes → Novo ambiente). Começar e terminar a
    passada 1 na fita (recomendado); a fita pode ser ajustada à mão.
  - Bumper: 20 cm girando/parado, 30 na aproximação lenta, 50 no reto/joystick.
  - C1: ângulo HORÁRIO; 30 cm à frente do centro; sombra 150–222°; giro no
    suporte por robô (FROTA_C1_GIRO_DEG). C1 de cima idem (FROTA_C1_TOPO_*).
  - Acordar o controle PG-9076 pelo HOME.

REGRAS INVIOLÁVEIS:
  - Regra Nº 0 (≤15% / ≥20% → Emergency Stop); missão com teto 12% e roda ≥ 8%.
    Só joystick, malha de rumo, MISSÃO e bancada chamam set_speed; web/, fleet/,
    tower/, slam/ambientes|mapeamento|mapa_c1|sombra nunca (testado).
  - NÃO alterar pinos/PID/lógica de core/motor_driver.py sem discutir.
  - /api/stop fora do login · telemetria parada = visível e calada.
  - Conversa de desenho ANTES de código em peça nova que mexa em segurança;
    MEDIR antes de corrigir; harness que falha com o código antigo.

NA BANCADA:
  - Parar o robô = `sudo systemctl stop frota-rosto frota-robo` + conferir os dois
    + fuser /dev/gpiochip0 vazio. Nunca `authorized=0` em porta USB com o robô no ar.
  - Reiniciar o frota-robo desfaz a localização: "Localizar na fita" de novo.
  - Trocar de ambiente reinicia (~8 s); recarregar a página Ambientes depois.

A PI DO ROBÔ: ssh robo1 (192.168.0.185, ou 100.84.87.44 pelo Tailscale; amd).
  Dashboard :5000 (operador; senha fixa). Aurora no eth0 (192.168.11.1).
  Ao ligar: conferir o C1 (/dev/ttyUSB0), o BNO (pode acordar mudo) e
  "Localizar na fita". Script de bancada para os serviços; ao religar,
  localizar de novo. Gravação com prazo: só dizer "gravando" depois de ver a
  linha do script (a parada dos serviços pode levar ~1 min).

Por onde começamos?
```
