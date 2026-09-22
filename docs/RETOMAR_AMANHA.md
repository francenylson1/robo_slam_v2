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

> Atualizado em 22/09/2026, ao fechar a Fase 2 com a voz.

```
Olá! Retomando a Frota Mista v2 (robô garçom, Projeto Aluno Maker Digital).

LEIA PRIMEIRO, nesta ordem:
  docs/SESSAO_2026-09-22.md  (a última sessão: voz, conflito de GPIO com o v1)
  docs/RETOMAR_AMANHA.md     (este arquivo: C1, BNO085, Fase 1.5, sensores)
  docs/AMBIENTE_MULTIPLAS_MAQUINAS.md (acesso, Tailscale, SO da Pi, migração)
  docs/PROPOSTA_PRODUCAO_COMERCIAL.md (plano aprovado das fases)

ONDE O PROJETO ESTÁ:
  Fase 1   ✅ 39/39 em MOCK; LIDAR C1 e BNO085 PROVADOS NO HARDWARE.
  Fase 1.5 ✅ FECHADA — watchdog, systemd e fail-safe dos motores provados.
  Fase 2   ✅ FECHADA — auth, dashboard, rosto animado E VOZ (74/74).
  Fase 2.5 ✅ 17/17 em MOCK; falta a prova com 2 robôs reais.
  Fase 3   ⬜ PRÓXIMA — chassi/potência; gate é "linha reta de 2 m".
  Fase 4   ⬜ exige o ADS1115 ligado antes.

RUMO DEFINIDO PELO PROFESSOR (22/09/2026): o v2 é o dono do robô. A finalidade
é usar o sistema novo sem ficar voltando atrás — onde v1 e v2 disputarem um
recurso, o v2 ganha, e a régua do v2 é excelência, não "funciona".

A PI DO ROBÔ (ssh robo1 → 192.168.0.185, ou 100.84.87.44 pelo Tailscale; amd):
  multi-user.target (sem desktop) — jitter do loop 50Hz: 0,001 ms.
  Serviços: frota-robo (loop + dashboard :5000), frota-rosto (labwc + rosto no
  7" + a VOZ), e — do v1 — vitrine-app (:8080/signage) e vitrine-telas.

  ⚠️ A Pi NÃO é uma máquina limpa: carrega o sistema de telas do v1
  (~/robo_slam, de 12/09/2026). NÃO substituir; inventariar antes de mexer.
  O teleop do v1 (robo-teleop.service) foi DESLIGADO do boot em 22/09 porque
  disputava o GPIO dos motores com o v2 — ver docs/SESSAO_2026-09-22.md.

ÁUDIO: alto-falante é placa USB GeneralPlus (card 2), NÃO o HDMI. O PipeWire
da sessão segura a placa — tocar SEMPRE com pw-play (XDG_RUNTIME_DIR=
/run/user/1000), nunca aplay -D plughw:2,0 (dá "ocupado").

A VOZ: 18 .wav prontos em web/static/audio/, gerados na bancada pelo Piper
(voz pt_BR-faber-medium). O robô NÃO sintetiza em operação — o Piper leva ~4s
por frase na Pi. Mudar as falas: editar VOZ_FRASES em config/settings.py e
rodar scripts/gerar_vozes.py na Pi (Piper em ~/piper-venv, modelos em
~/piper-vozes). Variação é REQUISITO: evento de 4 horas não pode repetir.

SENSORES: LIDAR C1 ✅ (/dev/ttyUSB0 @460800) · BNO085 ✅ (/dev/serial0 →
ttyAMA0, 100 Hz) · ADS1115 ❌ adiado por decisão para antes da Fase 4 ·
câmera ausente.

REGRAS INVIOLÁVEIS:
  - Regra de Segurança Nº 0 (≤15% / ≥20% → Emergency Stop) em todos os caminhos.
  - NÃO alterar pinos/PID/lógica de core/motor_driver.py.
  - /api/stop fica FORA do login (parar o robô nunca depende de senha).
  - Telemetria parada tem que ser VISIVELMENTE parada — e o robô fica CALADO:
    sem telemetria fresca, o rosto não fala e não finge alegria.
  - Nunca aplicar raio mínimo no caminho da segurança — no bumper isso falharia
    ABERTO. A máscara de 140°–210° é só para mapeamento (Fase 4).

ANTES DE COMMITAR, rodar os três harnesses como regressão:
  python3 scripts/validate_phase1.py    (39/39 na Pi; 37/37 no PC — o jitter só
                                         vira veredito no Linux dedicado)
  python3 scripts/validate_phase2.py    (74/74)
  python3 scripts/validate_phase25.py   (17/17)

PRÓXIMO PASSO SUGERIDO: Fase 3 — chassi e potência. O gate é a linha reta de
2 m, e é onde o BNO085 finalmente fecha a malha: o passo 3 de
core/control_loop.py ("CORREÇÃO DE RUMO") ainda é só um comentário. Exige o
professor junto do robô.

PENDÊNCIAS DO PROFESSOR: senha permanente do dashboard
(sudo python3 scripts/set_web_password.py); Tailscale nas outras máquinas;
na bancada — ADS1115 (antes da Fase 4), multímetro nos freios com o estágio de
potência ligado, e identificar a protuberância de 0,59 cm entre 187° e 195°.

OBSERVAÇÃO: eu não consigo rolar as mensagens no terminal. Respostas longas,
por favor, em arquivo .md no repositório ou em página publicada.

Por onde começamos?
```
