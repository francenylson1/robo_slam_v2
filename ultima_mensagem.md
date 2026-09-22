# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# A SUA OBSERVAÇÃO MUDOU O QUE ESTAMOS OTIMIZANDO

> "Cruzou a linha central apenas uma vez e continuou do lado direito, andando
> **em paralelo** a ela, com o sistema fazendo pequenas correções para manter o
> robô paralelo."

Isso é o comportamento **correto** — e mostra o limite do que a malha atual pode
fazer.

## Rumo não é posição

A malha controla **para onde o robô aponta**, não **onde ele está**.

Depois que ele sai de lado, ela consegue endireitá-lo — fazê-lo apontar de novo
na direção certa — mas **não tem como trazê-lo de volta à linha**. Ele não sabe
onde a linha está. Nenhum sensor nosso mede isso.

Então ele faz exatamente o que você viu: corrige o rumo e segue **paralelo à
linha**, carregando para sempre o desvio lateral que acumulou nos primeiros
metros.

**Isso não é defeito. É o que uma malha de rumo faz.** Trazer o robô de volta à
linha exige realimentação de **posição**, e isso chega na Fase 4, com o Aurora —
que sabe onde o robô está no mapa.

## E explica a divergência entre nós

Você contou **1 cruzamento**. O sensor reportou **4**. Não é contradição:

- eu conto cruzamentos do **rumo de referência** (para onde ele aponta);
- você conta cruzamentos da **linha no chão** (onde ele está).

O rumo pode oscilar em torno do certo enquanto a posição fica toda de um lado. O
rótulo do meu relatório estava enganoso e já corrigi — agora ele diz "cruzou o
**RUMO** de referência" e avisa que não é a linha do chão.

Ótimo que você tenha reportado exatamente o que viu, em vez de tentar encaixar
no meu número. Foi assim que a diferença apareceu.

---

# O QUE ISSO MUDA NO AJUSTE

O desvio lateral de 28 cm **nasceu todo no começo**, enquanto o rumo ainda estava
errado. Depois que a malha estabilizou, ele parou de crescer — o robô passou a
andar paralelo.

Ou seja: **quem determina o desvio final é o transiente inicial**, não o
comportamento em regime. O sensor mediu esse transiente: o rumo chegou a
**+25,9°** antes de a correção alcançar.

Para reduzir o desvio, é preciso **reagir mais rápido no começo** — e quem faz
isso é o `kp`, o ganho proporcional, que hoje está em 0,105% por grau. Com 10°
de erro ele produz apenas 1,05% de correção, enquanto o desvio natural do robô
pede uns 5,6%.

Mas **uma coisa de cada vez.** A rodada 2 já está preparada e testa outra
hipótese (limite do integral em 12). Vamos completá-la antes de mexer no `kp`.

---

# O QUE EU PRECISO DE VOCÊ

1. **Robô de volta à linha de partida** — ele está 2,64 m adiante.
2. Me diga **"pode"** para a rodada 2: `ki=0,25`, **limite do integral 12**,
   mesmo percurso.

## O que espero, e o que faço em cada caso

- **Se a excursão máxima cair** (hoje +25,9°) e o desvio lateral também, o limite
  12 fica e partimos para o `kp`.
- **Se ficar igual**, o limite não era o gargalo e vou direto ao `kp`.
- **Se piorar**, volto para 24 e vou ao `kp` de qualquer forma.

Em todos os cenários o próximo passo é o `kp` — a rodada 2 serve para saber se
mexemos nele *além* do limite ou *em vez* dele.
