# Ambiente de Desenvolvimento Multi-Máquina

> Como trabalhar no mesmo projeto a partir de **4 máquinas diferentes** (Pi do robô,
> desktop Ubuntu, notebook do trabalho, notebook de casa) sem perder trabalho nem
> divergir de versão. Complementa `RETOMAR_AMANHA.md`, que trata do fluxo na Pi.

---

## 1. Papéis das máquinas

As máquinas **não são equivalentes**. Cada uma tem um papel:

| Máquina | Papel | O que roda |
|---|---|---|
| **Raspberry Pi 5 (no robô)** | Alvo real — a única com hardware | Modo REAL: GPIO, I2C (ADS1115), LIDAR, BNO085 (UART-RVC) |
| **Desktop Ubuntu 24** (i7 14700F + RTX) | Estação pesada | MOCK, `validate_phase1.py` / `validate_phase25.py`, **Torre de Controle + mosquitto**, futura simulação SLAM |
| **Notebooks (trabalho / casa)** | Tela e teclado | Cursor **Remote-SSH** → editam arquivos que estão *fisicamente na Pi* |

O **GitHub é a fonte da verdade** (`francenylson1/robo_slam_v2`). Nenhuma máquina é
"a principal": todas clonam, todas empurram.

---

## 2. A regra que evita 90% da dor

> **Nenhuma máquina guarda trabalho não-commitado quando você sai dela.**

Fim de sessão = `commit` + `push`, **mesmo que o trabalho esteja incompleto**, em uma
branch `dev/fase-X`. `main` continua reservada para milestone concluída (convenção já
adotada no `GUIA_SETUP.md`).

```bash
# INÍCIO de sessão — em QUALQUER máquina
cd <pasta do projeto>
git pull --rebase origin main      # ou a branch dev da fase
source .venv/bin/activate          # Linux/Pi  |  .venv\Scripts\activate no Windows

# FIM de sessão — em QUALQUER máquina, mesmo com trabalho pela metade
git add -A
git commit -m "wip: <onde parei e o que falta>"
git push origin dev/fase-X
```

Se você esquecer e for para outra máquina, o trabalho fica preso — e o jeito de
descobrir é justamente o `git status` do início. Por isso o `pull` vem sempre primeiro.

### Passando o contexto entre sessões do Claude Code

