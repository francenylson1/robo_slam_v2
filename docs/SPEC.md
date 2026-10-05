# SPEC — Frota Mista v2 (como funciona hoje)

> **Estado atual do sistema, em poucas páginas.** Números e parâmetros moram no
> `config/settings.py` (comentados com a medida que os justifica); o porquê
> de cada decisão mora nos documentos citados. Atualizar quando mudar uma
> interface, um fluxo ou uma regra de segurança. Última revisão: **01/10/2026**.

---

## 1. Hardware do robô 1 (a referência da frota)

| Peça | Como está ligado | Fato que custou caro |
|---|---|---|
| Raspberry Pi 5, 8 GB | Debian 12 aarch64, `multi-user.target` (sem desktop) | USB-C vem de step-down sem USB-PD → **`usb_max_current_enable=1`** (senão 600 mA no USB) |
| Motores de hoverboard + ZS-X11H | GPIO BCM 5/6/18/16 (E) e 23/24/12/17 (D) | `BREAK=HIGH` **solta** a roda; `LOW` = frenagem elétrica (`docs/NUCLEO_MOTOR.md`, `FASE3_PLANO.md`) |
| RPLIDAR C1 | USB, **460800 baud**, a 22 cm do chão, borda frontal | não implementa `SET_PWM`; sombra da coluna 145°–204° |
| BNO085 | UART-RVC 100 Hz, `/dev/serial0 → ttyAMA0` (`enable_uart=1`), RST no GPIO 4, energia por BC327 no GPIO 7 | direita **aumenta** o yaw (o v1 era o contrário) |
| ADS1115 | I²C 0x48, divisor 100k/6,8k, `BATTERY_CAL_FACTOR` 1,018 | — |
| Slamtec Aurora | cabo `eth0` (Aurora 192.168.11.1), 1,45 m, 12 V próprio | o ponto que ele reporta fica **5,3 cm atrás e 7,2 cm à esquerda** do eixo de giro (`AURORA_BRACO_M`) |
| Joystick iPega PG-9076 | receptor USB 2.4 GHz, tem que ser **"shanwan Android GamePad"** | só manda evento quando o valor muda; desligado/fora do alcance → centro |
| Alto-falante 6 W | **placa de som USB** (card 2), tocar com `pw-play` | o PipeWire segura a placa |
| Telas | 7" touch (HDMI-A-1, rosto) e 15,6" (HDMI-A-2, vitrine do v1) | 7" sem EDID nesta Pi (em aberto) |
| Base | 42 × 60 cm; rodas a 30 cm da frente (centro); 4 rodízios rígidos | 6 apoios → roda motriz no ar num desnível; base nova (05/10): 1 rodízio frente + 1 trás a 250 mm do eixo, com 4 molas nos parafusos, 3 montantes de aço 30×30 (`docs/SESSAO_2026-10-05.md`) |

## 2. Processos (systemd)

| Serviço | O que roda |
|---|---|
| `frota-robo` | `main.py`: loop 50 Hz, sensores, missão, dashboard `:5000` (waitress), telemetria MQTT, watchdog (`Type=notify`, `WatchdogSec=5`) |
| `frota-rosto` | labwc + Chromium no 7" (`/rosto`) — `Wants=frota-robo` (religa o robô se só ele parar!) |
| `vitrine-*` (user, v1) | vitrine do 15,6"; o v2 usa o gancho `ROBO_SEM_ROSTO=1` |

## 3. O loop de 50 Hz (`core/control_loop.py`)

A cada 20 ms, com deadline absoluto: alimenta o watchdog → **percepção**
(bumper, rumo, bateria, pose, joystick) → **timeout do joystick** (em modo
Joystick, se `timed_out()`: para os motores e **apaga** `cmd_motores`) →
**E-Stop geral** da Torre → **malha de rumo** (só com comando vivo de reta) →
**missão** (`missao.tick`). Jitter medido na Pi: 0,001 ms.

`timed_out()` = sem controle aceito no USB **ou** leitor parado há > 200 ms. Não
é "silêncio do manche" (30/09).

## 4. Quem pode mover o robô

Só por `motors.set_speed()` (Regra Nº 0 dentro), e só de: joystick (`main.py`),
malha de rumo (`core/control_loop.py`), **missão** (`slam/missao.py`) e scripts
`scripts/bancada_*.py`. A varredura estática do `validate_phase1.py` acusa
qualquer outro — e qualquer um em `web/`, `fleet/`, `tower/`. Única exceção de
GPIO fora do `motor_driver`: `sensors/bno_reset.py`.

## 5. Segurança em camadas

| Camada | O quê | Comportamento |
|---|---|---|
| Regra Nº 0 | teto 15% (missão 12%), ≥ 20% E-Stop | clip em ponto único + na escrita do PWM + joystick escalado |
| Bumper (C1) | arco ±30° à frente | 50 cm no reto a 12% e no joystick; 30 cm na aproximação lenta; 20 cm girando/parado; **sem dado = bloqueado** |
| Watchdog | systemd + hardware | processo travado → reinicia; pronto em ~8 s |
| Missão | vigias | pose inválida (0,3 s), BNO sem sinal, BNO × Aurora > 10°, centro na margem, sem avanço (5 cm / 5° em 3 s), rodas × Aurora, tempo, bateria |
| Mapa | áreas proibidas desenhadas + margem de 50 cm | o planejador contorna |
| **Não coberto** | acima de 22 cm, atrás, fora do arco | autônomo **supervisionado** (camada 3 em estudo) |

