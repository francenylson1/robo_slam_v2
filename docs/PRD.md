# PRD — Frota Mista v2 (o quê, para quem, com que meta)

> **Estado atual em poucas páginas.** O detalhe mora nos documentos citados;
> aqui não se copia, aponta-se. Atualizar este arquivo quando mudar uma meta,
> um requisito, uma decisão de produto ou o estado de uma fase.
> Última revisão: **02/10/2026** (contrato da V1).

---

## 0. Contrato da V1 (decidido pelo professor em 02/10/2026)

Ler antes de propor qualquer frente nova. Ideia nova = dizer a qual objetivo
abaixo ela serve, ou marcá-la como versão futura. Página da reunião:
https://claude.ai/artifact/6nsnY7JC3D1skCZw7fdrtK

**Objetivos da V1**

1. **Robô 1 (com Aurora) = o topógrafo.** Navega com estabilidade, indo e
   voltando de missões aos POIs escolhidos, e faz o mapeamento. **Um mesmo
   mapeamento gera os dois mapas:** o `.stcm` com que o próprio robô 1 navega
   e o mapa de referência com que os robôs sem Aurora se localizam.
2. **Robôs sem Aurora navegam com estabilidade com DOIS C1:** um a 22 cm (o
   bumper, que já existe) e outro a 1,45 m. Os dois juntos são o caminho, não
   há mais "plano B".
3. **Obstáculo não cancela a missão:** o robô **para, espera, fala e retoma**.
   - **Pausa e retoma:** obstáculo visto pelo C1 (pessoa, cadeira, mochila).
   - **Continua cancelando (e não retoma):** PARAR, E-Stop, joystick,
     watchdog, e as falhas do próprio robô: C1 sem dado, pose inválida,
     patinagem, "sem avanço" com caminho livre, bateria.
   - A desenhar antes de codar: tempo de caminho livre para retomar (~2 s,
     sem para-e-arranca); espera longa → fala de tempos em tempos e avisa o
     operador no painel, parado (não volta à base sozinho); ao retomar,
     replaneja de onde está.
4. **Painel gerencia ambientes e mapeamentos:** escolher o ambiente
   (pacote de ambiente, §7) **e** iniciar/salvar um mapeamento pelo painel,
   sem SSH.
5. **Bandeja sem sensor, protegida pela geometria.** Medida dele: a bandeja
   avança **5 cm em cada lateral** (52 cm no total), **começando a 47 cm do
   chão**; não avança na frente nem atrás. O C1 a 22 cm não a protege; quem
   protege é a margem das áreas proibidas, que precisa considerar o contorno
   com a bandeja (ver §6). Mesas no caminho precisam estar desenhadas como
   área proibida.

**Ordem de trabalho proposta:** (1) robô 1 estável (cancelamentos de 01/10,
pose velha) → (2) pacote de ambiente + painel → (3) pausa-e-retoma →
(4) robôs sem Aurora com os dois C1 (robô 2; C1 chegam ~10/10) →
(5) E-Stop físico e base nova, em paralelo conforme a bancada.

**Fora da V1 (versões seguintes):** contornar obstáculo; missão com 2 ou mais
POIs; C1 na diagonal; mapa 3D na navegação; odometria pelas rodas.

---

## 1. O produto

**Frota de 10 robôs garçons** sobre motores de hoverboard, do projeto **Aluno
Maker Digital** (Prof. Francenylson, CRE Recanto das Emas / DF), para uso
**educacional e em eventos**, com foco em **inclusão**: alunos cadeirantes
conduzem robôs assistivos.

- **Duas versões funcionando juntas:** **autônoma** (navega sozinha até um POI)
  e **assistiva** (o aluno conduz pelo joystick). Quantos robôs em cada uma
  **não é requisito** (decisão de 23/09).
- **Um só Slamtec Aurora** (no robô 1). O mapa e os POIs são compartilhados;
  a **localização não**: robô sem Aurora hoje é assistivo
  (`docs/FASE4_ARQUITETURA_FROTA.md`). Na V1 ele passa a se localizar com
  dois C1 (22 cm + 1,45 m) no mapa feito pelo robô 1 (§0).
