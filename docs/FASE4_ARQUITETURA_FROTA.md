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

## O que eu preciso verificar antes de recomendar de verdade

Há uma pergunta de fato que eu **não sei responder** e não vou chutar:

> **O SDK do Aurora permite exportar o mapa num formato que outro software
> consiga usar para localização?**

Se sim, a opção B fica bem mais viável: o Aurora faz o mapa bom (visual-laser, a
30 cm) e os outros robôs se localizam nele com o C1. Se não, o mapa do Aurora
fica preso ao Aurora, e sobra construir um mapa 2D próprio com o C1.

Isso se checa na documentação do SDK, e é o primeiro item da Fase 4.

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

| Documento | Precisa de revisão |
|---|---|
| `PROMPT_INICIAL.md:17` | "3 robôs autônomos" — reescrever conforme a decisão |
| `PROPOSTA_PRODUCAO_COMERCIAL.md:211` | gate "3 autônomos" — idem |

Nenhuma dessas linhas deve ser alterada sem a decisão do professor. Ficam
registradas aqui como **pendentes de revisão**, para que a próxima sessão não
volte a tratar "3 autônomos" como se fosse fato resolvido.
