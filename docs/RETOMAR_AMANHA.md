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
#    Esperado: 0x48 (ADS1115) e 0x4a (BNO085). Se faltar, revise fiação (SDA=pino3, SCL=pino5).

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

## MOCK vs REAL — o que muda entre notebook e Pi

| Aspecto            | Notebook (hoje)        | Raspberry Pi (amanhã)               |
|--------------------|------------------------|-------------------------------------|
| `MOCK_MODE`        | `True` (auto)          | `False` (auto; `--mock` força MOCK) |
| GPIO / PWM         | desativado             | real, via `rpi-lgpio`               |
| Bateria (ADS1115)  | tensão simulada        | leitura I2C real                    |
| Bumper (RPLIDAR)   | varredura sintética    | LIDAR físico em `/dev/ttyUSB0`      |
| Heading (BNO085)   | yaw simulado           | I2C real *(driver SHTP pendente)*   |
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
2. `i2cdetect -y 1` deve mostrar 0x48 (ADS1115) e 0x4a (BNO085).
3. Validar leitura real da bateria (±0.5V vs multímetro) e do bumper (objeto a 45cm).
4. Prova física do fail-closed: desconectar o USB do RPLIDAR com o sistema rodando
   → blocked = ⛔ em ≤ 1s; reconectar → volta a liberar sozinho.
5. Instalar o serviço: `sudo bash scripts/install_service.sh 1` e provar o gate:
   `sudo systemctl kill -s SIGKILL frota-robo` → serviço volta sozinho em ~2s.
6. Implementar o driver real do BNO085 (protocolo SHTP via adafruit-circuitpython-bno08x),
   que hoje é só placeholder em sensors/heading_lock.py — manter o caminho MOCK intacto.

Regras invioláveis: NÃO altere pinos/PID/lógica de core/motor_driver.py; a Regra de
Segurança Nº 0 (≤15% / ≥20% → Emergency Stop) permanece em todos os caminhos.

Por onde começamos?
```
```
