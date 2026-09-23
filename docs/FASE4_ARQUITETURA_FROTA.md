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