- **Offline-first**, Python puro, sem ROS, interface web (Flask), sem nuvem.
- Eventos de **~4 horas**: a voz tem que ser variada e o robô confiável sem
  ninguém mexendo em código.

## 2. Quem usa

| Quem | O que faz | Onde |
|---|---|---|
| **Operador** (professor/equipe) | localiza o robô na fita, desenha áreas e POIs, manda "vá até o POI X" / "Voltar para a base", para tudo | dashboard com login (`/`, `/mapa`); Torre (`:5100`) |
| **Aluno** (inclusive cadeirante) | conduz o robô assistivo | joystick PG-9076 (2.4 GHz) |
| **Público do evento** | é servido; vê o rosto e ouve a voz | tela de 7" (`/rosto`, pública, sem controles) e 15,6" (vitrine) |
| **Supervisor** (durante autônomo) | joystick na mão e alguém no PARAR | — |

## 3. Requisitos que não se negociam

1. **Regra de Segurança Nº 0:** teto de **15%** de potência; **≥ 20% →
   Emergency Stop**. Na missão, teto de **12%**. Testada em toda regressão.
2. **Parar sempre vence:** `/api/stop` **fora do login**; PARAR, E-Stop da
   Torre, joystick e watchdog cancelam a missão, e ela **não retoma**.
   **Mudança de 02/10 (§0, item 3):** o bumper que vê um **obstáculo**
   passa a **pausar** a missão (para, espera, fala, retoma), e não mais a
   cancelar. Até a pausa ser desenhada, testada e entregue, o código atual
   (bumper cancela) continua valendo. O bumper **sem dado** continua
   fail-closed e cancela.
3. **Fail-closed onde a segurança depende:** LIDAR sem dado = robô bloqueado;
   pose inválida em missão = para. **Fail-soft** onde é só informação (BNO no
   assistivo, bateria sem sensor).
4. **Honestidade da tela e da voz:** telemetria parada fica **visível e
   calada**; a missão **não diz "chegou"** fora da tolerância; cada situação
   tem a **sua** fala (nada de "estou preso" quando só parou perto).
5. **Só "vá até o POI X"** vem pela rede — nunca velocidade nem direção.
6. **O v2 é o dono do robô**; a régua é excelência, não "funciona".

## 4. Não-objetivos (por decisão)

- ROS, PyQt, nuvem, síntese de voz em operação (o Piper leva ~4 s por frase na
  Pi 5: as falas são geradas na bancada e versionadas).
- **Mapa 3D** para a navegação, até a versão 2D + áreas proibidas estar estável
  (28/09): o 3D do estéreo tem ruído e "tampo liso vira buraco".
- Detecção de obstáculo ao vivo pelo Aurora (só um robô o tem — 25/09).
- Na V1 (02/10): contornar obstáculo, missão com 2+ POIs, C1 na diagonal,
  sensor para a bandeja (§0).

## 5. Fases e gates

| Fase | Gate | Estado (30/09) |
|---|---|---|
| 1 Percepção | sensores lendo, loop 50 Hz < 5 ms | ✅ provado no hardware |
| 1.5 Blindagem | fail-closed, watchdog, systemd | ✅ 21/09 |
| 2 Interface | dashboard 4 tamanhos, auth, rosto, voz | ✅ 22/09 |
| 2.5 Torre | 2+ robôs na tela, E-Stop geral | software ✅ em MOCK; falta prova com 2 robôs |
| 3 Chassi | reta 2 m | ✅ 22/09 — 2,1 cm/m com a malha de rumo |
| **4 Autônomo** | **30 min atendendo chamadas sem colisão, com o assistivo funcionando junto; ADS1115 ligado** | **em andamento** — 1º autônomo 29/09; base 3/3 ≤ 3 cm em 30/09 |
| 5 Piloto | golden image, QA por unidade, 1 dia real sem intervenção | ⬜ |

Detalhe: `README.md` e `docs/PROPOSTA_PRODUCAO_COMERCIAL.md`.

## 6. O que falta para o gate da Fase 4

- **E-Stop físico** (deixa de ser opcional antes dos 30 min) — desenho em
  conversa; atenção: `BREAK=HIGH` solta a roda.
