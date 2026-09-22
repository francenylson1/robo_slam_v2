# O furo do plano único — por que o robô bateu numa mesa

> Achado em 22/09/2026, durante os testes da reta da Fase 3. **Primeira colisão
> real do projeto.** Não é defeito do bumper: é um limite estrutural que nenhum
> ajuste de software resolve.

---

## O que aconteceu

Durante um percurso de 20 s a 12%, o robô andou quase reto pela linha e **bateu
numa mesa**. O bumper do LIDAR não o impediu.

O professor descreveu o local: era o **vão aberto da mesa**, entre as pernas,
sem nada no caminho naquela altura — apenas cadeiras nas laterais.

---

## Por que o bumper não viu

O RPLIDAR C1 é um sensor **2D**. Ele varre **um único plano horizontal**, na
altura em que está montado.

| Medida | Valor |
|---|---|
| Altura do LIDAR | **22 cm** do chão |
| Altura do robô (colunas) | **140 cm** |
| Faixa vigiada | **22 cm**, uma linha |
| Faixa NÃO vigiada | de 0 a 22 cm e de 22 a 140 cm |

O feixe passou **por baixo do tampo** e **pelo vão entre as pernas**. No plano
dele, o caminho estava livre — e o sensor reportou a verdade.

**Quem bateu foi a parte de cima do robô**, 1,18 m acima do plano vigiado.

> O bumper fez exatamente o que sabe fazer. O problema é que **a proteção cobre
> um plano e o robô ocupa um volume.**

---

## Por que isso é grave neste projeto

Este é um **robô garçom**. O obstáculo mais comum do ambiente dele é
**exatamente uma mesa**.

A lista do que é invisível a 22 cm, num salão de eventos:

- **tampos de mesa** (~75 cm) com vão livre entre as pernas;
- **bancadas e balcões**;
- **assentos e encostos de cadeira**, conforme o modelo;
- **braços de pessoas sentadas**, e mãos segurando copos;
- **carrinhos de serviço** com prateleira alta e base recuada;
- qualquer coisa **abaixo de 22 cm**: pés, bolsas, degraus, cabos.

O último item merece atenção própria: o plano único também não enxerga **para
baixo**. Um degrau ou um desnível é tão invisível quanto um tampo de mesa.

---

## As opções, com o que cada uma custa

### 1. Subir o LIDAR

Trocaria um ponto cego por outro: passaria a ver mesas e deixaria de ver pés,
bolsas e degraus. **Não resolve — desloca.**

### 2. Um segundo plano de varredura

Outro LIDAR, mais alto (~1,0 m). Cobre o tampo da mesa e o tronco das pessoas.
Custo de um sensor por robô, **vezes dez robôs**. É a solução mais completa e a
mais cara.

### 3. Ultrassônicos na parte alta ⭐

Dois ou três HC-SR04 apontados para a frente, a ~1,0–1,2 m. Baratos, simples, e
**bons justamente no caso que nos pegou**: superfícies grandes e planas como um
tampo de mesa refletem ultrassom muito bem.

Limitações honestas: campo largo e impreciso, cegos a superfícies muito
inclinadas ou absorventes (toalha de mesa grossa), e não servem para navegação —
só para *"tem algo grande à frente, pare"*.

Para um projeto educacional, tem ainda uma vantagem: é um sensor que os alunos
entendem, montam e testam sozinhos.

### 4. Para-choque físico com microchave

A última linha: uma barra na altura crítica que, ao tocar, aciona uma chave e
para o robô. Não evita o toque — **evita o dano**. Complementar às anteriores,
não substituta.

### 5. Limitar o ambiente

Definir que o robô só opera em corredores livres, com as mesas fora da rota. É
uma decisão de operação, não de engenharia, e vale registrar como possível: num
evento controlado, pode ser suficiente e custa zero.

---

## Recomendação

**Ultrassônicos altos (3) mais para-choque físico (4)**, nessa ordem de
prioridade. Juntos cobrem o volume do robô por sensor e por contato, com custo
compatível com dez unidades.

E isso **muda a sequência do projeto**: o furo é de segurança, e a Fase 4 prevê
**30 minutos de operação autônoma sem supervisão**. Rodar autônomo entre mesas
com um único plano de varredura a 22 cm não é aceitável.

Entra na lista de bancada junto com o ADS1115 e o botão cogumelo — e, dos três,
este é o que tem consequência mais direta sobre a integridade física do robô e
dos convidados.

---

## Decisão do professor (22/09/2026)

Sem dano: o toque foi leve no tampo e ele interveio; nem o robô nem a mesa
sofreram.

**Decisão: registrar o achado e OBSERVAR as ocorrências reais antes de escolher
a solução.** Palavras dele: *"essa segunda camada de proteção deve ficar
registrada e eu vou observar as ocorrências para saber das necessidades reais"*.

É o mesmo critério do botão cogumelo, e é sólido: em vez de comprar sensor por
especulação, acumular evidência de onde o robô realmente bate — que altura, que
tipo de móvel, com que frequência. Um salão de eventos tem geometria própria, e
o dado do salão dele vale mais que a lista genérica acima.

**O que fica pendente até lá:** operação autônoma sem supervisão (Fase 4) em
ambiente com mesas. Enquanto houver só o plano de 22 cm, os percursos autônomos
precisam de rota livre verificada ou de alguém olhando.

**O que registrar a cada ocorrência**, para a decisão vir de dados:

| Campo | Por quê |
|---|---|
| Altura do que foi atingido | define a altura do novo sensor |
| Tipo de móvel | mesa, balcão, cadeira, carrinho |
| Tinha apoio cruzando os 22 cm? | se tinha, é caso de ângulo, não de altura |
| Velocidade e modo | teleop ou autônomo |
| Houve dano? | separa incômodo de risco |

---

## O que NÃO mudar por causa disto

O bumper do LIDAR continua como está: fail-closed, arco de ±30°, 0,50 m,
provado em 21/09. Ele não falhou. O que falta é **outra camada**, para o volume
que ele não cobre.
