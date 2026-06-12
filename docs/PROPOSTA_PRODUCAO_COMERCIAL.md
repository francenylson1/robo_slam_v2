# Proposta — Frota Mista v2 **PRO**: do protótipo à produção comercial

> Documento gerado por Claude Code em 12/06/2026, a pedido do Prof. Francenylson,
> após análise completa do repositório `robo_slam_v2` (PROMPT_INICIAL.md, README.md,
> GUIA_SETUP.md, main.py, config/settings.py, core/, sensors/, slam/, web/).

---

## 1. Diagnóstico do que vocês já têm (e está bom)

O projeto tem uma base **acima da média** para essa fase:

- **Regra de Segurança Nº 0** centralizada em `core/motor_driver.py → _apply_safety_clip()`
  (teto 15%, E-Stop em 20%, timeout de joystick 200ms);
- **Modo MOCK transparente** — todo o sistema roda no PC sem GPIO;
- **Loop 50Hz com agendamento por deadline absoluto** e medição de jitter
  (`core/control_loop.py`), reutilizado pelo harness de validação;
- **Configuração 100% centralizada** em `config/settings.py`;
- **Compatibilidade Pi 4 / Pi 5** resolvida via `rpi-lgpio` com encoders por polling.

Isso é arquitetura de gente grande. A proposta abaixo **não joga nada fora** — ela
constrói por cima.

---

## 2. Checagem de hardware primeiro (antes do plano)

### 🔴 Risco 1 — O bumper de segurança falha "aberto" (fail-open)

Em `sensors/safety_bumper.py` (método `_scan_loop`, linhas 61–68): se o RPLIDAR
desconectar ou lançar exceção, a thread morre silenciosamente e `blocked_front`
congela no último valor (geralmente `False`).

**Consequência:** LIDAR morto = robô cego que acha que o caminho está livre.

Para produto comercial circulando entre pessoas (e alunos cadeirantes!), segurança
tem que falhar **"fechada"**: sem dado fresco do LIDAR há mais de ~500ms →
`blocked_front = True` obrigatório, com reconexão automática e alerta no dashboard.

**É a mudança mais importante de todo o projeto.** (~20 linhas de código.)

### 🔴 Risco 2 — Não há parada de emergência física

Todo o E-Stop hoje é software. Se o Python travar, o PWM congela no último duty cycle.

Proposta de hardware (barata):

1. **Botão cogumelo físico** em série com as linhas BREAK dos drivers ZS-X11H
   (freio engatado quando pressionado — independente do software);
2. **Watchdog de hardware da própria Pi** (`/dev/watchdog`, já existe no
   BCM2711/BCM2712 — custo zero): se o loop 50Hz parar de "alimentar" o watchdog,
   a Pi reinicia e os freios voltam ao estado seguro (o `motor_driver` já inicializa
   com freios em HIGH);
3. **Fusível lâmina** no barramento 42V de cada robô.

### 🟡 Risco 3 — Resolução de odometria baixa

20 ticks/volta com roda de 50cm = **2,5cm por tick**. Suficiente para teleoperação
e para SLAM (o Aurora resolve a pose), mas insuficiente para o gate "linha reta 2m"
da Fase 3 usando só encoder.

A boa notícia: vocês já têm o **BNO085** — o `heading_lock` deve ser a fonte
primária de correção de rumo (malha fechada de Yaw), encoder só para velocidade.
O código já aponta nessa direção (`control_loop.py`, passo 3 do loop — comentário
"CORREÇÃO DE RUMO"); só precisa fechar a malha.

### Hardware adicional sugerido por robô (baixo custo, alto retorno)

| Item | Função |
|------|--------|
| Botão cogumelo E-Stop | Parada física independente de software |
| Fusível + porta-fusível 42V | Proteção contra curto no barramento |
| Buzzer 5V | Aviso sonoro de ré/bloqueio (exigência comum com público) |
| LED RGB de status | Verde = ok, amarelo = bloqueado, vermelho = emergência — visível a distância |

Nada disso muda o núcleo motor validado (pinos, PID, lógica direcional intactos).

---

## 3. A inovação central: **Torre de Controle da Frota** (offline-first)

