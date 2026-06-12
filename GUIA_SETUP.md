# Guia de Setup — Frota Mista v2
# Do zero ao Cursor + Claude Code rodando na Raspberry Pi

---

## PARTE 1 — Criar o repositório no GitHub

### Passo 1 — Criar o repositório novo

1. Acesse https://github.com e faça login com sua conta `francenylson1`
2. Clique no botão verde **"New"** (canto superior esquerdo)
3. Preencha:
   - **Repository name:** `robo_slam_v2`
   - **Description:** `Frota Mista v2 — Robô Garçom Autônomo com SLAM`
   - **Visibility:** Public
   - **NÃO marque** nenhuma opção de inicializar (sem README, sem .gitignore)
4. Clique em **"Create repository"**
5. Anote a URL do seu repositório:
   ```
   https://github.com/francenylson1/robo_slam_v2.git
   ```

---

### Passo 2 — Fazer upload do zip no GitHub

**Opção A — Pelo navegador (mais simples):**

1. Na página do repositório recém-criado, clique em **"uploading an existing file"**
2. Extraia o arquivo `robo_slam_v2.zip` que o Claude gerou
3. Arraste a pasta `robo_slam_v2/` completa para a área de upload
4. No campo de commit, escreva: `feat: estrutura inicial — Fase 0 concluída`
5. Clique em **"Commit changes"**

**Opção B — Pelo terminal do seu notebook (recomendado):**

```bash
# 1. Extrair o zip (onde você salvou o download)
cd ~/Downloads
unzip robo_slam_v2.zip
cd robo_slam_v2

# 2. Inicializar git
git init
git add .
git commit -m "feat: estrutura inicial — Fase 0 concluída"

# 3. Conectar ao GitHub e enviar
git branch -M main
git remote add origin https://github.com/francenylson1/robo_slam_v2.git
git push -u origin main
```

---

### Passo 3 — Arquivar o repositório antigo (robo_slam v1)

**Taguear antes de arquivar:**

```bash
# Clone o repo antigo se não tiver localmente
git clone https://github.com/francenylson1/robo_slam.git
cd robo_slam

# Criar tag de referência final
git tag -a "legacy-v1-referencia" \
    -m "Versão legada arquivada. Núcleo motor migrado para robo_slam_v2."
git push origin --tags
```

**Arquivar no GitHub:**

1. Acesse https://github.com/francenylson1/robo_slam
2. Clique em **Settings** (aba superior)
3. Role até a seção **"Danger Zone"** (final da página)
4. Clique em **"Archive this repository"**
5. Digite o nome do repositório para confirmar
6. Clique em **"I understand the consequences, archive this repository"**

> O repositório ficará somente para leitura — você ainda acessa o código
> mas não consegue fazer novos commits acidentais.

---

## PARTE 2 — Configurar a Raspberry Pi

### Passo 4 — Descobrir o IP da Raspberry Pi

Na Raspberry Pi (com teclado e tela conectados), abra o terminal:

```bash
# Ver o IP da Pi na rede Wi-Fi
hostname -I

# Exemplo de saída: 192.168.1.105
# Anote este IP — você vai usar no Cursor
```

**Alternativa — no roteador TP-Link Archer AX73:**

1. Acesse http://192.168.0.1 (ou o IP do seu roteador)
2. Vá em **DHCP → Lista de clientes DHCP**
3. Procure por "raspberrypi" ou o nome que você deu à Pi

**Dica:** Para fixar o IP da Pi (recomendado para o projeto):

```bash
# Na Raspberry Pi — editar a configuração de rede
sudo nano /etc/dhcpcd.conf

# Adicionar no final do arquivo:
interface wlan0
static ip_address=192.168.1.200/24   # escolha um IP fixo livre
static routers=192.168.1.1            # IP do seu roteador
static domain_name_servers=8.8.8.8
```

---

### Passo 5 — Habilitar SSH na Raspberry Pi

```bash
# Na Raspberry Pi — habilitar SSH permanentemente
sudo systemctl enable ssh
sudo systemctl start ssh

# Verificar se está rodando
sudo systemctl status ssh
# Deve mostrar: Active: active (running)
```

**Testar do notebook:**

```bash
# No terminal do seu notebook Windows/Linux
ssh pi@192.168.1.200

# Primeira vez: vai pedir confirmação de fingerprint → digite "yes"
# Senha padrão da Pi: raspberry (mude depois!)
```

**Mudar a senha padrão (segurança):**

```bash
# Na Raspberry Pi
passwd
# Digite a nova senha duas vezes
```

---

### Passo 6 — Clonar o repositório na Raspberry Pi

```bash
# Na Raspberry Pi (via SSH ou terminal direto)

# 1. Ir para o home
cd ~

# 2. Clonar o repositório novo
git clone https://github.com/francenylson1/robo_slam_v2.git

# 3. Entrar na pasta
cd robo_slam_v2

# 4. Instalar as dependências
pip install -r requirements.txt --break-system-packages

# 5. Verificar se instalou tudo
python3 -c "import flask, waitress, cv2, smbus2, pygame; print('Dependências OK!')"
```