Cada máquina inicia uma sessão **nova** do Claude Code, sem memória da anterior. O
documento que carrega o contexto é o `docs/RETOMAR_AMANHA.md` (seção "PROMPT DE
RETOMADA"). Mantenha-o atualizado ao fechar uma fase — ele é o "handoff" entre máquinas.

---

## 3. Setup de cada máquina

### 3.1 Raspberry Pi 5 do robô — já configurada

| Dado | Valor |
|---|---|
| Host | `192.168.0.185` (IP **fixo**, `ipv4.method: manual`, gw `192.168.0.1`) |
| Usuário | `amd` |
| Placa | Raspberry Pi 5 Model B Rev 1.1 — 8 GB |
| SO | Debian 12 **Bookworm `aarch64`** (kernel 6.12.34+rpt-rpi-2712) |
| Projeto | `~/robo_slam_v2`, venv em `.venv` |
| Autenticação | chave `~/.ssh/id_robo_frota` (login sem senha) |

```bash
ssh -i ~/.ssh/id_robo_frota amd@192.168.0.185
```

Para não digitar isso toda vez, em cada máquina sua adicione ao `~/.ssh/config`
(no Windows: `C:\Users\<voce>\.ssh\config`):

```
Host robo1
    HostName 192.168.0.185
    User amd
    IdentityFile ~/.ssh/id_robo_frota
    ServerAliveInterval 30
```

Daí basta `ssh robo1`.

> A chave privada **não vai para o Git**. O ideal é **gerar uma chave por máquina**
> (`ssh-keygen -t ed25519 -f ~/.ssh/id_robo_frota`) e adicionar cada pública ao
> `~/.ssh/authorized_keys` da Pi — assim dá para revogar o acesso de uma máquina
> sem afetar as outras. Instalar a pública em uma máquina nova:
> `ssh-copy-id -i ~/.ssh/id_robo_frota.pub amd@192.168.0.185`

### 3.2 Desktop Ubuntu 24

```bash
sudo apt update && sudo apt install -y git python3-venv python3-pip
cd ~ && git clone https://github.com/francenylson1/robo_slam_v2.git
cd robo_slam_v2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # rpi-lgpio é pulado automaticamente (ver §6)

# Provar que está tudo certo (roda em MOCK — settings.py detecta "PC"):
python3 scripts/validate_phase1.py
python3 scripts/validate_phase25.py
```

Esta é a máquina indicada para hospedar a **Torre de Controle** durante o
desenvolvimento (broker mosquitto + dashboard :5100) — ver `docs/TORRE_CONTROLE.md`.

### 3.3 Notebooks Windows

Duas formas de trabalhar, complementares:

1. **Cursor Remote-SSH → Pi** (principal): os arquivos ficam na Pi, o notebook é só
   tela e teclado. É assim que se testa hardware. Ver `RETOMAR_AMANHA.md`, Etapa 2.
2. **Clone local** (secundária): para escrever código sem a Pi por perto; roda em
   MOCK. `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r requirements.txt`.

> **Finais de linha:** o `.gitattributes` força **LF** em toda a árvore justamente
> porque o repo é editado no Windows e executado no Linux. Não altere isso — scripts
> `.sh` com CRLF não rodam na Pi.

---

## 4. Acesso remoto — de casa, do trabalho, de qualquer lugar

### 4.1 Na mesma rede do robô (trabalho)

Direto: `ssh robo1`. Dashboard do robô em `http://192.168.0.185:5000`.

### 4.2 Fora da rede (de casa) — Tailscale

**Não abra porta no roteador.** SSH exposto na internet, num equipamento que aciona
motores, é risco real. Use uma VPN mesh: sem porta aberta, sem IP público, atravessa
CGNAT e firewall de escola.

```bash
# Na Pi (uma vez)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh
# → imprime uma URL. Abra no navegador e autentique (Google/GitHub).

# Em cada máquina sua (Ubuntu / Windows): instale o Tailscale e entre na MESMA conta.
# Windows: https://tailscale.com/download/windows
```

Depois disso, de qualquer lugar:

```bash
ssh amd@raspberry-185       # MagicDNS resolve o nome dentro da sua tailnet
tailscale status            # ver quem está online
```

Pontos importantes:

- **Não afeta o caráter offline-first do robô.** O túnel serve só ao desenvolvimento.
  Se a internet cair, o robô e a Torre continuam 100% na rede local.
- Exige que a rede onde o robô está tenha saída de internet (hoje tem).
- Plano gratuito: 100 dispositivos — muito além da necessidade.
- Dá para apontar o `Host robo1` do `~/.ssh/config` para o nome Tailscale, e o mesmo
  atalho passa a funcionar dentro **e** fora da rede.

> **Segurança operacional:** nunca comande motores sem linha de visão para o robô.
> Acesso remoto é para editar, instalar, ler telemetria e rodar MOCK — não para
> dirigir. O E-STOP GERAL da Torre (`docs/TORRE_CONTROLE.md`) é retained: um robô
> que ligar depois do acionamento também permanece parado.

---

## 5. O sistema operacional da Pi — decisão registrada

**Não há SO para reinstalar.** Diagnóstico feito por SSH em 21/09/2026:

```
Debian GNU/Linux 12 (bookworm) · aarch64 · kernel 6.12.34+rpt-rpi-2712
Raspberry Pi 5 Model B Rev 1.1 · 8 GB · SD 58 GB (15% usado)
systemctl get-default → graphical.target
/dev/serial0 → ttyAMA10 (OK) · /dev/i2c-1 (OK)
```

O que está instalado **já é** o RaspiOS 64-bit Bookworm que o projeto definiu.
"RaspiOS Lite" **não é um sistema diferente** — é esta mesma instalação sem os
pacotes de desktop: mesmo kernel, mesmo repositório APT, mesma base.

Portanto, para obter o comportamento do Lite (RAM e CPU livres para o loop de 50 Hz,
menos jitter), **não se troca o cartão SD**:

```bash
sudo systemctl set-default multi-user.target
sudo reboot
# Para voltar atrás a qualquer momento:
sudo systemctl set-default graphical.target && sudo reboot
```

Compatível com a **Fase 3**: as telas HDMI (carinha 7" / sinalização 15.6") usarão
pygame/SDL por KMSDRM ou navegador em quiosque — nenhum dos dois precisa de desktop.

Opcionalmente, depois, para recuperar disco (cosmético — há 48 GB livres):

```bash
sudo apt purge -y raspberrypi-ui-mods lightdm && sudo apt autoremove -y
```

### 5.1 Reboot headless é seguro — checklist

Antes de qualquer `sudo reboot` por SSH, confirme que a Pi volta sozinha:

```bash
systemctl is-enabled ssh                          # → enabled
systemctl is-enabled NetworkManager               # → enabled
nmcli -t -f NAME,AUTOCONNECT connection show      # perfil do Wi-Fi com autoconnect=yes
sudo ls /etc/NetworkManager/system-connections/   # perfil salvo em escopo de SISTEMA
```

O perfil precisa estar em `/etc/NetworkManager/system-connections/` (escopo de
sistema, dono `root`) e **não** dentro da sessão do usuário do desktop — é isso que
garante Wi-Fi sem desktop. Na Pi do robô, os quatro itens estão verdes.

### 5.2 Plano B arquivado — boot por USB

Se um dia for realmente necessário instalar um sistema **novo** sem abrir o robô, a
Pi 4 e a Pi 5 bootam de USB. O procedimento é todo por SSH: espetar um SSD/pendrive,
gravar a imagem pela própria Pi (`xzcat imagem.img.xz | sudo dd of=/dev/sda bs=4M
status=progress conv=fsync`), pré-configurar SSH e Wi-Fi via `custom.toml` na partição
de boot, e mudar a ordem de boot no EEPROM:

```bash
sudo rpi-eeprom-config --edit     # BOOT_ORDER=0xf14  (4=USB primeiro, 1=SD depois)
```

**O cartão SD fica intacto como resgate**: se o USB não bootar, o bootloader cai de
volta no sistema atual sozinho. Risco de inutilizar a placa ≈ zero.

Vale considerar essa rota no futuro por **confiabilidade**, não por necessidade: SSD
USB tolera corte de energia muito melhor que cartão SD, e o robô é desligado no tapa
com frequência.

> **Nunca** regrave o próprio cartão SD com a Pi rodando a partir dele. É tecnicamente
> possível (kexec + ramdisk), mas se falhar você perde o acesso e cai exatamente no
> problema mecânico que se quer evitar.

### 5.3 Correção do chassi

Enquanto o chassi está em correção, deixe **acessíveis por fora**: o slot do cartão SD,
pelo menos uma porta USB e o conector de alimentação. Isso elimina de vez a
necessidade de desmontar o robô para manutenção de sistema.

---

## 6. Configuração que NÃO vai para o Git

| Item | Onde vive | Por quê |
|---|---|---|
| `FROTA_MQTT_HOST` | `/etc/frota.conf` na Pi | endereço da Torre muda por instalação |
| `.env` | raiz do projeto (no `.gitignore`) | segredos e ajustes locais |
| `.venv/` | raiz do projeto (no `.gitignore`) | binários específicos de cada arquitetura |
| `data/pois.json`, `data/map.json` | `data/` (no `.gitignore`) | estado de runtime, por robô |
| Chave SSH privada | `~/.ssh/` | nunca versionar |

O `requirements.txt` é **único para todas as máquinas**: o `rpi-lgpio` carrega um
marcador PEP 508 que faz o `pip` pulá-lo fora de ARM Linux —

```
rpi-lgpio>=0.6; sys_platform == "linux" and (platform_machine == "aarch64" or platform_machine == "armv7l")
```

— então o mesmo arquivo instala corretamente na Pi (aarch64), no Ubuntu x86_64 e no
Windows, sem precisar de um `requirements-dev.txt` separado.

---

## 7. Referência rápida

```bash
ssh robo1                                    # entrar na Pi (atalho do ~/.ssh/config)
cd ~/robo_slam_v2 && source .venv/bin/activate
git pull --rebase origin main

python3 scripts/validate_phase1.py           # Gate Fase 1 (na Pi, jitter é veredito)
python3 scripts/validate_phase25.py          # Gate Fase 2.5 (Torre)
python3 main.py --mock --log DEBUG           # smoke sem tocar no hardware
python3 main.py --robot-id 1 --log DEBUG     # modo REAL

i2cdetect -y 1                               # esperado: 0x48 (ADS1115)
ls -l /dev/serial0 /dev/ttyUSB0              # BNO085 (UART-RVC) e RPLIDAR
```

| Recurso | Endereço |
|---|---|
| Dashboard do robô | http://192.168.0.185:5000 |
| Torre de Controle | http://HOST_DA_TORRE:5100 |
| Repositório | https://github.com/francenylson1/robo_slam_v2 |
