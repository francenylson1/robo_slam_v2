# WORKFLOW — como se trabalha no projeto

> O fluxo **de fato**, firmado desde 21/09/2026 e registrado como regra em
> 30/09/2026 (decisão do professor). Última revisão: **30/09/2026**.

---

## 1. O ciclo de uma mudança

```
1. CONVERSA DE DESENHO antes de código em peça nova que mexa em segurança
   ou no movimento. Questão por questão; a decisão do professor vai para
   docs/ (arquitetura da fase ou sessão do dia) ANTES do código.
2. MEDIR antes de corrigir. Uma hipótese sem medida não vira código
   (30/09: a 1ª proposta para o comando velho do joystick estava errada e
   a medida do hidraw desmentiu antes de virar código).
3. CÓDIGO no notebook (máquina de desenvolvimento até a Fase 4 —
   docs/AMBIENTE_MULTIPLAS_MAQUINAS.md §7).
4. HARNESS PRIMEIRO: o "robô de mentira" ganha o comportamento que a sala
   mostrou, e o teste novo tem que FALHAR com o código antigo.
5. OS CINCO HARNESSES verdes (README, "Regressão").
6. COMMIT em main — um por mudança coerente, mensagem que diz o porquê e a
   medida — e push.
7. NA PI: git pull, harness de novo, reiniciar o serviço
   ("Localizar na fita" de novo depois).
8. PROVA FÍSICA com o professor (docs/PROTOCOLO_TESTES_MANUAIS.md); o
   resultado — trena, logs, números — vai para a sessão do dia.
```

`main` é o que está no robô: **nada entra sem os cinco harnesses**. Não há
branches de fase (o plano de junho previa `dev/fase-N`; nunca foi usado).

## 2. O dia

| Momento | O quê |
|---|---|
| Início | ler o prompt de retomada (fim de `docs/RETOMAR_AMANHA.md`), a sessão anterior e a memória; apresentar o plano numa **página publicada** |
| Durante | um passo por mensagem na bancada; decisões e resultados na página, com "AGORA" no topo |
| Fim | `docs/SESSAO_AAAA-MM-DD.md` (inclusive os **erros meus** e o que ensinaram), prompt de retomada atualizado, memória, commit, Pi atualizada |

## 3. Comunicação com o professor

- **Terminal curto** (poucas linhas): as mensagens longas cortam no terminal
  dele. Tabelas, roteiros, diagnósticos e conversas de decisão vão para a
  **página do dia** (Artifact), e o terminal só avisa com o link.
- Perguntar **o que o visor mostra exatamente** (o multímetro dele mostra
  infinito como "0.L").
- Não inventar resultado: se a janela de um teste passou, refaz.

## 4. Regras de bancada

- **Parar o robô para bancada:** `sudo systemctl stop frota-rosto frota-robo`,
  conferir os dois `inactive` e `sudo fuser -v /dev/gpiochip0` vazio (o rosto
  religa o robô).
- Scripts de bancada **recusam** rodar com o serviço no ar (e o do Aurora
  exige cliente único).
- Pedir ao professor para desligar a Pi **antes** de cortar a bateria.
- **Inventariar antes de mexer** em boot, vídeo, áudio ou serviço: a Pi tem o
  sistema v1 convivendo; reaproveitar os ganchos dele, não substituir.
- Nada de `echo 0 > …/authorized` numa porta USB com o robô no ar (30/09:
  travou o firmware). Nada de `pkill -f` no mesmo comando SSH que leva um
  script (o padrão casa com o próprio texto).
- Autônomo sempre **supervisionado**: joystick na mão, alguém no PARAR, sala
  sem gente no caminho, bateria ok.

## 5. Colocar um robô novo em operação

Checklist completo no `GUIA_SETUP.md` (Partes 2 e 4). O que não pode faltar:

1. Clone, `.venv --system-site-packages`, `pip install -r requirements.txt`.
2. `config.txt`: `enable_uart=1` e, com step-down sem USB-PD,
   `usb_max_current_enable=1` (Passo 7b). Conferir `pinctrl get 14,15` = `a4`.
3. Receptor do PG-9076 como "shanwan Android GamePad"; acordar pelo HOME.
4. `install_service.sh <id>`, `install_rosto.sh`, `set_web_password.py`.
5. Os cinco harnesses **na Pi**.
6. Provas físicas: bumper (mão à frente 340°–7°, fail-closed puxando o USB),
   BNO (3 níveis), bateria × multímetro, reta 2 m com a malha, procedimento E
   (joystick); com Aurora: procedimento F (braço) e G (base).

## 6. Documentação

| Documento | Papel | Quando atualizar |
|---|---|---|
| `docs/PRD.md` | o quê, para quem, metas, fases | mudou meta, requisito, decisão de produto ou fase |
| `docs/SPEC.md` | como funciona hoje | mudou interface, fluxo ou regra de segurança |
| `docs/WORKFLOW.md` | como se trabalha | mudou o jeito de trabalhar |
| `README.md` | porta de entrada, fases, regressão | junto com o PRD |
| `GUIA_SETUP.md` | montar e operar um robô | aprendeu algo na montagem |
| `docs/PROTOCOLO_TESTES_MANUAIS.md` | provas físicas passo a passo | prova nova |
| `docs/SESSAO_*.md` | registro do dia | **nunca se reescreve** — correções entram no dia em que foram descobertas |
| `docs/RETOMAR_AMANHA.md` | prompt de retomada | fim de todo dia |
| `config/settings.py` | todo número, com a medida no comentário | junto com o código |

Afirmação de segurança **só vale com prova no mundo**, não no barramento — e
toda prova diz também **o que ela não cobre**.
