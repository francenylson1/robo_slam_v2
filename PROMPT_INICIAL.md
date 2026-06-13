# PROMPT INICIAL — Frota Mista v2
# Cole este conteúdo na primeira mensagem ao Claude Code no Cursor

---

Olá Claude Code! Vou te apresentar o projeto completo antes de começarmos a trabalhar.

## Quem sou eu

Sou o Prof. Francenylson, criador do projeto **Aluno Maker Digital** no Recanto das Emas / DF.
Trabalho com Python, Raspberry Pi 4 e 5, e estamos desenvolvendo uma frota de robôs garçons
para uso educacional com foco em inclusão (alunos cadeirantes).

## O projeto — Frota Mista v2

Sistema Python puro (sem ROS) para 10 robôs garçons com motores de hoverboard:
- 3 robôs autônomos com SLAM (Slamtec Aurora)
- 7 robôs assistivos controlados por joystick USB 2.4GHz
- Interface web responsiva: 34" → 15.6" → 7" → smartphones
- Sistema offline-first (sem internet/nuvem)

## Estrutura do repositório

```
robo_slam_v2/
├── main.py                  ← Loop de controle 50Hz — PONTO DE ENTRADA
├── config/settings.py       ← TODA configuração centralizada aqui
├── core/
│   ├── motor_driver.py      ← ⚠️ NÚCLEO VALIDADO — não alterar pinos/PID
│   ├── pid_controller.py    ← PID calibrado fisicamente
│   └── joystick_reader.py   ← Dongle USB via pygame
├── sensors/
│   ├── battery_monitor.py   ← ADS1115 → bateria 42V
│   ├── safety_bumper.py     ← RPLIDAR C1 → obstáculos
│   └── heading_lock.py      ← BNO085 → correção de Yaw
├── slam/
│   ├── poi_manager.py       ← Gerenciador de POIs (pois.json)
│   └── slam_nav.py          ← Navegação autônoma (Fase 4)
├── fleet/
│   └── link.py              ← FleetLink: MQTT (paho) ou mock — robô ↔ Torre
├── tower/
│   └── main.py              ← Torre de Controle (dashboard frota + E-Stop geral)
├── web/
│   ├── server.py            ← Flask (waitress) + MJPEG + telemetria SSE
│   └── templates/dashboard.html
└── docs/NUCLEO_MOTOR.md     ← Documentação dos pinos validados
```

## ⚠️ REGRA DE SEGURANÇA Nº 0 — ABSOLUTA

```python
MOTOR_MAX_POWER_PCT      = 15.0   # Teto de potência (%)
MOTOR_EMERGENCY_STOP_PCT = 20.0   # ≥ 20% → desliga tudo imediatamente
JOYSTICK_TIMEOUT_MS      = 200    # Sem pacote → força velocidade = 0
```

Esta regra está em `core/motor_driver.py → _apply_safety_clip()`.
**NUNCA** remova ou contorne esta verificação. Em qualquer novo código que
escrever para os motores, chame sempre `_apply_safety_clip()` antes de
enviar qualquer valor ao GPIO.

## ⚠️ NÚCLEO MOTOR — PINOS VALIDADOS FISICAMENTE

Estes valores foram testados no robô real. **NÃO ALTERAR** sem teste físico.

```python
# Motor Esquerdo
PIN_DIR_E   = 5    # Direção
PIN_BREAK_E = 6    # Freio
PIN_PWM_E   = 18   # Velocidade (PWM 20Hz)
PIN_HALL_E  = 16   # Encoder Hall

# Motor Direito
PIN_DIR_D   = 23
PIN_BREAK_D = 24
PIN_PWM_D   = 12
PIN_HALL_D  = 17

# Lógica direcional (CRÍTICO):
# Motor ESQUERDO: HIGH = frente | LOW = trás
# Motor DIREITO:  LOW  = frente | HIGH = trás  ← OPOSTO por fiação
```

**PID calibrado:** Kp=0.26, Ki=0.23, Kd=0.0, limits=(-90, 90)
**Encoders:** polling a 1000Hz com debounce de 10ms (não usar add_event_detect)

## Legado aproveitado do robo_slam v1

