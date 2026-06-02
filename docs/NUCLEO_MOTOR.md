# Núcleo Motor — Documentação Formal

> **Status:** VALIDADO FISICAMENTE — NÃO ALTERAR SEM TESTE NO ROBÔ  
> **Fonte:** `robo_slam v1` · tag `v1.0-estavel-base` · commit `d3727e0`

---

## Mapeamento de Pinos GPIO (BCM)

| Motor    | Sinal  | Pino GPIO | Observação                    |
|----------|--------|-----------|-------------------------------|
| Esquerdo | DIR_E  | 5         | Direção                       |
| Esquerdo | BRK_E  | 6         | Freio — HIGH = freado         |
| Esquerdo | PWM_E  | 18        | Velocidade — 20Hz, 0–100%     |
| Esquerdo | HALL_E | 16        | Encoder — entrada PUD_DOWN    |
| Direito  | DIR_D  | 23        | Direção                       |
| Direito  | BRK_D  | 24        | Freio — HIGH = freado         |
| Direito  | PWM_D  | 12        | Velocidade — 20Hz, 0–100%     |
| Direito  | HALL_D | 17        | Encoder — entrada PUD_DOWN    |

---

## Lógica Direcional

```
Motor ESQUERDO:
  DIR_E = HIGH  →  FRENTE
  DIR_E = LOW   →  TRÁS

Motor DIREITO (⚠️ OPOSTO ao esquerdo — por design de fiação):
  DIR_D = LOW   →  FRENTE
  DIR_D = HIGH  →  TRÁS
```

### Comandos de movimento

| Movimento     | Motor Esquerdo | Motor Direito |
|---------------|---------------|---------------|
| Frente        | +pct (HIGH)   | +pct (LOW)    |
| Trás          | -pct (LOW)    | -pct (HIGH)   |
| Girar direita | +pct (frente) | -pct (trás)   |
| Girar esquerda| -pct (trás)   | +pct (frente) |
| Parar         | 0%            | 0%            |

---

## PID — Ganhos Calibrados

```python
Kp = 0.26
Ki = 0.23
Kd = 0.0
output_limits = (-90.0, 90.0)
loop_hz = 20  # 50ms por ciclo
```

Estes valores foram obtidos após sessões de calibração física com o robô
real em linha reta. Reduzir `Kp` causa deriva; aumentar `Ki` causa
oscilação. Ajustar somente com ferramenta de calibração e gráfico de TPS.

---

## Encoders Hall

- Tipo: sensor Hall por polling (não usa `add_event_detect` — instável)
- Frequência de polling: 1000Hz (1ms de intervalo)
- Debounce: 10ms (filtra ruído mecânico)
- Atualização de velocidade: a cada 100ms (10Hz)
- Unidade: TPS (ticks por segundo)

---

## Regra de Segurança Nº 0

```
MOTOR_MAX_POWER_PCT      = 15.0   ← Teto de potência permitido
MOTOR_EMERGENCY_STOP_PCT = 20.0   ← Aciona shutdown total
```

Implementada em `core/motor_driver.py` → `_apply_safety_clip()`.  
Presente em TODOS os caminhos de comando (set_speed, loop PID, joystick).

---

## Histórico de Problemas Resolvidos (do v1)

| Problema                          | Solução                                      |
|-----------------------------------|----------------------------------------------|
| Inversão de direção               | DIR_D é oposto ao DIR_E — validado em gpio_test.py |
| Robô desviando para a direita     | Calibração PID com Kp=0.26, Ki=0.23          |
| Encoder instável com event_detect | Substituído por polling com debounce de 10ms |
| Giro de retorno ~90° em vez de 180° | Limitação conhecida — a corrigir na Fase 4  |