**A analogia:** uma torre de aeroporto. Os aviões voam sozinhos, mas a torre vê
todos ao mesmo tempo. Aqui, a Torre é **uma 11ª Raspberry Pi** (uma Pi 4 dedicada,
sem motores), ligada ao mesmo roteador da frota e à tela de 34".

- Cada robô continua **independente e completo**: anda, mantém seu dashboard
  próprio na porta 5000 e funciona mesmo se a Torre desligar. A Torre só *escuta*
  e *coordena*.
- A comunicação usa **MQTT** — um "grupo de WhatsApp dos robôs": cada robô publica
  mensagens curtas de status ("sou o robô 4, bateria 72%, sem obstáculo") e a Torre
  exibe tudo numa tela só. No sentido inverso, a Torre publica comandos
  ("PAREM TODOS") que todos os robôs obedecem — o E-Stop geral.
- O "carteiro" das mensagens (broker `mosquitto`) roda **na própria Torre**,
  sem internet nenhuma — só a rede local do roteador.

O ganho prático: hoje, para acompanhar 10 robôs, seriam 10 abas de navegador.
Com a Torre, é **uma tela com 10 cartões** (bateria, status, alertas) e um botão
vermelho que para a frota inteira.

Hoje cada robô é uma ilha com seu Flask na porta 5000. Para 10 robôs comerciais,
a peça que transforma "10 robôs" em **"uma frota"** — e que é o diferencial de venda:

```
┌─────────────────────────────────────────────────┐
│  TORRE DE CONTROLE (1 Raspberry Pi 4 dedicada)  │
│  • Broker MQTT (mosquitto) — leve, offline      │
│  • Dashboard da FROTA: 10 robôs numa tela 34"   │
│  • Histórico: bateria, km, alertas (SQLite)     │
│  • E-STOP GERAL: um botão para a frota inteira  │
└──────────────────┬──────────────────────────────┘
                   │ Wi-Fi 5GHz local (sem internet)
   ┌───────┬───────┼───────┬───────┐
   ▼       ▼       ▼       ▼       ▼
 Robô 1  Robô 2  Robô 3 ... Robô 10
 (cada um mantém seu dashboard local na :5000)
```

- **MQTT** é o padrão da indústria para isso: roda 100% offline, consome quase nada,
  e cada robô só publica o `state` que **já existe** no `main.py`
  (`battery`, `blocked`, `mode`, `loop`). É uma thread a mais, ~50 linhas por robô.
- O **E-Stop geral via MQTT** é um recurso que clientes (escolas, eventos,
  restaurantes) percebem imediatamente como "produto sério".
- A telemetria histórica em SQLite vira **manutenção preditiva**: "Robô 4 está
  descarregando 20% mais rápido que a média → verificar bateria" — argumento de
  venda de contrato de manutenção.

---

## 4. Inovações de produto (o que diferencia comercialmente)

### 4.1 Personalidade do robô

Vocês já têm o display 7" reservado para expressão facial e o speaker 6W. Proposta:

- **Rosto animado** em HTML/Canvas servido pelo próprio Flask (sem dependência nova),
  com estados ligados à telemetria real: feliz = navegando, "olhando" para o lado
  bloqueado quando o LIDAR detecta obstáculo, sono = bateria baixa;
- **Voz em português offline com Piper TTS** (roda bem na Pi 4/5, sem nuvem,
  mantendo o offline-first). Robô que fala "Com licença!" quando bloqueado é o que
  faz cliente filmar e divulgar de graça.

### 4.2 Chamada por botão de mesa (ESP32)

Botões físicos baratos nas mesas publicam no MQTT → o robô autônomo mais
próximo/livre atende o POI daquela mesa. Transforma a Fase 4 (SLAM) num **serviço
completo de garçom**, não só "robô que anda sozinho". Cada ESP32 custa pouco e o
protocolo já estará pronto (MQTT da Torre).

### 4.3 Acessibilidade como produto, não acessório

Para os 7 robôs assistivos: **perfis de joystick por usuário** (sensibilidade,
curva de aceleração, modo "uma mão") salvos em JSON e selecionáveis no dashboard.

Para alunos cadeirantes isso é a diferença entre usável e frustrante — e é um
diferencial que **nenhum robô garçom chinês de prateleira tem**. É a história do
Aluno Maker Digital virando especificação técnica.

### 4.4 Identidade industrial por robô

