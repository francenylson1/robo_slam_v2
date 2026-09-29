# Fase 4 — um Aurora, vários robôs: como isso funciona

> Pergunta do professor em 22/09/2026, e ela expõe uma lacuna real do plano.
> Escrito antes de qualquer código da Fase 4, de propósito.

---

## A pergunta

> "Quando você diz que vamos usar o Aurora para a navegação SLAM, está
> considerando que temos vários robôs e apenas **1 Aurora**? Os mapas serão
> compartilhados? Vamos ter apenas 1 robô com Aurora? E os POIs?"

## O que o projeto assume hoje

| Documento | O que diz |
|---|---|
| `PROMPT_INICIAL.md:17` | **3 robôs autônomos** com SLAM (Slamtec Aurora) |
| `PROMPT_INICIAL.md:18` | 7 robôs assistivos por joystick |
| `PROPOSTA_PRODUCAO_COMERCIAL.md:211` | Gate da Fase 4: **3 autônomos**, 30 min sem colisão |

**O plano prevê três Auroras. Existe um.** Essa lacuna nunca foi discutida, e eu
repeti "o Aurora resolve a pose" sem verificar quantos existem.

---

## A distinção que responde quase tudo

**SLAM são duas coisas, e elas têm naturezas completamente diferentes:**

| | O que é | Quando acontece | Dá para compartilhar? |
|---|---|---|---|
| **Mapeamento** | construir a planta do salão | **uma vez**, antes | **SIM** — é um arquivo |
| **Localização** | saber onde o robô está **agora** | **o tempo todo**, a 10 Hz | **NÃO** — cada robô por si |

O mapa é um retrato do lugar. Ele não sabe nada sobre nenhum robô.

**Um robô sem sensor de localização não sabe onde está, por melhor que seja o
mapa que ele carrega.** É como dar a planta de um shopping a alguém vendado: a
planta está correta e é inútil.

> Então: **os mapas podem ser compartilhados — e isso resolve metade do
> problema.** A metade que sobra é a que custa.

---

## E os POIs? Esses são a parte fácil

POIs (mesa 4, cozinha, base de carga) são **coordenadas dentro do mapa** — um
JSON pequeno. Compartilhar é trivial:

- ficam em `data/pois.json` (hoje fora do git, porque são estado de runtime);
- a **Torre de Controle** distribui para a frota, que é justamente o papel dela;
- todos os robôs recebem as **mesmas** coordenadas.

**POIs não são o problema.** "A mesa 4 fica em (3,2 · 7,8)" vale para todos. O
que difere é cada robô saber que **ele** está em (3,0 · 5,1) agora.

---

## As opções reais, com o que cada uma custa

### A. Um autônomo, nove teleoperados ⭐ para agora

O robô com Aurora navega sozinho; os outros seguem no joystick, como já fazem.

- **Custo: zero.** É o hardware que existe hoje.
- Prova a pilha inteira — mapa, POIs, missões, chamadas de mesa — num robô real.
- O gate da Fase 4 ("3 autônomos") passa a ser cumprido por **1 autônomo + 2
  simulados**, que já é o padrão que a Fase 2.5 adotou para a Torre.
- **Limitação honesta:** é um produto com um robô autônomo, não com três.

### B. Localização pelo RPLIDAR C1 que todos já têm

Todo robô da frota já carrega um C1 (o bumper). Um mapa 2D mais um **filtro de
partículas** permite que cada robô se localize sozinho, sem Aurora.

- **Custo: zero de hardware**, e trabalho de software considerável.
- **Três obstáculos concretos, todos já medidos por nós:**
  1. o C1 está a **22 cm** — ele enxerga **pernas de mesa e de cadeira**, não
     paredes. E cadeiras **mudam de lugar** entre eventos;
  2. tem um **setor cego de 60°** (a coluna do próprio robô), sobrando 300°;
  3. são ~275 pontos por varredura a 13,8 Hz — esparso, mas trabalhável.

O obstáculo 1 é o sério: localizar-se por móveis que se movem é frágil por
construção.

