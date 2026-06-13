# BNO085 (módulo GY-BNO08x) — Instalação em UART-RVC

> **Por que este documento existe:** o controlador I2C de hardware da Raspberry
> Pi tem um bug de silício conhecido — **não respeita clock stretching** — e o
> BNO085 (protocolo SHTP) usa clock stretching intensamente. A combinação causa
> leituras corrompidas e travamentos. **Solução adotada: modo UART-RVC**, em que
> o sensor abandona o I2C e transmite Yaw/Pitch/Roll prontos a **100Hz**.
> O ADS1115 (bateria) **não** faz clock stretching e permanece no I2C de hardware.

---

## O seu módulo serve? SIM — e é o ideal

O **GY-BNO08x** expõe os pinos de seleção de modo (**PS0 e PS1**) direto no
conector — na placa da Adafruit seria preciso soldar jumper. Nenhuma compra
nova é necessária.

**Como o BNO08x escolhe o modo de comunicação** (lido no momento em que liga):

| PS1 | PS0 | Modo |
|-----|-----|------|
| 0   | 0   | I2C (padrão de fábrica) ← *era o nosso, com o bug* |
| 0   | **1** | **UART-RVC** ← **novo modo do projeto** |
| 1   | 0   | UART-SHTP |
| 1   | 1   | SPI |

⚠️ **PS0/PS1 são lidos só na energização/reset.** Faça a fiação ANTES de ligar.
Se mudar com o circuito ligado, desligue e ligue de novo.

---

## Fiação completa — GY-BNO08x ↔ Raspberry Pi (4 ou 5)

Apenas **4 fios**. Os demais pinos ficam desconectados.

| Pino do GY-BNO08x | Liga em (Pi)                        | Função no modo RVC |
|-------------------|--------------------------------------|--------------------|
| **VCC**           | **3V3** — pino físico **1** (ou 17)  | Alimentação 3,3V — ⚠️ NUNCA 5V |
| **GND**           | **GND** — pino físico **6** (ou 9/14/20/25) | Terra comum |
| **PS0**           | **3V3** — mesmo 3V3 do VCC           | Seletor = 1 → ativa UART-RVC |
| **PS1**           | **GND**                              | Seletor = 0 (explícito, contra ruído) |
| **SDA**           | **GPIO 15 / RXD** — pino físico **10** | Vira o **TX** do sensor (saída de dados) |
| SCL               | — não conectar                       | Sem função no RVC |
| AD0               | — não conectar                       | Era seleção de endereço I2C |
| CS                | — não conectar                       | Só para SPI |
| INT               | — não conectar                       | Sem função no RVC |
| RST               | — não conectar (opcional: botão p/ GND) | Reset manual (ativo baixo) |

**Pontos de atenção elétrica:**
1. **3,3V em tudo** — o GPIO da Pi não tolera 5V. O módulo GY funciona a 3,3V.
2. A comunicação é **unidirecional** (sensor → Pi): só 1 fio de dados, no RXD.
   O TXD da Pi (GPIO14/pino 8) fica livre.
3. PS0 e PS1 podem ir nos mesmos trilhos de 3V3/GND do VCC/GND — sem resistor.
4. Cabos curtos (< 20cm) e terra comum sólido evitam quadros corrompidos.

```
GY-BNO08x                       Raspberry Pi (conector de 40 pinos)
┌──────────┐
│ VCC ─────┼──────────────────► pino 1  (3V3)
│ PS0 ─────┼──────────────────► pino 1  (3V3)   ← mesmo trilho do VCC
│ GND ─────┼──────────────────► pino 6  (GND)
│ PS1 ─────┼──────────────────► pino 6  (GND)   ← mesmo trilho do GND
│ SDA ─────┼──────────────────► pino 10 (GPIO15 / RXD)
│ SCL  AD0 │  CS  INT  RST  ── não conectados
└──────────┘
```

---

## Configuração da Raspberry Pi (uma vez)

```bash
sudo raspi-config
# Interface Options → Serial Port:
#   "Would you like a login shell over serial?"  → NO   (libera a UART)
#   "Would you like the serial port hardware enabled?" → YES
sudo reboot
```

Após reiniciar, deve existir `/dev/serial0` (symlink que funciona na Pi 4 e na Pi 5):

```bash
ls -l /dev/serial0
# Pi 4 → aponta para ttyS0 (mini-UART) | Pi 5 → ttyAMA0 — ambos OK a 115200
```

> **Nota Pi 4:** o Bluetooth ocupa a UART principal, então `/dev/serial0` é a
> mini-UART — funciona bem a 115200 (o `enable_uart=1` que o raspi-config grava
> fixa o clock). Se algum dia houver instabilidade, o plano B é desativar o BT:
> `dtoverlay=disable-bt` no `/boot/firmware/config.txt`.

---

## Teste em 3 níveis (na bancada)

```bash
# NÍVEL 1 — chegam bytes? (sensor ligado, fiação feita)
python3 - <<'EOF'
import serial
s = serial.Serial("/dev/serial0", 115200, timeout=1)
data = s.read(38)   # ~2 quadros de 19 bytes
print(f"{len(data)} bytes:", data.hex(" "))
# Esperado: 38 bytes com "aa aa" aparecendo a cada 19 bytes
EOF

# NÍVEL 2 — o driver do projeto decodifica?
cd ~/robo_slam_v2 && source .venv/bin/activate
python3 -c "
from sensors.heading_lock import HeadingLock
import time
h = HeadingLock(); h.start(); time.sleep(2)
print(f'Yaw: {h.yaw_deg:.2f}°  | healthy: {h.healthy}')
# Gire o módulo com a mão e rode de novo — o Yaw deve acompanhar
"

# NÍVEL 3 — estabilidade (Gate da Fase 1, item heading)
# Módulo parado sobre a mesa por 3 minutos: o Yaw deve variar < ±1°
```

## Solução de problemas

| Sintoma | Causa provável | Correção |
|---|---|---|
| 0 bytes no Nível 1 | PS0 não estava em 3V3 **na energização** | Confira PS0 e desligue/ligue o módulo |
| 0 bytes no Nível 1 | Console serial ainda ativo | `raspi-config` de novo; confira que não há `console=serial0` em `/boot/firmware/cmdline.txt` |
| Bytes sem `aa aa` | Baud errado ou fio no GPIO errado | 115200; SDA do módulo → pino físico 10 |
| Quadros corrompidos (checksum) | Terra ruim / cabo longo | Encurtar cabos, reforçar GND |
| Yaw congelado | Módulo travou | RST ao GND por 1s (ou ciclo de energia) |

---

## O que NÃO muda e o que se perde

- **Nada muda** no núcleo motor, no ADS1115 (segue no I2C) e em todo o caminho
  MOCK — o harness `validate_phase1.py` continua validando a lógica do Yaw.
- **Perde-se** (e não faz falta): quaternions crus e controle fino de
  calibração do SHTP. Só usamos o Yaw; na Fase 4 a pose vem do Slamtec Aurora.
- **Plano B documentado:** se um dia precisarmos do SHTP, a alternativa é I2C
  por software (`dtoverlay=i2c-gpio` em GPIOs livres), que respeita clock
  stretching — ao custo de CPU e de um driver muito mais complexo.