- **QR code adesivo** no chassi → abre o dashboard daquele robô;
- Número de série + `robot_id` lido de `/boot/frota.conf` (não de argumento de
  linha de comando);
- **Imagem "golden" do cartão SD**: gravar cartão → editar 1 arquivo → robô novo
  pronto. É isso que torna a fabricação de 10 (ou 50) unidades viável.

---

## 5. Endurecimento para produção (o "chato" que não pode faltar)

| Item | Situação atual | Ação |
|------|----------------|------|
| Boot automático | Precisa de SSH + `python3 main.py` | **systemd service** com `Restart=always` — robô liga na tomada e funciona |
| Servidor web | Dev server do Flask (`app.run` em `main.py`) — não recomendado para produção | Trocar por **waitress** (WSGI de produção, puro Python) |
| Autenticação | Qualquer pessoa na rede Wi-Fi para/controla o robô | Token simples + rede Wi-Fi dedicada da frota |
| LGPD | Webcam MJPEG em escola, com menores | Manter 100% local (já é), aviso visível no chassi, **toggle de privacidade** no dashboard |
| Atualização | `git pull` manual robô por robô | **OTA controlado**: tag assinada + script na Torre com rollback automático se o gate de validação falhar no boot |

---

## 6. Roadmap revisado

### Passo 0 — Preparação do ambiente (pré-requisito operacional)

Antes de qualquer fase nova, vale o que **já está documentado no repositório**:

1. **`docs/RETOMAR_AMANHA.md`** — runbook atualizado: **RaspiOS Lite 64-bit
   (sem desktop)**, pacotes de sistema, I2C, clone do GitHub, venv com
   `--system-site-packages`, validação do gate na Pi e conexão do Cursor via
   Remote-SSH (inclui o prompt de retomada para o Claude Code na Pi);
2. **`GUIA_SETUP.md`** — descoberta de IP, IP fixo, habilitar SSH, configuração
   inicial do Cursor (Passos 4–13) e convenções de commit/branch.

A ordem operacional completa é: **Passo 0 (preparar a Pi) → validar Fase 1 no
hardware real → Fase 1.5 em diante**. Obs.: a Fase 1.5 é quase toda software
testável em MOCK — pode ser adiantada no notebook enquanto a Pi não fica pronta.

| Fase | Conteúdo | Gate de conclusão |
|------|----------|-------------------|
| **1.5 — Blindagem** *(novo, 1ª prioridade)* | Bumper fail-closed, watchdog HW, systemd, waitress | Matar o processo → robô freia e reinicia sozinho |
| **2 — Interface PRO** | Dashboard 4 telas + auth + rosto animado + voz Piper | Demo nos 4 tamanhos, robô "fala" |
| **2.5 — Torre de Controle** *(novo)* | MQTT + dashboard frota + E-Stop geral + SQLite | 2 robôs (ou 1 real + 1 MOCK no PC) na mesma tela |
| **3 — Chassi real** | E-Stop físico, fusíveis, buzzer, linha reta 2m c/ BNO085 | E-Stop testado, 2m com desvio < 5cm |
| **4 — SLAM + Missões** | Aurora + POIs + botões de mesa | 3 autônomos, 30min sem colisão, atendendo chamadas |
| **5 — Piloto comercial** *(novo)* | Golden image, QA checklist por unidade, manual, LGPD | 1 dia de operação real sem intervenção técnica |

A **Fase 1.5 é curta** (poucos dias de trabalho) e quase toda testável em MOCK no
fluxo atual — e é o que separa "protótipo impressionante" de "produto que pode
circular perto de aluno cadeirante com assinatura do professor embaixo".

---

## 7. Recomendação de próximo passo

Começar pela Fase 1.5 — especificamente o **bumper fail-closed**
(`sensors/safety_bumper.py`), que é uma correção pequena (~20 linhas) e elimina o
risco mais sério do sistema atual:

1. Timestamp da última varredura válida (`last_scan_ts`);
2. Propriedade `blocked_front` retorna `True` se `now - last_scan_ts > 0.5s`;
3. Loop de reconexão automática do LIDAR com backoff;
4. Flag `lidar_healthy` exposta na telemetria (dashboard mostra estado do sensor).

Tudo validável em MOCK com o mesmo padrão do `validate_phase1.py`.
