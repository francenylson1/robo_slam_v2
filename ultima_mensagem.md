# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# A COLISÃO É O ACHADO MAIS IMPORTANTE DO DIA

Mais importante que qualquer ajuste de malha. Registrei em
**`docs/SEGURANCA_PLANO_LIDAR.md`**.

## O que aconteceu, em uma frase

**O LIDAR varre um plano; o robô ocupa um volume.**

| | |
|---|---|
| Altura do LIDAR | **22 cm** |
| Altura do robô | **140 cm** |
| Faixa vigiada | 22 cm — uma linha |
| Faixa cega | 0 a 22 cm, e 22 a 140 cm |

O feixe passou por baixo do tampo e pelo vão entre as pernas. **No plano dele, o
caminho estava livre — e ele reportou a verdade.** Quem bateu foi a estrutura de
cima, 1,18 m acima do que está sendo vigiado.

**O bumper não falhou.** Falta uma camada.

## Por que é grave neste projeto

Você está construindo um **robô garçom**. O obstáculo mais comum do ambiente
dele é **exatamente uma mesa**.

Também invisíveis a 22 cm: balcões, assentos e encostos, braços de pessoas
sentadas, carrinhos com base recuada. E, **abaixo** do plano, pés, bolsas e
degraus — o plano único também não enxerga para baixo.

E a Fase 4 prevê **30 minutos de operação autônoma sem supervisão**.

## A lição de método, que vale mais que o achado

Em 21/09 provamos o bumper fisicamente — mão à frente, bloqueio, fail-closed,
reconexão — e concluímos "bumper provado". **A prova estava certa; a conclusão,
larga demais.** Provamos o bumper **no plano dele**.

Passo a perguntar, em cada validação: *o que este teste NÃO cobre?*

---

# AS OPÇÕES (detalhe no documento)

| | Solução | Avaliação |
|---|---|---|
| 1 | Subir o LIDAR | **não resolve** — troca mesas por pés e degraus |
| 2 | Segundo LIDAR a ~1 m | mais completa, mais cara (×10 robôs) |
| 3 | **Ultrassônicos altos** (HC-SR04 a 1,0–1,2 m) | ⭐ baratos, e bons justamente em superfície grande e plana |
| 4 | **Para-choque com microchave** | última linha: não evita o toque, evita o dano |
| 5 | Limitar o ambiente | custo zero, decisão de operação |

**Recomendo 3 + 4.** Juntos cobrem o volume por sensor e por contato, com custo
compatível com dez robôs. E o ultrassônico é um sensor que seus alunos montam e
entendem sozinhos — o que, num projeto educacional, conta.

---

# O QUE EU PRECISO DE VOCÊ

1. **O robô está danificado? E a mesa?** Você ainda não me disse, e é a primeira
   coisa.

2. **Como quer seguir?**
   - **Parar os testes de percurso por hoje** e retomar quando houver a segunda
     camada de proteção — é o que eu recomendo se houver mesas na sala;
   - **Continuar**, mas só em pista com o caminho **realmente** livre até a
     parede, sem mesas nem bancadas na rota;
   - **Encerrar a sessão** — o gate da Fase 3 já está cumprido desde os 4,34 m.

Sobre a rodada de partida suave que acabou de rodar: os números do sensor
melhoraram (pico de 13,4° para 8,6°, RMS de 4,7° para 3,6°), mas **a medida de
chão foi invalidada pela colisão**. Se formos continuar, essa rodada precisa ser
refeita num trajeto limpo.