O repositório antigo (https://github.com/francenylson1/robo_slam) foi arquivado.
Os seguintes elementos foram migrados para este projeto:

| O que foi migrado         | Onde está agora              | Status    |
|---------------------------|------------------------------|-----------|
| Pinos GPIO dos motores    | config/settings.py           | ✅ Pronto |
| Lógica direcional         | core/motor_driver.py         | ✅ Pronto |
| PIDController             | core/pid_controller.py       | ✅ Pronto |
| Encoders Hall (polling)   | core/motor_driver.py         | ✅ Pronto |
| JoystickController        | core/joystick_reader.py      | ✅ Pronto |
| Detecção Pi vs PC (MOCK)  | config/settings.py           | ✅ Pronto |

## Fases do projeto

```
Fase 0   — Fundação            → CONCLUÍDA (estrutura criada, pinos documentados)
Fase 1   — Percepção           → CONCLUÍDA em MOCK (validação física na Pi pendente)
Fase 1.5 — Blindagem           → EM ANDAMENTO (bumper fail-closed, watchdog, systemd, waitress)
Fase 2   — Interface web PRO   → AGUARDANDO (dashboard 4 telas + auth + rosto + voz Piper)
Fase 2.5 — Torre de Controle   → SOFTWARE PRONTO em MOCK (fleet/ + tower/; falta mosquitto na Pi)
Fase 3   — Chassi real         → AGUARDANDO (E-Stop físico, fusíveis, linha reta 2m)
Fase 4   — SLAM autônomo       → AGUARDANDO (Aurora + POIs + chamadas de mesa)
Fase 5   — Piloto comercial    → AGUARDANDO (golden image, QA, operação real)
```

> Plano de produção comercial aprovado (fases 1.5/2.5/5, Torre de Controle,
> riscos de hardware e inovações de produto): `docs/PROPOSTA_PRODUCAO_COMERCIAL.md`

## Hardware disponível

- Raspberry Pi 5 (8GB)
- Slamtec Aurora (SLAM visual-laser, altura fixa: 30cm do solo)
- RPLIDAR C1 (bumper de segurança)
- BNO085 via I2C (IMU, endereço 0x4A)
- ADS1115 via I2C (ADC bateria, endereço 0x48)
- Drivers ZS-X11H V2 (motores hoverboard)
- Step-down SZBK07 (42V → 5.1V/20A)
- Display 7" (HDMI-A-1, expressão facial)
- Display 15.6" (HDMI-A-2, sinalização, áudio mudo)
- Webcam Full HD (stream MJPEG)
- Speaker ativo 6W (saída P2 da Pi)
- Joystick + dongle USB 2.4GHz

## Ambiente de desenvolvimento

- IDE: Cursor com Claude Code (Sonnet 4.6)
- Conexão: Remote SSH via Wi-Fi 5GHz local
- Controle de versão: GitHub (robo_slam_v2)
- Commits: somente em milestones estáveis (uma por fase concluída)
- OS da Pi: RaspiOS 64-bit
- Python: 3.11+

## Como trabalhar neste projeto

1. Sempre leia `config/settings.py` antes de escrever qualquer novo módulo
2. Antes de qualquer saída GPIO, verifique `MOCK_MODE` de settings.py
3. Use `log = logging.getLogger(__name__)` em todos os módulos
4. Nunca use PyQt5 — interface é web (Flask)
5. Nunca use ROS — tudo Python puro
6. Para testar sem Pi: `python3 main.py --mock` ativa o modo MOCK
7. Commits só quando a fase estiver com o Gate de Conclusão 100% verde

## Próxima tarefa (Fase 1.5 — Blindagem)

A Fase 1 foi fechada em MOCK (`scripts/validate_phase1.py` verde). Estado da
blindagem:

1. ✅ `sensors/safety_bumper.py` — **fail-closed** implementado e validado em MOCK:
   sem varredura fresca do LIDAR há > 0.5s → `blocked_front = True`; reconexão
   automática com backoff; saúde do sensor na telemetria (`state["lidar"]`)
2. ✅ Watchdog implementado e validado em MOCK (`core/watchdog.py`, alimentado
   pelo loop 50Hz): modo systemd (WATCHDOG=1) ou `/dev/watchdog` direto
3. ✅ `systemd` pronto (`deploy/frota-robo.service` + `scripts/install_service.sh`):
   Type=notify + WatchdogSec=5 + Restart=always + RuntimeWatchdogSec (HW)
4. ✅ waitress no lugar do dev server do Flask (telemetria convertida de
   WebSocket para SSE — `/events` — pois waitress não suporta WebSocket;
   `flask-sock` removido das dependências)

Gate da Fase 1.5 (provas na Pi):
- [x] Sem dado do LIDAR por 0.5s → robô bloqueado (provado em MOCK; refazer na Pi)
- [ ] Matar o processo Python → freios engatam e o serviço reinicia sozinho
      (`sudo systemctl kill -s SIGKILL frota-robo`)
- [ ] Desconectar o USB do RPLIDAR com o robô rodando → `blocked = ⛔` em ≤ 1s

---

Pode começar! Qual arquivo quer abrir primeiro?
