# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# UM AURORA, VÁRIOS ROBÔS — a resposta

Documento completo: **`docs/FASE4_ARQUITETURA_FROTA.md`**

## Primeiro, a parte que é minha responsabilidade

Eu venho repetindo "o Aurora resolve a pose" desde ontem, **sem nunca ter
verificado quantos Auroras existem**. Fui buscar agora:

- `PROMPT_INICIAL.md:17` — "**3 robôs autônomos** com SLAM (Slamtec Aurora)"
- `PROPOSTA_PRODUCAO_COMERCIAL.md:211` — gate da Fase 4: "**3 autônomos**"

**O plano prevê três. Existe um.** Essa lacuna estava no projeto desde o começo
e eu não a levantei.

---

## A distinção que responde quase tudo

**SLAM são duas coisas com naturezas diferentes:**

| | O que é | Quando | Compartilha? |
|---|---|---|---|
| **Mapeamento** | a planta do salão | **uma vez** | **SIM** — é um arquivo |
| **Localização** | onde o robô está **agora** | **o tempo todo** | **NÃO** |

O mapa é um retrato do lugar: ele não sabe nada sobre nenhum robô.

**Um robô sem sensor de localização não sabe onde está, por melhor que seja o
mapa.** É como dar a planta de um shopping a alguém vendado — a planta está
certa e é inútil.

Então, respondendo direto: **sim, os mapas podem ser compartilhados — e isso
resolve metade do problema.** A metade que sobra é a cara.

## E os POIs? São a parte fácil

POIs são **coordenadas dentro do mapa** — um JSON pequeno. A Torre de Controle
distribui para a frota; todos recebem as mesmas coordenadas.

"A mesa 4 fica em (3,2 · 7,8)" vale para todos os robôs. O que difere é cada um
saber que **ele** está em (3,0 · 5,1) agora.

---

## As quatro opções

**A. Um autônomo, nove teleoperados** ⭐ *(recomendo para agora)*
Custo zero. Prova a pilha inteira — mapa, POIs, missões, chamadas — num robô
real. O gate "3 autônomos" passa a ser 1 real + 2 simulados, que é o padrão que
a Fase 2.5 já adotou.

**B. Localização pelo C1 que todos já têm**
Zero de hardware, muito software. Três obstáculos, todos já medidos por nós: o
C1 está a 22 cm e enxerga **pernas de cadeira, que mudam de lugar**; tem 60° de
setor cego; e são 275 pontos por varredura.

**C. Marcadores no teto + câmera barata**
Uma câmera por robô e papel impresso. **O teto não muda de lugar** — é por isso
que boa parte dos robôs de entrega comerciais usa exatamente isso. Os alunos
imprimem, colam e veem funcionar. Exige preparar o salão a cada montagem.

**D. Comprar mais Auroras**
Resolve sem invenção. É decisão de orçamento, não técnica.

---

## O que eu NÃO sei, e não vou chutar

> **O SDK do Aurora permite exportar o mapa num formato que outro software
> use para localização?**

Se sim, a opção B fica bem mais viável. Se não, o mapa fica preso ao Aurora.
Isso se verifica na documentação do SDK — e é o **primeiro item da Fase 4**.

---

## Minha recomendação

**Fazer a Fase 4 inteira no robô que tem o Aurora.** Isso responde, com dados, o
que hoje é especulação: quanto o salão muda entre eventos, se o C1 a 22 cm vê
estrutura suficiente, e se o mapa é exportável.

E há um argumento de produto: **um robô autônomo que leva o pedido e nove
assistivos que os alunos conduzem é o projeto que você já descreveu** — inclusão,
alunos cadeirantes operando robôs. Autonomia da frota inteira é objetivo, não
requisito da próxima entrega.

---

## O que fica pendente de decisão SUA

Duas linhas do plano falam em "3 robôs autônomos". **Não vou alterá-las sem você
decidir.** Ficaram registradas como pendentes de revisão, para a próxima sessão
não tratar isso como assunto resolvido.
