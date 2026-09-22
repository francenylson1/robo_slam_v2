# Última mensagem — o entendimento sobre o Aurora e a frota

> Salvo a pedido do professor. Atualizado em 22/09/2026.
> Documento completo do tema: `docs/FASE4_ARQUITETURA_FROTA.md`

---

# ESTAMOS SINTONIZADOS? — o que eu entendi

Leia e corrija o que estiver diferente do que você pensa.

## 1. Temos 1 Aurora, e isso sempre foi sabido

Você disse que desde o início se sabe que há **um** Aurora, para mapear e servir
de base. Nos arquivos `.md` do repositório só está escrito "3 robôs autônomos com
SLAM (Slamtec Aurora)" — e os PDFs eu não consegui ler (são imagem ou fonte
embutida). Então **aceito sua palavra**: a premissa é 1 Aurora, e a linha dos "3
autônomos" é que está desatualizada.

## 2. A quantidade de autônomos não é requisito

Suas palavras:

> "A quantidade autônoma ou controlada não importa, pois o importante é ter as
> duas versões funcionando."

**Entendido, e isso simplifica tudo.** O objetivo da Fase 4 passa a ser: **provar
que a versão autônoma funciona** — não fazer N robôs autônomos.

## 3. O que o Aurora pode e o que não pode fazer pela frota

| O que ele entrega | Para a frota? |
|---|---|
| **O mapa** do salão | ✅ **sim** — é um arquivo, e é compartilhável |
| **Os POIs** dentro do mapa | ✅ **sim** — JSON pequeno, distribuído pela Torre |
| **A pose dele mesmo** | ✅ sim, pela rede |
| **A posição dos OUTROS robôs** | ❌ **não** — ele não os enxerga |

O último ponto é a única limitação real, e ela não tem contorno: **o Aurora é um
instrumento de medição embarcado, não uma infraestrutura de rastreamento.** Se
ele está no robô 1, quem se localiza é o robô 1.

É a diferença entre **um mapa** e **um GPS**. Compartilhar mapa: dá. Um aparelho
localizar terceiros: não dá.

---

# O QUE EU VERIFIQUEI HOJE (e não estava verificado antes)

Eu tinha deixado em aberto a pergunta "o mapa do Aurora é exportável?", marcada
como "primeiro item da Fase 4". Você apontou isso, e eu fui à documentação
oficial do SDK. **A resposta é sim, e melhor do que eu esperava:**

| O que precisávamos | Resposta |
|---|---|
| Exporta **mapa 2D de ocupação**? | **Sim** — `LIDAR2DMapBuilder`, `get_gridmap_dimension()` |
| **Salva e carrega** mapas? | **Sim** — `sdk.map_manager.save_vslam_map()` |
| Roda em **ARM64 / Pi 5**? | **Sim** — "Linux: x86_64, **ARM64 (aarch64)**" |
| **Python puro**, sem ROS? | **Sim** — SDK oficial em Python 3.7+ (a Pi tem 3.11) |
| Fornece a **pose**? | `sdk.data_provider.get_current_pose()` |

**O mapa não fica preso ao Aurora.** Sai como grade de ocupação 2D — o formato
que um algoritmo de localização consome.

E o SDK chama-se **Aurora *Remote* SDK**: o acesso é **pela rede**. Isso dá forma
concreta à sua ideia de "servidor" — o Aurora pode ficar num robô e ser lido por
outras máquinas pela rede. O que ele serve é o mapa e a pose dele; não a posição
dos outros.

**Fontes:**
- https://github.com/Slamtec/py_aurora_remote
- https://github.com/Slamtec/aurora_remote_sdk_demo
- https://www.slamtec.com/en/aurora

---

# A CONSEQUÊNCIA: a opção B destravou

A ideia de os **outros nove robôs se localizarem com o RPLIDAR C1 que já têm**
estava bloqueada porque eu não sabia se o mapa sairia do Aurora. **Agora sei que
sai.**

O Aurora levanta a planta boa (visual-laser, a 30 cm), exportamos a grade 2D, e
os outros robôs passam a ter **onde** se localizar.

O que **continua em aberto** não é mais o mapa — são os três obstáculos do
sensor, todos já medidos por nós hoje e ontem:

1. o C1 está a **22 cm** e enxerga **pernas de cadeira, que mudam de lugar**;
2. **60° de setor cego** (a coluna do próprio robô), sobrando 300°;
3. ~**275 pontos** por varredura a 13,8 Hz.

Mais o trabalho de escrever o filtro de partículas em Python puro.

---

# A PRÓXIMA PERGUNTA DE BANCADA — e ficou barata

Antes era *"dá para exportar o mapa?"*. Agora é:

> **O que o C1 a 22 cm vê no seu salão é estável o bastante entre eventos?**

E isso se responde **sem escrever uma linha de filtro de partículas**: basta
gravar varreduras do C1 no salão em **dois dias diferentes** e comparar.

- Se a estrutura fixa — paredes, colunas, balcão — aparecer consistente: a
  **opção B é viável**, e a frota inteira pode se localizar sem mais hardware.
- Se o que domina forem cadeiras e mesas que mudam de lugar: o caminho é
  **marcador no teto** (opção C), porque o teto não se move.

É um teste de meia hora, que pode economizar a compra de nove sensores — ou
justificá-la com dados.

---

# RESUMO DO ALINHAMENTO

| Ponto | Situação |
|---|---|
| 1 Aurora, sempre foi assim | ✅ entendido |
| Quantidade de autônomos não é requisito | ✅ entendido |
| Mapas **serão** compartilhados | ✅ confirmado como viável |
| POIs compartilhados pela Torre | ✅ parte fácil |
| Aurora localizar outros robôs | ❌ impossível, e sem contorno |
| Mapa exportável do SDK | ✅ **verificado hoje** |
| Localização dos demais robôs | ⬜ **decisão futura**, com o teste das varreduras |
| Linhas "3 autônomos" nos docs | ⬜ pendentes de revisão sua |

**Se algum desses pontos estiver diferente do que você entende, me diga qual.**