- **Base nova com apoios rígidos 3–5 mm acima do chão** (opção B, 30/09) — os
  rodízios rígidos tiram a roda motriz do chão num desnível de 5 mm.
- "Costura" no reto (medir de novo depois do pivô), telas (7" sem EDID),
  tela do robô e botão da Torre para a missão, mapa da frota na Torre.
- **Camada 3 = bandeja, sem sensor (02/10).** Com 5 cm em cada lateral, o
  canto mais distante passa de 36,6 cm (só a base, 21 × 30 cm do centro) para
  **39,7 cm** (26 × 30 cm). Com `NAV_MARGEM_M = 0,50`, a folga para o erro de
  localização cai de 13,4 cm para **10,3 cm** (o Aurora erra 5–8 cm na sala).
  Decidir se a margem muda; a batida de 01/10 às 16:36 (aba da bandeja numa
  mesa) entra nessa análise.
- **Pausa no obstáculo** (§0, item 3): conversa de desenho → harness → código.

## 7. Decisões de produto em aberto

| Tema | Pergunta | Onde |
|---|---|---|
| Missão com 2+ POIs | **02/10: fora da V1.** Na V1 o operador manda um POI por vez. Perguntas para depois: como espera em cada POI; quem define a ordem; volta à base no fim? | `docs/SESSAO_2026-09-30.md` §1 |
| Outro ambiente | **DECIDIDO em 01/10/2026 (professor): ENTRA NO PROJETO.** O operador escolhe em qual ambiente o robô vai navegar; cada "pacote de ambiente" tem mapa `.stcm` (+ sha), planta, fita, áreas proibidas, POIs e o mapa de referência para os C1. Hoje existem dois mapas: sala (`lab_metade_20260925`) e corredor (`corredor_20261001`, mapeado em 01/10). **02/10:** desenho APROVADO (página https://claude.ai/artifact/3cqZvZGfP4wXKzLiudAaUJ): página "Ambientes" no dashboard do robô 1; troca recusada com missão/editor/andando/mapeamento e aplicada REINICIANDO o serviço; fita física por ambiente; mesmo evento = mover áreas, evento novo = mapear de novo; arquivar, não apagar. **Etapa A (escolher/trocar + migração) feita em software** (`slam/ambientes.py`, `scripts/migrar_ambientes.py`, harness fase 4 seção 19); falta a prova na Pi. Etapa B: mapear pelo painel (gera .stcm, planta, mapas dos C1 a 1,45 m e 22 cm) + medir fita. Etapa C: distribuição (robô 2) | `docs/SESSAO_2026-09-30.md` · `docs/SESSAO_2026-10-01.md` T8 |
| Robôs sem Aurora | **DECIDIDO em 02/10 (§0, item 2): os DOIS C1, a 22 cm e a 1,45 m.** Histórico: caminho escolhido em 30/09: C1 a 22 cm + mapa gravado pelo próprio C1 no robô 1 (o Aurora é o topógrafo).** Teste offline: ~5 cm. Câmera e marcas no teto descartadas pelo professor; Aurora em todos inviável (~US$ 4.000 cada). Plano B: 2º C1 no topo a 1,45 m (US$ 69). **01/10:** a simulação do C1 a 1,45 m no mapa do Aurora deu ~2 cm (otimista: mundo = mapa); o laser real do Aurora passou a ser gravado (`a145`) para a medida de verdade, inclusive 22 cm + 1,45 m juntos. **01/10 tarde, dados reais:** laser do Aurora rebaixado a um C1 (275 pts, 8 m + ruído) localiza a **~5 cm** num mapa montado com as voltas do próprio Aurora (contra a planta de 29/09, ~10 cm — desvio da planta, não do C1). Recomendação: caminho principal = Aurora mapeia, C1 a 1,45 m navega. Falta: corredor, C1 real a 1,45 m (mudança física), gente na altura do peito, o desenho, a construção e a prova no robô 2 | `docs/SESSAO_2026-09-30.md` §11 · `docs/SESSAO_2026-10-01.md` |
| Robô 2 | o C1 único fica no robô 1; empréstimo em janela combinada; chegam mais em ~10 dias | `docs/SESSAO_2026-09-30.md` §1 |