### C. Marcadores fiduciais no teto (ArUco/AprilTag) + câmera barata

Cada robô ganha uma câmera apontada para cima; o teto recebe marcadores
impressos.

- **Custo: uma câmera por robô** (barato) e papel.
- **O teto não muda de lugar.** É por isso que boa parte dos robôs de entrega
  comerciais usa exatamente isso.
- Precisão alta e previsível perto de cada marcador.
- Para um projeto educacional: os alunos imprimem, colam e veem funcionar — o
  conceito é visível, ao contrário de um filtro de partículas.
- **Limitação:** exige preparar o salão. Num evento itinerante, é trabalho a
  cada montagem.

### D. Comprar mais Auroras

Resolve sem invenção. É decisão de orçamento, e eu não sei o preço — mas para
dez robôs de um projeto educacional, é a opção que precisa de justificativa
financeira, não técnica.

---

## A pergunta do mapa: VERIFICADA em 22/09/2026 — e a resposta é SIM

A dúvida era:

> **O SDK do Aurora permite exportar o mapa num formato que outro software
> consiga usar para localização?**

Consultada a documentação oficial do SDK. O que ela diz:

| O que precisávamos | Resposta |
|---|---|
| Exporta **mapa 2D de ocupação**? | **Sim** — componente `LIDAR2DMapBuilder`, com `get_gridmap_dimension()` e `start_lidar_2d_map_preview()` |
| **Salva e carrega** mapas? | **Sim** — `sdk.map_manager.save_vslam_map()` e carregamento pelo MapManager |
| Roda em **ARM64 / Pi 5**? | **Sim** — plataformas suportadas incluem "Linux: x86_64, **ARM64 (aarch64)**" |
| **Python puro**, sem ROS? | **Sim** — SDK oficial em Python (também C++ e ROS 1/2), Python 3.7+ (testado 3.8–3.12; a Pi tem 3.11) |
| Fornece a **pose**? | `sdk.data_provider.get_current_pose()` — posição, rotação, timestamp |

**O mapa NÃO fica preso ao Aurora.** Sai como grade de ocupação 2D — exatamente
o formato que um filtro de partículas consome.

### E o SDK é REMOTO

Ele se chama **Aurora Remote SDK**: o acesso é **pela rede**, não por cabo à Pi
que o consome. Isso dá forma concreta à ideia de "servidor" do professor:

- o Aurora pode ficar num robô e ser **lido pela rede** por outras máquinas;
- mas o que ele entrega pela rede é **o mapa** e **a pose dele mesmo** — nunca a
  posição dos outros robôs, que ele não enxerga.

