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
