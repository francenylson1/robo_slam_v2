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

**6 fios** (VCC, GND, PS0, PS1, SDA e — desde 23/09/2026 — **RST**). Os demais pinos ficam desconectados.

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
| **RST**           | **GPIO 4** — pino físico **7**       | Reset pelo software (ativo baixo) — ver seção abaixo |

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
│ RST ─────┼──────────────────► pino 7  (GPIO4)   ← desde 23/09/2026
│ SCL  AD0 │  CS  INT  ── não conectados
└──────────┘
```

---

## O RST e o BNO que acorda mudo (23/09/2026)

**Sintoma:** às vezes, ao ligar o robô, o BNO085 não manda **nenhum byte** —
fiação certa, `pinctrl get 14,15` = `a4`. Aconteceu em 22/09 e 23/09; nas duas
vezes só voltou desligando e religando o robô inteiro.

**Não é mau contato:** com o robô ligado, cada fio foi mexido nas duas pontas
(deitado e em pé) com um monitor a 0,5 s — nenhuma queda. É a **partida** do
sensor, que às vezes sai ruim.

**Correção:** RST no **GPIO 4 (pino 7)**. O `frota-robo` dá um **reset de
partida** e, se o sensor ficar **mudo por 2 s**, um **reset automático** (espera
crescente 2/5/10/30 s entre tentativas), com aviso no log. Código:
`sensors/bno_reset.py` e `sensors/heading_lock.py`.

- **Por que o GPIO 4 e não o 22:** o 4 nasce com **pull-up** — no boot o RST fica
  solto e o sensor funciona mesmo sem o software. O 22 nasce com pull-down.
- **O pino nunca é posto em nível alto:** só é puxado para baixo e depois solto
  (entrada com pull-up). Com o RST em curto, a Pi nunca entra em curto.
- **No multímetro, RST "tem continuidade" com GND/PS1:** é o capacitor de reset
  da placa (bipe curto). Prova na Pi: com pull-up, o GPIO 4 lê `hi`.
- **Depois de um reset o yaw zera** na direção atual (-118,44° → -0,02°). A malha
  de rumo não vê o salto: com 1 s sem quadro ela já soltou a referência.

**Prova no hardware (23/09):** RST segurado baixo às 11:56:48 → `MUDO há 2.0 s`
e `Reset automático nº 1` às 11:56:50 → `voltou a transmitir` às 11:56:51.

---

## Configuração da Raspberry Pi (uma vez)

```bash
sudo raspi-config
# Interface Options → Serial Port:
#   "Would you like a login shell over serial?"  → NO   (libera a UART)
#   "Would you like the serial port hardware enabled?" → YES
sudo reboot
```

> ### ⚠️ NA PI 5 ISSO NÃO BASTA — verificado no hardware em 21/09/2026
>
> Na Pi 5, `/dev/serial0` pode existir e apontar para **`ttyAMA10`**, que é o
> **conector de depuração dedicado** (o JST de 3 pinos perto da USB-C) — e **não**
> os pinos 8/10 do header de 40 vias. Nesse estado tudo *parece* configurado:
> `/dev/serial0` existe, o código abre a porta sem erro, e **zero byte chega**,
> porque o programa está lendo um conector físico diferente daquele onde o sensor
> está soldado.
>
> O sintoma definitivo é este:
>
> ```bash
> pinctrl get 14,15
> # ERRADO: 14: no pd | -- // GPIO14 = none     ← pinos sem função nenhuma
> # CERTO : 14: a4 pn | hi // GPIO14 = TXD0
> #         15: a4 pu | hi // GPIO15 = RXD0
> ```
>
> A correção é acrescentar ao final de `/boot/firmware/config.txt`:
>
> ```
> enable_uart=1
> ```
>
> e reiniciar. Depois disso `/dev/serial0` passa a apontar para **`ttyAMA0`** (a
> UART do header) e os pinos ganham a função `a4`. Confirme sempre com
> `pinctrl get 14,15` e `ls -l /dev/serial0` **antes** de suspeitar da fiação.

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
| 0 bytes no Nível 1 | **UART não roteada para os pinos (Pi 5)** | `pinctrl get 14,15` → se disser `none`, falta `enable_uart=1` no `config.txt`. **Cheque isto ANTES da fiação** |
| 0 bytes no Nível 1 | **O serviço já está com a porta aberta** | `sudo systemctl stop frota-robo` antes de testar — o `HeadingLock` do robô consome os bytes |
| 0 bytes no Nível 1 | PS0 não estava em 3V3 **na energização** | Confira PS0 e desligue/ligue o módulo |
| 0 bytes no Nível 1 | Console serial ainda ativo | `raspi-config` de novo; confira que não há `console=serial0` em `/boot/firmware/cmdline.txt` |

### Teste que separa "sem alimentação" de "não transmite"

Sem multímetro, dá para saber se há um módulo vivo na outra ponta do fio:

```bash
sudo pinctrl set 15 ip pd     # entrada com pull-down
pinctrl get 15                # alto = algo do outro lado segura a linha
sudo pinctrl set 15 a4 pu     # devolve a função UART
```

- **Fica em `hi`** → há alimentação no módulo e o fio do pino 10 chega nele.
  (Atenção: a placa GY-BNO08x tem pull-up no SDA, então isso prova
  *alimentação e continuidade*, não que o sensor esteja falando.)
- **Cai para `lo`** → nada conectado, ou o módulo está sem 3V3.

Se ficar em `hi` e ainda assim não vier byte nenhum em **nenhum baud**, o suspeito
é o **PS0** — o sensor continua em modo I²C/SHTP e simplesmente não transmite.
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
