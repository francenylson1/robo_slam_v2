# Frota Mista v2 — Robô Garçom Autônomo

**Projeto Aluno Maker Digital** · CRE Recanto das Emas / DF  
Prof. Francenylson Luiz Dantas dos Santos

---

## Sobre o projeto

Ecossistema Python puro para gerenciar uma frota mista de 10 robôs garçons
construídos sobre motores de hoverboard com drivers ZS-X11H V2:

- **1 Slamtec Aurora** — mapeia o salão e serve de base; mapa e POIs compartilhados com a frota
- **Duas versões funcionando** — autônoma (navegação SLAM) e assistiva (teleoperação via joystick USB 2.4 GHz); a quantidade em cada uma não é requisito
- Interface web responsiva: 34" ultrawide → 15.6" → 7" touchscreen → smartphones
- Sistema **offline-first** — sem dependência de nuvem

---

## ⚠️ Regra de Segurança Nº 0

> Potência máxima permitida: **15%** dos motores de hoverboard.  
> Qualquer leitura ≥ **20%** aciona **Emergency Stop imediato**.  
> Esta regra está implementada em `core/motor_driver.py` e **não pode ser alterada**
> sem revisão formal e teste físico no robô.

**Como a regra é garantida** (auditado em 22/09/2026):

| Camada | Onde | O que faz |
|---|---|---|
| 1. Ponto único | `core/motor_driver.py → _apply_safety_clip()` | corta em 15%; ≥20% dispara Emergency Stop e trava o sistema |
| 2. Todos os caminhos | `set_speed()` e o loop PID | os dois passam pelo clip antes de escrever qualquer coisa |
| 3. Na escrita do PWM | `_write_motor()` | `min(abs(power), 15%)` de novo, por último |
| 4. No comando do operador | `core/joystick_reader.py` | o manche é **escalado** por 15% — fundo de curso já É o teto — e ainda sofre clamp |

**Ninguém contorna:** nenhum módulo fora do `motor_driver.py` escreve em PWM ou GPIO.
Isso é verificado automaticamente.

**A regra é testada em toda regressão.** `scripts/validate_phase1.py` abre com a
seção **"0. REGRA Nº 0"** — 14 verificações que falham o gate se o teto mudar, se o
Emergency Stop parar de disparar, se o joystick deixar de escalar pelo teto, ou se
algum módulo novo passar a escrever direto no hardware.

> **Ao adicionar comandos de movimento** (dashboard, Torre, navegação da Fase 4):
> passe **sempre** por `motors.set_speed()` ou `set_target_speed_tps()`. Hoje o
> dashboard e a Torre só sabem chamar `stop()` — nenhum caminho de rede move o robô.

---

## Estrutura do projeto

```
robo_slam_v2/
├── main.py                  ← Ponto de entrada (loop 50Hz)
├── config/
│   └── settings.py          ← Configuração central (pinos, PID, segurança)
├── core/
│   ├── motor_driver.py      ← ⚠️ NÚCLEO VALIDADO — pinos e PID do v1
│   ├── pid_controller.py    ← PID com anti-windup (migrado do v1)
│   └── joystick_reader.py   ← Dongle USB 2.4GHz via pygame
├── sensors/
│   ├── battery_monitor.py   ← ADS1115 → tensão/% bateria 42V
│   ├── safety_bumper.py     ← RPLIDAR C1 → bloqueio frontal
│   └── heading_lock.py      ← BNO085 → correção de Yaw
├── slam/
│   ├── slam_nav.py          ← Aurora SDK (Fase 4)
│   └── poi_manager.py       ← pois.json (Fase 2)
├── fleet/
│   └── link.py              ← FleetLink: MQTT (paho) ou mock — robô ↔ Torre
├── tower/
│   ├── main.py              ← Torre de Controle: dashboard da frota (:5100)
│   └── templates/torre.html ← Cartões da frota + E-STOP GERAL
├── web/
│   ├── server.py            ← Flask (waitress) + MJPEG + telemetria SSE
│   ├── templates/
│   │   └── dashboard.html   ← Interface responsiva
│   └── static/
├── data/                    ← POIs e mapas (gerado em runtime)
├── scripts/
│   └── tag_legacy.sh        ← Script para arquivar o repo v1
└── docs/
    └── NUCLEO_MOTOR.md      ← Documentação dos pinos validados
```

---

## Núcleo Motor — Pinos Validados (NÃO ALTERAR)

| Sinal       | GPIO (BCM) | Descrição              |
|-------------|-----------|------------------------|
| DIR_E       | 5         | Direção motor esquerdo |
| BREAK_E     | 6         | Freio motor esquerdo   |
| PWM_E       | 18        | Velocidade (20Hz)      |
| HALL_E      | 16        | Encoder esquerdo       |
| DIR_D       | 23        | Direção motor direito  |
| BREAK_D     | 24        | Freio motor direito    |
| PWM_D       | 12        | Velocidade (20Hz)      |
| HALL_D      | 17        | Encoder direito        |

**Lógica direcional** (validada fisicamente):
- Motor esquerdo: `HIGH` = frente, `LOW` = trás
- Motor direito:  `LOW` = frente, `HIGH` = trás ← **OPOSTO** por design de fiação

**PID calibrado:** `Kp=0.26 | Ki=0.23 | Kd=0.0`  
Fonte: `robo_slam v1` — tag `v1.0-estavel-base` / commit `d3727e0`

---

## Como executar

```bash
# Desenvolvimento (PC/notebook — modo MOCK automático)
python3 main.py

# Na Raspberry Pi (modo real)
python3 main.py --robot-id 1

# Forçar modo MOCK mesmo na Pi (testes)
python3 main.py --mock

# Com log detalhado
python3 main.py --log DEBUG
```

