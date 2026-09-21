# Retomada na Raspberry Pi — Fluxo de Desenvolvimento

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
| Estado dos motores após `SIGKILL` | ✅ **freios seguem acionados** (medido, ver abaixo) |
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

Um processo morto deixa o robô **freado e parado**, não solto. Confirmar com
multímetro quando o estágio de potência estiver ligado.

### Bug corrigido no caminho

O `deploy/frota-robo.service` fixava `User=pi` e `/home/pi/robo_slam_v2`. Nesta Pi o
usuário é `amd` — o serviço falharia ao subir, e o mesmo valeria para qualquer placa
da frota com outro usuário. O arquivo virou **modelo** (`__USER__`,
`__PROJECT_DIR__`) e o `install_service.sh` substitui pelos valores reais.

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

## PROMPT DE RETOMADA (cole no Claude Code amanhã, na Pi)

```
Olá Claude Code! Estou agora conectado via Cursor Remote-SSH na minha Raspberry Pi
(robô da Frota Mista v2). Leia docs/RETOMAR_AMANHA.md, PROMPT_INICIAL.md e
docs/PROPOSTA_PRODUCAO_COMERCIAL.md (plano aprovado) para o contexto completo.

Estado atual: a Fase 1 (Percepção) foi fechada em MOCK no notebook e está no Git —
sensores com injeção de valores (read_once/feed_scan/set_mock_*), loop 50Hz em
core/control_loop.py (deadline absoluto + medição de jitter) e o harness
scripts/validate_phase1.py (todas as verificações verdes em MOCK). GPIO migrado para
rpi-lgpio (Pi 4 + Pi 5). Da Fase 1.5 (Blindagem), JÁ IMPLEMENTADO E VALIDADO EM MOCK:
(a) bumper FAIL-CLOSED — sem varredura fresca do LIDAR por > 0.5s → blocked_front =
True, reconexão automática (backoff), saúde na telemetria; (b) WATCHDOG
(core/watchdog.py) alimentado pelo loop 50Hz — modos systemd/device/mock;
(c) systemd pronto em deploy/frota-robo.service + scripts/install_service.sh
(Type=notify, WatchdogSec=5, Restart=always, RuntimeWatchdogSec p/ hardware);
(d) WAITRESS servindo o dashboard (16 threads) — telemetria convertida de
WebSocket para SSE (/events), flask-sock removido. FASE 1.5: parte de software
COMPLETA — restam apenas as provas físicas na Pi.
(e) FASE 2.5 TAMBÉM ADIANTADA: Torre de Controle pronta em MOCK — fleet/link.py
(FleetLink: backend mqtt/paho ou mock), tower/main.py (dashboard da frota :5100
com E-STOP GERAL retained), integração no main.py do robô (telemetria 2s +
fleet_estop re-assertado pelo loop 50Hz). Validação: scripts/validate_phase25.py
(17/17) e demo scripts/demo_torre.py. Setup de produção: docs/TORRE_CONTROLE.md
(mosquitto na Torre; robôs apontam via FROTA_MQTT_HOST em /etc/frota.conf).

Objetivo de hoje (validar no HARDWARE real, sem MOCK):
1. Rodar `python3 scripts/validate_phase1.py` na Pi e confirmar o jitter < 5ms como veredito.
2. `i2cdetect -y 1` deve mostrar 0x48 (ADS1115 apenas — o BNO085 agora é UART-RVC).
3. Validar leitura real da bateria (±0.5V vs multímetro) e do bumper (objeto a 45cm).
4. Prova física do fail-closed: desconectar o USB do RPLIDAR com o sistema rodando
   → blocked = ⛔ em ≤ 1s; reconectar → volta a liberar sozinho.
5. Instalar o serviço: `sudo bash scripts/install_service.sh 1` e provar o gate:
   `sudo systemctl kill -s SIGKILL frota-robo` → serviço volta sozinho em ~2s.
6. BNO085 (GY-BNO08x): o driver UART-RVC JÁ ESTÁ IMPLEMENTADO em
   sensors/heading_lock.py (o I2C foi abandonado pelo bug de clock stretching
   da Pi). Fiação na tabela abaixo; depois habilitar a serial no raspi-config
   (console NO, hardware YES) e rodar os 3 níveis de teste de
   docs/BNO085_UART_RVC.md.

Regras invioláveis: NÃO altere pinos/PID/lógica de core/motor_driver.py; a Regra de
Segurança Nº 0 (≤15% / ≥20% → Emergency Stop) permanece em todos os caminhos.

Por onde começamos?
```
```