## 6. Pose (`sensors/pose_source.py`, `sensors/aurora_pose.py`)

- Interface genérica: `pose_valida(max_idade)`, `motivo()`, `health()`. Robôs
  sem Aurora: `NullPoseSource` → missão "indisponível".
- **A pose é do CENTRO de giro**: cada leitura do Aurora é convertida com o braço
  (`centro_do_robo`); a referência da fita também (`fita_do_centro`).
- Vale com todas de pé: localizou depois de conectar; bateu com a fita (15 cm,
  5°); fresca (0,5 s; 0,3 s em missão); sem salto > 25 cm/15° (depois, 1 s
  estável); fora do 1º segundo; rastreio não perdido.
- **Partida** ("Localizar na fita", com login, robô parado): zerar → carregar o
  mapa (sha conferido) → relocalizar → conferir com a fita. Reiniciar o
  serviço desfaz a localização.
- Convenção: rumo do Aurora cresce para a **esquerda**; o BNO para a
  **direita** — só passam **diferenças**, com sinal trocado.

## 7. Navegação e missão (`slam/`)

- **Desenho** (`mapa_nav.py`): áreas proibidas e POIs em metros, desenhados
  pelo operador no `/mapa`, com versões e trava de edição. A base é um POI fixo
  (a fita convertida para o centro).
- **Planejador** (`planejador.py`): A* na planta de 5 cm; parede e "nunca
  visto" bloqueiam; tudo cresce pela margem; prefere o meio dos corredores;
  rota em poucos trechos retos.
- **Missão** (`missao.py`), por trecho: **girar** parado (Aurora diz quanto, BNO
  fecha; contínuo 8–12% regulado pela velocidade até faltarem 25°, depois
  pulsos adaptativos) → **reto** a 12% com a malha de rumo e a mira do Aurora a
  cada 0,5 s (≤ 3°, congelada nos últimos 50 cm), 8% nos últimos 60 cm, para 6
  cm antes → **assentar** 0,5 s. Replaneja no ponto de curva (até 3×).
- **Base:** se o último trecho chegaria > 30° torto, passa antes por um ponto
  **atrás da base** (60/45/30 cm, com 15 cm de folga da margem). Depois do giro
  final **confere a posição**: corrige 1×; senão "parou perto".
- Tolerâncias: 15 cm (POI), 10 cm (base), 5° de rumo.
- Histórico: `data/navegacao/missoes.jsonl`.

## 8. Web e rede

| Rota | Login | O quê |
|---|---|---|
| `/`, `/mapa` | sim | dashboard; mapa com robô, áreas, POIs, rota e missão |
| `/api/status`, `/events` | sim | telemetria (SSE; `?rapido=1` no /mapa) — inclui `joystick`, `pose`, `missao` |
| `/api/stop` | **não** | parar (decisão 1 — nunca atrás de senha) |
| `/api/mode` | sim | só volta para Joystick (Autônomo só existe em missão) |
| `/api/aurora/partida` | sim | "Localizar na fita" |
| `/api/nav`, `/api/nav/editar`, `/nav/planta.png`, `/api/nav/rota` | sim | desenho, trava, planta, **mostrar** a rota |
| `/api/missao/ir` | sim | "vá até o POI X" (a rota tem que bater com a vista) |
| `/rosto`, `/rosto/eventos` | não | rosto do 7", payload reduzido, sem controles |

MQTT (Torre, `:5100`): `frota/robos/<id>/telemetria`, `frota/robos/<id>/status`
(retained + LWT), `frota/comandos/estop` (retained "on"/"off").

## 9. Voz

Falas em `VOZ_FRASES` (settings), geradas pelo Piper (`pt_BR-faber-medium`) na
bancada com `scripts/gerar_vozes.py`, versionadas em `web/static/audio/`.
Quem fala é o mesmo `decide()` que faz a cara; sem telemetria fresca, calado;
silêncio por estado (`VOZ_COOLDOWN_S`). Grupos de missão: início, chegou,
base, chegou na base, perdido, preso, apertado, **perto** (30/09).

## 10. Dados (fora do git)

`data/aurora/mapas/` (mapa `.stcm` + planta) · `data/navegacao/` (desenho,
histórico de versões, missões) · `data/varreduras/` (1 varredura do C1 por
segundo, com pose do centro e `mov`; desde 01/10, no robô 1, também a volta do
**laser do Aurora** a 1,45 m no campo `a145`, ~150 MB/h → o teto de 2 GB guarda
~13 h de uso) · `data/aurora/pivo/` (medidas
do braço).

## 11. Onde está o detalhe

`docs/NUCLEO_MOTOR.md` · `docs/FASE3_PLANO.md` · `docs/FASE4_ARQUITETURA_FROTA.md`
· `docs/SEGURANCA_PLANO_LIDAR.md` · `docs/BNO085_UART_RVC.md` ·
`docs/TORRE_CONTROLE.md` · `docs/ETAPA_B_ENCODERS.md` · sessões diárias
`docs/SESSAO_*.md` (histórico, não se reescreve).