Fontes:
[SDK Python oficial](https://github.com/Slamtec/py_aurora_remote) ·
[demo e SDK](https://github.com/Slamtec/aurora_remote_sdk_demo) ·
[página do produto](https://www.slamtec.com/en/aurora)

### O que isso muda

A **opção B deixa de estar bloqueada no nível do mapa.** O Aurora levanta a
planta boa (visual-laser, a 30 cm), exportamos a grade 2D, e os outros robôs
passam a ter *onde* se localizar.

O que **continua em aberto** para a opção B não é mais o formato do mapa — são
os três obstáculos do sensor, que já medimos:

1. o C1 está a **22 cm** e enxerga pernas de cadeira, **que mudam de lugar**;
2. **60° de setor cego** (a coluna do robô);
3. ~275 pontos por varredura.

E o trabalho de escrever o filtro de partículas em Python puro.

**A pergunta a responder na bancada mudou**, e ficou mais barata: em vez de
"dá para exportar o mapa?", agora é *"o que o C1 a 22 cm vê no salão é estável
o bastante entre eventos?"*. Isso se responde gravando varreduras do C1 no salão
em dois dias diferentes e comparando — sem escrever uma linha de filtro.

---

## Recomendação

**Fazer a Fase 4 inteira no robô que tem o Aurora** (opção A), e usá-la para
responder as perguntas que hoje são especulação:

- quanto o salão realmente muda entre eventos;
- se o C1 a 22 cm vê estrutura suficiente para localizar;
- se o mapa do Aurora é exportável.

Com isso em mãos, a decisão entre B, C e D deixa de ser opinião.

**E há um argumento de produto a favor disso:** um robô autônomo que leva o
pedido e nove assistivos que os alunos conduzem **é o projeto que você já
descreveu** — inclusão, alunos cadeirantes operando robôs. A autonomia total da
frota é um objetivo, não um requisito da próxima entrega.

---

## O que isso muda no plano

**Revisado em 23/09/2026, com a palavra do professor.** As quatro linhas que
diziam "3 robôs autônomos" foram reescritas como "1 Aurora; as duas versões
(autônoma e assistiva) funcionando; a quantidade em cada uma não é requisito":

| Documento | Situação |
|---|---|
| `PROMPT_INICIAL.md:17` | ✅ reescrita |
| `README.md:13` e `README.md:185` (gate da Fase 4) | ✅ reescritas |
| `PROPOSTA_PRODUCAO_COMERCIAL.md:211` (gate da Fase 4) | ✅ reescrita |

As respostas às quatro observações dele (mapa em tempo real ou arquivo,
dependência da Torre, C1 em todos os robôs, observar antes de decidir) estão em
`ultima_mensagem.md`.

---

## Decisões de 23/09/2026 (revisão fechada com o professor)

1. **O robô funciona sozinho** com a cópia local do mapa e dos POIs; a Torre só
   sincroniza e coordena.
2. **O destino chega por dois caminhos**: a tela touchscreen do próprio robô e um
   botão na Torre, valendo os dois.
3. **Salvaguardas desses dois caminhos** (a primeira exceção à regra "nenhum
   caminho de rede move o robô"):
   - o comando é só "vá até o POI X", nunca velocidade nem direção; POI fora da
     cópia local do mapa é recusado;
   - pela tela do robô, só aceito vindo de localhost (estar no robô é a
     autorização); o `/rosto` segue público, mas não move o robô;
   - pela Torre, exige login na Torre, e o robô confere o POI;
   - **parar sempre vence**: `/api/stop`, E-Stop geral, bumper e watchdog cancelam
     a missão, e o robô não retoma sozinho;
   - todo movimento passa por `motors.set_speed()`, sob o teto de 15%;
   - a varredura da Regra Nº 0 no `validate_phase1.py` permite exatamente esse
     caminho e continua acusando qualquer outro;
   - dois comandos: vale o último; a tela mostra o destino e quem mandou.
4. **Mapa de navegação é arquivo fixo**; o mapa ao vivo serve só para acompanhar
   o mapeamento.

Detalhe e as palavras dele: `ultima_mensagem.md`.

---

## O gravador de varreduras (em operação desde 23/09/2026)

Para a decisão entre as opções B e C com dados, e não com palpite. O `frota-robo`
grava **1 varredura do C1 por segundo** em `data/varreduras/AAAA-MM-DD/HH.jsonl`
(fora do git), sempre que o robô está ligado. O gravador vive dentro do bumper e
só copia o que ele já leu; a seção 7 do `validate_phase1.py` prova que ele não
atrasa nem derruba a segurança. Medido: ~5 KB por varredura, ~18 MB/h, teto de
2 GB (~110 h), apagando as horas mais antigas.

**O teste com o professor, para cada comparação:**
1. Marcar um ponto no chão com fita (e a direção de frente do robô).
2. Em cada dia, estacionar o robô ali e deixá-lo **parado ~2 min**. Anotar a hora.
3. `python3 scripts/compara_varreduras.py data/varreduras/<dia A> --janela-a HH:MM-HH:MM data/varreduras/<dia B> --janela-b HH:MM-HH:MM`

O comparador acha sozinho o giro entre as duas visitas (±15°) e dá o percentual
de graus que concordam. Limiares iniciais: ≥70% aponta para B, ≤40% para C —
a calibrar com as primeiras comparações reais.

**Observação de 23/09:** o campo `yaw` está saindo vazio porque o BNO085 não
está mandando nenhum byte (UART da Pi configurada certo; zero bytes em 2 s).
Pendência de bancada. O comparador não depende do yaw.

---

## Decisão de 25/09/2026 — o mapa e as camadas de proteção

> ⚠️ **A camada 1 foi revista em 28/09/2026** — ver a seção seguinte. As
> camadas 2 e 3 continuam como abaixo.

Contexto: o Aurora do robô 1 entrega profundidade 3D (416×224) e segmentação
semântica (verificado em 25/09). Com **um Aurora só**, a detecção ao vivo por
profundidade não vale para a frota — os outros robôs não a teriam. Decisão do
professor:

| Camada | O quê | Quem vê |
|---|---|---|
| **1 — mapa** | Mapa **2D gerado do 3D**: o Aurora levanta a sala em 3D e a faixa de altura do robô é achatada num 2D que inclui mesas, balcão e o que for fixo | O mapa, copiado para cada robô |
| **2 — ao vivo** | O **RPLIDAR C1** de cada robô (bumper, fail-closed) | Tudo a 22 cm — inclusive pés de mesa e de cadeira |
| **3 — acima de 22 cm** | **Em estudo.** Observar ocorrências antes de escolher a solução | — |

**Ponto técnico para quando o mapa for gerado:** o mapa de **navegação** (faixa
do chão a ~1,40 m, com os tampos de mesa) e o mapa que um robô **sem Aurora** usa
para se **localizar** pelo C1 não são o mesmo. O C1 só enxerga o plano de 22 cm:
para ele, uma mesa são quatro pés, não um tampo. Guardar os dois recortes do 3D
(faixa inteira para navegar; fatia na altura do C1 para localizar) deixa a
opção B aberta sem refazer o mapeamento.

---

## Decisão de 28/09/2026 — camada 1 sem o 3D: mapa 2D + áreas proibidas

Decisão do professor, sobre a avaliação publicada em
https://claude.ai/artifact/6f5LoV5ZorEFRPFeGzzA3n.

| Camada | O quê |
|---|---|
| **1 — mapa** | **Mapa 2D do laser do Aurora** (paredes, para localizar) **+ áreas proibidas desenhadas** à mão sobre ele: mesas, balcão, degraus, o que for fixo. Coordenadas em metros no referencial do mapa, conferidas com trena |
| **2 — ao vivo** | Sem mudança: o RPLIDAR C1 de cada robô (bumper, fail-closed) |
| **3 — acima de 22 cm** | Sem mudança: observar e estudar |

**O 3D fica fora** até a versão 2D + áreas proibidas estar estável. Nem gravar
"de carona" durante o mapeamento.

**Por quê:**

1. O mapa bom de 25/09 é do **laser** do Aurora. O 3D sai das **câmeras
   estéreo**, outro sensor; a qualidade de um não passa para o outro. O
   professor já tinha testado o 3D antes e ele saiu com muito ruído.
2. No 2D achatado do 3D, o ruído dá dois erros. O **obstáculo fantasma** só
   atrapalha. O **buraco** (tampo liso, sem textura, sem pontos) é perigoso:
   o planejador passa por baixo do tampo, que é a colisão de 22/09
   (`docs/SEGURANCA_PLANO_LIDAR.md`). Buraco não se corrige com filtro.
3. Área proibida é determinística: o robô evita exatamente o que foi desenhado.
   Cobre também o que não tem objeto para detectar (degrau, rampa, porta a não
   cruzar) e se ajusta arrastando o polígono quando uma mesa muda de lugar.

**O que as áreas proibidas não resolvem:** só protegem do que foi desenhado;
dependem da pose estar certa (**perdeu a pose, para**, como regra da missão);
objetos soltos continuam com o C1; a camada 3 continua aberta. O 1º autônomo
segue supervisionado.

**A fatia a 22 cm** para a opção B (robôs sem Aurora se localizando pelo C1),
que a decisão de 25/09 tiraria do 3D, passa a vir do próprio C1: o gravador de
varreduras mais a pose do Aurora no robô 1. É o sensor que vai usá-la.

**Referência:** o v1 tinha áreas proibidas (polígonos + A*, em
`old_versions/path_finder.py` e `old_versions/map_manager.py`). No v2 serve de
referência do que o professor já usava; a versão do v2 é escrita do zero, com
verificação nos harnesses.

### Geometria do robô para a margem (medida pelo professor em 28/09)

| Medida | Valor |
|---|---|
| Base | **42 cm** de largura × **60 cm** de profundidade |
| Eixo das rodas motrizes | a **30 cm da frente** — o centro da base |
| Face externa de cada roda | **2,5 cm** para dentro da lateral (rodas dentro da base) |
| BNO085 | centrado na largura, a **22 cm da frente** |
| Aurora | no centro da base, a 1,45 m de altura |
| RPLIDAR C1 | na borda frontal, no eixo — **30 cm à frente** do centro de giro |

**Consequências:**

- O robô **gira em torno do centro da base**. O raio que ele varre ao girar no
  lugar é a meia-diagonal: **√(21² + 30²) ≈ 36,6 cm**.
- O Aurora está sobre o centro de giro: a pose dele, no plano, **já é** a pose
  do centro do robô. Só o rumo precisa conferir com a frente do robô.
- A posição do BNO não entra na margem (o yaw é o mesmo em qualquer ponto da
  base).
- **Margem proposta** (a fixar no planejador): 36,6 cm do robô + 10–15 cm de
  folga de localização → cada área proibida cresce **~47–52 cm**. Com margem
  circular, um corredor entre duas mesas precisa de **~73 cm** livres mais as
  duas folgas. Medir os corredores reais do lab antes de fixar o valor.

**Em aberto:** algo passa para fora da base de 42 × 60 cm (bandeja, tela,
suporte)? Se passar, entra no raio.

---

## Decisões de 29/09/2026 — a pose do Aurora dentro do serviço

Conversa de desenho, sem código, questão por questão, com o professor. Página:
https://claude.ai/artifact/8wzsKqZk2RaBSVfx45Mc1L

**Premissa lembrada por ele:** só o **robô 1** tem Aurora; os demais têm só o
C1. Tudo abaixo precisa deixar esses robôs exatamente como estão.

1. **Onde vive.** `sensors/aurora_pose.py`, com **thread própria** (o loop de
   50 Hz só lê o último valor; nunca espera a rede) e reconexão sozinha com
   espera crescente, como o C1. Risco conhecido: o SDK é nativo (C++); um
   segfault derruba o `frota-robo` inteiro, bumper junto (o robô para e volta
   em ~8 s). Prova de bancada: 1 h ligado e o cabo do Aurora puxado com o
   serviço rodando. Se o SDK derrubar o processo, o Aurora vai para um serviço
   separado **antes** da missão.
2. **Quando a pose vale** — todas de pé:
   1. relocalizou **depois** que o serviço conectou (13 com carimbo novo; um 13
      antigo não conta — o erro de 25/09);
   2. logo após relocalizar, a pose bate com a **fita** (15 cm e 5° de
      x −0,046 · y −0,253 · rumo 125,8°);
   3. leitura com menos de **0,5 s**;
   4. sem **salto** acima de **25 cm ou 15°** entre leituras; depois de um salto,
      só volta a valer após **1 s estável**;
   5. ignora o **1º segundo** depois de conectar;
   6. (verificado no SDK em 29/09: existe `DEVICE_STATUS_TRACKING_LOST = 4`)
      rastreio perdido invalida a pose.
3. **Se falhar.** Assistivo: *fail-soft* — só o dashboard mostra "sem pose" e o
   motivo; o aluno não percebe nada. Missão: *fail-closed* — para, cancela e
   **não retoma** mesmo que a pose volte; sem pose válida a missão nem começa.
   Toda perda vai para o log (hora, motivo, última pose boa). Em missão a pose
   velha é **0,3 s** e o teto é **12%** (a 12%, 0,3 s = ~6,5 cm às cegas).
   **Fala variada**: várias versões pré-geradas no Piper, sorteadas sem repetir
   a última, e **uma fala só por parada**.
4. **Partida.** Botão **"Localizar na fita" só no dashboard, com login**; não
   dispara sozinho no boot. Só com o robô parado (sem comando nos motores,
   joystick solto, encoders parados) e aborta se ele andar. Mapa fixo no
   `settings.py`, conferido pelo sha. Sequência provada: zerar → carregar →
   relocalizar → conferir com a fita. Até ~60 s, com o passo na tela.
5. **Rumo: os dois.** Gira parado até o rumo do **Aurora** apontar para o ponto
   (~5°); anda o trecho com a malha do **BNO** sem mudar os ganhos; a cada
   ~0,5 s o Aurora **desloca a referência** da malha sem zerar o integral. Só
   passam **diferenças** de ângulo (BNO: direita aumenta; Aurora: esquerda
   aumenta), testadas nos dois sentidos. BNO × Aurora divergindo mais de ~10°
   num trecho → a missão para. Em missão o BNO é **obrigatório**. Muda só um
   método em `core/heading_assist.py`; `motor_driver.py` não é tocado.
6. **Um cliente só.** O serviço é o único cliente do Aurora; os scripts de
   bancada se recusam a rodar com o `frota-robo` ativo. Prova futura: um
   segundo cliente só de leitura.
7. **Telemetria e tela.** `/api/status` e Torre: fonte, vale/não vale e motivo,
   x/y em cm, rumo com 0,1°, idade, passo da partida; robôs sem Aurora mandam
   "sem fonte de pose". Dashboard: planta do mapa com o robô, rumo e rastro de
   ~30 s; pose inválida apaga o robô e mostra o motivo. A planta é gerada uma
   vez na bancada, com origem e escala — a mesma das áreas proibidas. 3 s sem
   pacote apaga tudo. `/rosto` não muda. Mapa da frota na Torre fica para
   depois do 1º autônomo.
8. **Gravador.** Cada linha ganha `"pose": [x_cm, y_cm, rumo, idade_s]` ou
   `null`. Dá o mapa a 22 cm e um **gabarito** para medir, com dados, o quanto
   um robô só com C1 se localizaria (decide a opção B). O gravador só copia o
   último valor; nunca chama o SDK.

**Consequências para os robôs sem Aurora:** o Aurora é ligado por robô no
`settings.py`; sem ele o módulo nem sobe (sem alarme, sem tentativa de
conexão); a missão aparece "indisponível: este robô não tem localização"; e a
missão lê a pose por uma **interface genérica de fonte de pose**, com as mesmas
regras de validade — a opção B ou C entra depois como outra fonte, sem
reescrever a missão.

---

## Decisões de 29/09/2026 (tarde) — as áreas, o planejador e a MISSÃO

**Áreas proibidas e POIs: quem desenha é o operador** (pergunta do professor),
no dashboard (`/mapa`), com o login do operador. Desenha só o objeto real; a
margem (`NAV_MARGEM_M`, 50 cm, provisória até medir os corredores) é do
sistema. Versões com histórico; uma pessoa editando por vez; a missão não
começa com o editor aberto. Medidas em metros no painel (a M4 real, 2,00 ×
2,45 m, não saía a dedo). O "marcar ponto aqui" com o robô serve para POIs (o
centro do robô não alcança a quina de uma mesa). Desenho da sala revisto pelo
professor: versão 13, 6 retângulos, 2 POIs de teste.

**Planejador** (`slam/planejador.py`): A* na planta de 5 cm; parede e
"nunca visto" bloqueiam; áreas rasterizadas (miolo e contorno); tudo cresce
pela margem; prefere o meio dos corredores; rota em poucos trechos retos.

**Missão ("vá até o POI X") — as 8 decisões:**

1. **Onde vive:** `slam/missao.py`, chamada a cada ciclo do loop de 50 Hz
   (passo 4). Só `motors.set_speed()`, teto de **12%** na missão. Rota
   calculada uma vez, no começo. O `validate_phase1.py` passa a acusar
   qualquer chamada de `set_speed` fora do joystick (`main.py`), da malha de
   rumo (`core/control_loop.py`), da missão e dos scripts de bancada — e
   qualquer uma em `web/`, `fleet/` ou `tower/`. O dashboard só pede o POI.
2. **Como anda:** girar parado (o Aurora diz quanto, o BNO fecha, erro < 5°)
   → reto a 12% com a malha de rumo, o Aurora corrigindo a mira a cada 0,5 s
   → 8% nos últimos 40 cm → chega a < 15 cm, ou para onde está se passar do
   ponto (sem ré). Parada completa entre trechos. Rumo final se o POI tiver.
   Força do giro: começa em 10% (8% nos últimos 20°), medida na prova P2.
   O jeito de andar é o mesmo para a frota; a pose vem da **interface
   genérica de fonte de pose** — robôs só com C1 veem a missão
   "indisponível" (lembrado pelo professor: só 1 robô tem Aurora).
3. **O que para (cancela e não retoma):** PARAR, E-Stop da Torre, **mexer no
   joystick**, troca para o modo Joystick, **bumper** (decisão: cancelar, não
   esperar), pose inválida (0,3 s) ou rastreio perdido, BNO sem sinal,
   BNO × Aurora > 10°, bateria sem permissão de missão, editor aberto (não
   começa; e o editor não abre com missão rodando), reinício do serviço (a
   missão não é guardada).
4. **Travado ou sem avanço:** avanço mínimo de 5 cm (reto) ou 5° (giro) a
   cada 3 s; encoder × Aurora em 2 s (patinando, rodas no ar, empurrado);
   tempo total ≤ 2 × estimativa + 20 s.
   **Botão "Voltar para a base"** (sugestão do professor): a base é um POI
   fixo — a fita, rumo 125,8° — vindo do `settings.py`; chegada a < 10 cm e
   5°; só com a pose válida (sem pose, quem traz é o joystick).
5. **Quem manda:** primeiro o `/mapa` do dashboard (login): ver a rota → "Ir
   até aqui"; a rota vista é a que o robô segue (se mudar, pede para ver de
   novo). PARAR grande no `/mapa`, sem login. A tela do robô (localhost) e o
   botão da Torre ficam para depois do 1º autônomo.
6. **A voz:** grupos novos (começou, chegou, voltando para a base, chegou na
   base, perdeu a localização, travado), várias versões, uma fala por
   acontecimento. Calado quando quem parou foi o operador, no bumper (fica o
   "Com licença") e com a telemetria parada.
7. **A tela:** quadro "Missão" no `/mapa` (destino, quem, fase, trecho, o que
   falta, tempo; trecho feito em cinza); resultado fica até a próxima; uma
   linha no painel; telemetria para a Torre; rosto sem mudança; histórico em
   `data/navegacao/missoes.jsonl`.
8. **Provas:** P0 harness com robô de mentira → P1 rodas no ar → P2 giro no
   chão (mede a força) → P3 reto curto → P4 com giro → P5 contornando + base
   → **P6 1º autônomo supervisionado** (base → POI → base, sem tocar). A
   partir da P2: o professor com o joystick na mão, alguém com o PARAR,
   sala sem gente no caminho, bateria ok. Calendário: código e P0 em 29/09;
   P1–P6 em 30/09; se alguma não ficar verde, o P6 vai para 01/10.

**Fita (base) mudada em 29/09/2026, depois da P1:** 50 cm para a frente (na
direção do rumo 125,8°), decisão do professor — o piso é marcado de 50 em 50
cm. A antiga ficava a 58 cm da M4 (margem 50): nos calços, com as rodas
girando, o robô cruzou a margem. Nova referência calculada:
`AURORA_FITA = (-0.3388, 0.1526, 125.8)` (folga ~1,07 m); a 1ª partida nela
confere. Também decidido: o modo Autônomo só existe durante uma missão (o
botão 0 do joystick, herdado do v1, deixava o robô em Autônomo sem missão).