---

### Passo 7 — Verificar hardware I2C

```bash
# Na Raspberry Pi — verificar se os sensores estão visíveis no I2C

# Habilitar I2C (se ainda não estiver)
sudo raspi-config
# Interface Options → I2C → Enable

# Instalar ferramenta de diagnóstico
sudo apt install -y i2c-tools

# Varrer o barramento I2C
i2cdetect -y 1

# Saída esperada — você deve ver:
#      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 40: -- -- -- -- -- -- -- -- 48 -- -- -- -- -- -- --   ← ADS1115
# 48: -- -- -- -- -- -- -- -- -- -- 4a -- -- -- -- --   ← BNO085
```

> Se não aparecer, verifique as conexões físicas do I2C
> (pinos 3=SDA e 5=SCL da GPIO) e confirme que os sensores
> estão alimentados corretamente.

---

### Passo 8 — Testar o sistema em modo MOCK

```bash
# Na Raspberry Pi, dentro da pasta robo_slam_v2
cd ~/robo_slam_v2

# Rodar em modo MOCK (sem ativar GPIO real)
python3 main.py --mock --log DEBUG

# Saída esperada (--mock FORÇA o modo MOCK mesmo na Pi):
# 10:30:01 [config] Ambiente: DESENVOLVIMENTO (MOCK forçado) — motor_driver em modo MOCK.
# 10:30:01 [main] Iniciando Frota Mista v2 — Robô ID=1
# 10:30:01 [MotorDriver] Modo MOCK — nenhuma saída física.
# 10:30:01 [BatteryMonitor] Monitoramento iniciado.
# 10:30:01 [SafetyBumper] Modo MOCK — blocked_front sempre False.
# 10:30:01 [main] Dashboard disponível em http://0.0.0.0:5000
# 10:30:01 [main] Loop de controle 50Hz iniciado. Ctrl+C para sair.
#
# Para o modo REAL (GPIO/I2C/LIDAR ativos) rode SEM --mock:
#   python3 main.py --robot-id 1 --log DEBUG
# → "Ambiente: RASPBERRY PI (Pi 5) — modo real ativado."
```

**Testar o dashboard no navegador:**

No seu notebook, abra o navegador e acesse:
```
http://192.168.1.200:5000
```

Deve aparecer o dashboard básico do robô.

---

## PARTE 3 — Configurar o Cursor com Claude Code

### Passo 9 — Instalar o Cursor

1. Acesse https://cursor.sh e baixe para o seu sistema operacional
2. Instale normalmente
3. Na primeira execução, faça login com sua conta GitHub ou crie uma conta Cursor
4. Vá em **Settings → Models** e selecione **Claude Sonnet 4.6** como modelo principal

---

### Passo 10 — Instalar a extensão Remote SSH

1. No Cursor, abra a aba de extensões (Ctrl+Shift+X)
2. Busque por **"Remote - SSH"** (da Microsoft)
3. Clique em **Install**
4. Após instalar, aparece um ícone de monitor no canto inferior esquerdo

---

### Passo 11 — Conectar ao Raspberry Pi via Remote SSH

1. Clique no ícone **><** no canto inferior esquerdo do Cursor
2. Clique em **"Connect to Host..."**
3. Clique em **"+ Add New SSH Host..."**
4. Digite:
   ```
   ssh pi@192.168.1.200
   ```
5. Clique em **"Open Config"** e confirme o arquivo
6. Clique novamente no **><** e selecione `pi@192.168.1.200`
7. Selecione a plataforma: **Linux**
8. Digite a senha da Raspberry Pi quando solicitado
9. Cursor vai instalar automaticamente o servidor SSH remoto na Pi (leva 1-2 minutos)

---

### Passo 12 — Abrir a pasta do projeto no Cursor

1. Com a conexão SSH ativa, clique em **File → Open Folder**
2. No campo de caminho, digite:
   ```
   /home/pi/robo_slam_v2
   ```
3. Clique em **OK**
4. O Cursor vai abrir toda a estrutura do projeto diretamente da Pi

---

### Passo 13 — Configurar o Claude Code no Cursor

1. No Cursor, abra o painel do Claude Code (ícone de chat lateral ou Ctrl+L)
2. No campo de chat, cole o conteúdo completo do arquivo `PROMPT_INICIAL.md`
3. O Claude Code vai ler o contexto e já entender toda a arquitetura do projeto

**Como usar durante o desenvolvimento:**

```
# Exemplos de comandos para o Claude Code no Cursor:

"Abra o arquivo sensors/battery_monitor.py e implemente a 
leitura real do ADS1115 com tratamento de erro"

"Rode python3 main.py --mock e me mostre o log"

"Verifique se o loop está mantendo 50Hz sem jitter — 
adicione medição de tempo em main.py"

"Crie um teste simples para o motor_driver.py em modo MOCK"
```

