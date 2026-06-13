# Torre de Controle — Fase 2.5 (Frota Mista v2)

Dashboard único da frota + E-STOP GERAL, 100% offline na rede local.
Analogia: torre de aeroporto — os robôs "voam" sozinhos; a Torre vê todos
e coordena. **Se a Torre cair, cada robô segue 100% funcional** (fail-soft).

---

## Arquitetura

```
┌─────────────────────────────────────────────────┐
│  TORRE (1 Raspberry Pi 4 dedicada, tela 34")    │
│  • mosquitto (broker MQTT local, porta 1883)    │
│  • tower/main.py → dashboard em :5100           │
└──────────────────┬──────────────────────────────┘
                   │ Wi-Fi 5GHz local (sem internet)
   ┌───────┬───────┼───────┬───────┐
   ▼       ▼       ▼       ▼       ▼
 Robô 1  Robô 2  Robô 3 ... Robô 10
 (FleetLink em main.py — cada robô mantém seu dashboard local :5000)
```

## Tópicos MQTT

| Tópico | Sentido | Conteúdo |
|--------|---------|----------|
| `frota/robos/<id>/telemetria` | robô → Torre | JSON a cada 2s (bateria, modo, blocked, lidar, watchdog, loop_hz, fleet_estop) |
| `frota/robos/<id>/status` | robô → Torre | `online` (retained ao conectar) / `offline` (LWT — broker publica se o robô cair) |
| `frota/comandos/estop` | Torre → robôs | `on` / `off` (**retained**: robô que ligar depois do acionamento também para) |

## E-STOP GERAL — como funciona

1. Botão no dashboard da Torre → `POST /api/estop {"on": true}` →
   publica `on` (retained) em `frota/comandos/estop`;
2. Cada robô (assinante em `main.py`) seta `state["fleet_estop"] = True` e
   chama `motors.stop()` imediatamente;
3. O loop 50Hz (`core/control_loop.py`, passo 2b) **re-asserta** `motors.stop()`
   a cada ciclo enquanto a flag estiver ativa — mesmo que algo tente mover;
4. "✅ LIBERAR FROTA" publica `off` e os robôs voltam ao normal.

## Backends do FleetLink (`fleet/link.py`)

- **mqtt** — produção: paho-mqtt → mosquitto da Torre. Reconexão automática;
  broker fora do ar não trava nem derruba o robô.
- **mock** — dev/validação: barramento em memória do processo. Usado pelo
  harness e pelo demo. Escolha automática: MOCK → mock; robô real → mqtt.

## Validação em MOCK (no PC)

```bash
# Harness automático (17 verificações: roteamento, telemetria, E-Stop, retained)
python3 scripts/validate_phase25.py

# Demo interativo: 3 robôs simulados + Torre em http://localhost:5100
python3 scripts/demo_torre.py
```

## Instalação em produção (na Pi da Torre)

```bash
# 1. Broker MQTT (offline, local)
sudo apt install -y mosquitto
# Permitir conexões da rede local (mosquitto 2.x nega remoto por padrão):
sudo tee /etc/mosquitto/conf.d/frota.conf > /dev/null <<'EOF'
listener 1883
allow_anonymous true
EOF
# (Fase 5 / piloto comercial: trocar allow_anonymous por usuário/senha)
sudo systemctl enable --now mosquitto

# 2. Dashboard da Torre
cd ~/robo_slam_v2 && source .venv/bin/activate
python3 -m tower.main          # → http://IP_DA_TORRE:5100
```

## Nos robôs

O `main.py` já integra o FleetLink — basta apontar para o IP da Torre via
variável de ambiente (no systemd, adicione a linha em `/etc/frota.conf`):

```
ROBOT_ID=3
FROTA_MQTT_HOST=192.168.1.250   # IP fixo da Pi da Torre
```

## Gate da Fase 2.5 (prova física)

- [ ] mosquitto rodando na Torre; 2+ robôs reais publicando
- [ ] Dashboard da Torre mostra os cartões atualizando a cada 2s
- [ ] E-STOP GERAL para todos os robôs em ≤ 2s; LIBERAR retorna todos
- [ ] Robô desligado aparece como OFFLINE em ≤ 6s (LWT/staleness)
- [ ] Derrubar a Torre → robôs continuam operando normalmente (fail-soft)
