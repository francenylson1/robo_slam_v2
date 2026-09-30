# PRD — Frota Mista v2 (o quê, para quem, com que meta)

> **Estado atual em poucas páginas.** O detalhe mora nos documentos citados;
> aqui não se copia, aponta-se. Atualizar este arquivo quando mudar uma meta,
> um requisito, uma decisão de produto ou o estado de uma fase.
> Última revisão: **30/09/2026**.

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
  (`docs/FASE4_ARQUITETURA_FROTA.md`).
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
   Torre, joystick, bumper e watchdog cancelam a missão, e ela **não retoma**.
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
- **Camada 3** (acima de 22 cm): em observação; o autônomo segue supervisionado.

## 7. Decisões de produto em aberto

| Tema | Pergunta | Onde |
|---|---|---|
| Missão com 2+ POIs | como espera em cada POI; quem define a ordem; volta à base no fim? | `docs/SESSAO_2026-09-30.md` §1 |
| Outro ambiente | "pacote de ambiente" (mapa, planta, áreas, POIs, fita) escolhido pelo operador | idem |
| Robôs sem Aurora | **Caminho escolhido em 30/09: C1 a 22 cm + mapa gravado pelo próprio C1 no robô 1 (o Aurora é o topógrafo).** Teste offline: ~5 cm. Câmera e marcas no teto descartadas pelo professor; Aurora em todos inviável (~US$ 4.000 cada). Plano B: 2º C1 no topo a 1,45 m (US$ 69). Falta: desenho, construção e prova no robô 2 | `docs/SESSAO_2026-09-30.md` §11 |
| Robô 2 | o C1 único fica no robô 1; empréstimo em janela combinada; chegam mais em ~10 dias | `docs/SESSAO_2026-09-30.md` §1 |