---

### Passo 14 — Fluxo de trabalho diário

```bash
# INÍCIO DO DIA — na Pi (via terminal do Cursor)
cd ~/robo_slam_v2
git pull origin main          # pega últimas mudanças
python3 main.py --mock        # verifica se tudo ainda funciona

# DURANTE O DESENVOLVIMENTO
# → Claude Code edita os arquivos diretamente na Pi via Cursor
# → Você testa no terminal integrado do Cursor
# → Itera até o Gate de Conclusão da fase ficar verde

# COMMIT DE MILESTONE (somente quando a fase estiver concluída)
git add .
git commit -m "feat: Fase 1 concluída — sensores validados"
git push origin main

# Criar tag de milestone
git tag -a "fase-1-concluida" -m "Gate da Fase 1: todos os critérios verdes"
git push origin --tags
```

---

## PARTE 4 — Atualizar o workflow de fases

### Como saber se uma fase está concluída

Cada fase tem um **Gate de Conclusão**. Só avance quando todos os
critérios estiverem verdes. Use este checklist no terminal:

**Gate da Fase 0 (Fundação):**
```bash
# Verificar SSH funcionando
echo "SSH OK"

# Verificar tensões (com multímetro antes de ligar)
# SZBK07 saída 1: deve marcar entre 5.1V e 5.2V
# SZBK07 saída 2 (step-down 12V): deve marcar 12V

# Verificar I2C
i2cdetect -y 1
# ✓ Deve mostrar 0x48 (ADS1115) e 0x4A (BNO085)

# Verificar repositório
cd ~/robo_slam_v2 && git log --oneline -3
```

**Gate da Fase 1 (Percepção):**
```bash
# 1) Prova de SOFTWARE — harness automático (todas as verificações verdes, exit 0).
#    NA PI (Linux dedicado) o jitter < 5ms vira veredito real.
python3 scripts/validate_phase1.py

# 2) Prova de HARDWARE — leitura REAL (sem --mock), com sensores conectados:
# Bateria (comparar com multímetro, precisão ±0.5V)
python3 -c "
from sensors.battery_monitor import BatteryMonitor
import time
b = BatteryMonitor(); b.start(); time.sleep(6)
print(b.get_status())
"

# LIDAR (objeto físico a 45cm na frente → deve bloquear)
python3 -c "
from sensors.safety_bumper import SafetyBumper
import time
s = SafetyBumper(); s.start(); time.sleep(3)
print('Bloqueado:', s.blocked_front)
"
```

> Detalhes do fluxo Pi → Cursor (SSH) → Git e do ambiente virtual: `docs/RETOMAR_AMANHA.md`.

---

## PARTE 5 — Convenções do projeto

### Nomenclatura de commits

```
feat: nova funcionalidade
fix: correção de bug
docs: atualização de documentação
test: adição de testes
chore: tarefas de manutenção

Exemplos:
feat: implementar leitura real do ADS1115
fix: corrigir timeout do joystick no modo MOCK
docs: atualizar NUCLEO_MOTOR.md com resultados de calibração
chore: Fase 1 concluída — tag fase-1-concluida
```

### Política de branches

```
main          → código estável (somente milestones concluídas)
dev/fase-1    → desenvolvimento da Fase 1
dev/fase-2    → desenvolvimento da Fase 2
```

### Nunca faça no código

```python
# ❌ NUNCA — contorna a Regra 0
GPIO.output(PIN_PWM_E, 50)  # sem passar pelo _apply_safety_clip

# ❌ NUNCA — altera pinos sem teste físico
PIN_DIR_E = 7  # sem validação no robô real

# ❌ NUNCA — importa PyQt5
from PyQt5.QtCore import QObject

# ❌ NUNCA — usa ROS
import rospy

# ✅ SEMPRE — usa o motor_driver para comandar motores
motors.set_speed(left_pct, right_pct)  # Regra 0 aplicada internamente
```

---

## Resumo visual do setup

```
SEU NOTEBOOK (Windows/Linux)
        │
        │ SSH via Wi-Fi 5GHz
        │ (Cursor + Remote SSH)
        ▼
RASPBERRY PI 5
  ~/robo_slam_v2/
        │
        │ git push/pull
        ▼
GITHUB
  francenylson1/robo_slam_v2
  (main branch — somente milestones)
```

---

## Suporte e referências

- Repositório legado (arquivado): https://github.com/francenylson1/robo_slam
- Documentação dos pinos: `docs/NUCLEO_MOTOR.md`
- Contexto para Claude Code: `PROMPT_INICIAL.md`
- Regra de Segurança Nº 0: `core/motor_driver.py → _apply_safety_clip()`
- Plano de produção comercial (fases 1.5/2.5/5, Torre de Controle): `docs/PROPOSTA_PRODUCAO_COMERCIAL.md`