---

## Compatibilidade Raspberry Pi 4 e Pi 5

O sistema roda nas duas placas. A única diferença relevante é o subsistema GPIO:
a **Pi 5** usa o chip **RP1**, com o qual a `RPi.GPIO` clássica é incompatível.

Por isso o `requirements.txt` usa **`rpi-lgpio`** — um *drop-in* da API `RPi.GPIO`
sobre a `lgpio`, que funciona em Pi 4 **e** Pi 5. O código do núcleo motor
(`import RPi.GPIO as GPIO`) **não muda**: o design de encoders por *polling* (em
vez de `add_event_detect`) torna a troca transparente.

> ⚠️ Não instale `rpi-lgpio` e `RPi.GPIO` juntos — eles conflitam no mesmo namespace.

I2C (ADS1115), UART (BNO085 em modo RVC — `/dev/serial0` funciona nas duas
placas), USB (joystick/RPLIDAR/webcam), HDMI duplo e a numeração BCM dos pinos
são idênticos nas duas placas. O `settings.py` detecta o modelo (`PI_MODEL`)
apenas para log/diagnóstico.

> ⚠️ **BNO085 ≠ I2C**: o controlador I2C da Pi tem bug de clock stretching que
> trava com o BNO085 (SHTP). Por isso ele opera em **UART-RVC** (100Hz) —
> fiação e setup em `docs/BNO085_UART_RVC.md`.

---

## Validação da Fase 1 (Gate)

Os quatro critérios do Gate da Fase 1 são comprovados por um único script, em MOCK:

```bash
python3 scripts/validate_phase1.py
```

Ele imprime um relatório verde/vermelho (exit code 0 = tudo OK) cobrindo:
precisão de tensão ±0.5V, bloqueio do bumper a 45cm, estabilidade/normalização do
Yaw e jitter do loop 50Hz < 5ms.

O script prova a **lógica e a matemática** em MOCK. A **confirmação física** na Pi
é um checklist complementar:

- [ ] Tensão: comparar leitura do dashboard com multímetro no terminal da bateria (±0.5V)
- [ ] Bumper: posicionar objeto real a ~45cm à frente e confirmar `blocked = ⛔`
- [ ] Heading: BNO085 em UART-RVC (`docs/BNO085_UART_RVC.md`), robô parado —
      Yaw estável por alguns minutos (sem drift)
- [ ] Loop: rodar `validate_phase1.py` na própria Pi e confirmar jitter < 5ms
- [ ] Fail-closed (Fase 1.5): com o sistema rodando, **desconectar o USB do RPLIDAR**
      e confirmar `blocked = ⛔` em ≤ 1s; reconectar e confirmar que volta a liberar

---

## Fases de desenvolvimento

| Fase | Foco                            | Gate de conclusão                        |
|------|---------------------------------|------------------------------------------|
| 0    | Fundação e limpeza              | SSH ok, tensões medidas, i2cdetect ok    |
| 1    | Percepção e telemetria          | Sensores lendo, loop 50Hz estável        |
| 1.5  | Blindagem (produção)            | ✅ **CONCLUÍDA 21/09/2026** — bumper fail-closed, watchdog e systemd provados no hardware: processo morto (SIGKILL) e processo travado (SIGSTOP) → serviço volta sozinho, freios acionados. Detalhes: `docs/RETOMAR_AMANHA.md` |
| 2    | Interface web responsiva        | ✅ **CONCLUÍDA 22/09/2026** — dashboard nos 4 tamanhos + auth + rosto animado + **voz** (74/74). 18 falas pré-geradas pelo Piper, variadas, tocadas pelo mesmo `decide()` da expressão. Detalhes: `docs/SESSAO_2026-09-22.md` |
| 2.5  | Torre de Controle (frota/MQTT)  | 2+ robôs na mesma tela, E-Stop geral funcionando — *software validado em MOCK (`validate_phase25.py` + `demo_torre.py`); prova física: `docs/TORRE_CONTROLE.md`* |
| 3    | Integração de potência (chassi) | ✅ **CONCLUÍDA 22/09/2026** — o gate da reta cumprido com folga: **4,90 m com 10 cm de desvio** (2,1 cm/m, contra 111 cm/m sem correção). Malha de rumo fechada com o BNO085. Pendências registradas: E-Stop físico (adiado), encoder direito (defeito físico), segunda camada de proteção acima do plano do LIDAR. Detalhes: `docs/FASE3_PLANO.md` |
| 4    | Navegação autônoma SLAM         | Versão autônoma (robô com o Aurora) 30 min sem colisão, atendendo chamadas, com a versão assistiva funcionando junto — **exige o ADS1115 ligado** (30 min sem supervisão) |
| 5    | Piloto comercial                | Golden image, QA por unidade, 1 dia de operação real sem intervenção |

> Trabalhar de várias máquinas (Pi, desktop Ubuntu, notebooks), acesso remoto por
> Tailscale e o SO da Pi: `docs/AMBIENTE_MULTIPLAS_MAQUINAS.md`

> Detalhes das fases 1.5, 2.5 e 5 (plano aprovado para produção comercial):
> `docs/PROPOSTA_PRODUCAO_COMERCIAL.md`

---

## Repositório legado

O repositório original `robo_slam` (v1) contém o histórico completo de
desenvolvimento, calibração de PID e diagnóstico de direção.
Ele foi arquivado como referência e **não deve receber novos commits**.

```bash
# Para referenciar o legado:
# https://github.com/francenylson1/robo_slam
# Tag: v1.0-estavel-base  Commit: d3727e0
```
