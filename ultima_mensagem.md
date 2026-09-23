# Última mensagem — respostas às quatro observações

> 23/09/2026. Os oito pontos do alinhamento foram **confirmados** pelo professor
> na página de revisão. A versão anterior deste arquivo (os oito pontos) está no
> histórico do Git, commit `4696111`.
> Documento completo do tema: `docs/FASE4_ARQUITETURA_FROTA.md`

---

## Feito hoje

As quatro linhas "3 robôs autônomos" foram reescritas como **"1 Aurora; as duas
versões (autônoma e assistiva) funcionando; a quantidade em cada uma não é
requisito"**:

- `PROMPT_INICIAL.md:17`
- `README.md:13` e `README.md:185` (gate da Fase 4)
- `docs/PROPOSTA_PRODUCAO_COMERCIAL.md:211` (gate da Fase 4)

---

## 1. Mapa em tempo real ou arquivo?

**Os dois existem, mas servem para coisas diferentes.**

- **Em tempo real**: o SDK do Aurora é acessado pela rede. Enquanto ele mapeia,
  um computador (a Torre, por exemplo) pode ir recebendo o mapa e mostrando ele
  crescer na tela. Isso é bom para **acompanhar o mapeamento**.
- **Arquivo**: terminado o mapeamento, o mapa é salvo e vira uma grade 2D. É
  **isso** que os robôs devem usar para navegar.

Por que os robôs não devem navegar num mapa ao vivo: um robô se localiza
comparando o que o LIDAR dele vê com o mapa. Se o mapa muda enquanto ele anda
(uma cadeira arrastada aparece e some), a referência se move debaixo dele. Mapa
de navegação tem que ser **fixo e conferido**. Quando o salão muda de verdade
(mesas reposicionadas), mapeia-se de novo e distribui-se o arquivo novo.

**O fluxo proposto:**
1. O Aurora percorre o salão e mapeia (acompanhado ao vivo na tela).
2. O mapa é salvo, revisado, e os POIs são marcados nele.
3. O arquivo (mapa + POIs) vai para cada robô, que guarda uma cópia local.
4. Na operação, o robô com o Aurora se localiza com o Aurora; os outros, com o
   C1 contra o mesmo arquivo.

**O que ainda não verifiquei:** se o Aurora aceita **vários clientes ao mesmo
tempo** pela rede (por exemplo, o próprio robô e a Torre lendo juntos). Fica
como item a conferir na documentação e na bancada. No fluxo acima isso não é
necessário.

## 2. Todos os robôs com C1 e acesso ao mapa

**Entendido e registrado.** Todos os robôs terão o C1 e a cópia local do mapa
gerado pelo Aurora. O C1 já cuida da segurança (bumper) em todos; a pergunta
aberta é só se ele serve **também** para localizar. Se servir (opção B), a frota
se localiza sem hardware novo. Se não (opção C, marcador no teto), o C1 continua
em todos, para segurança e para desviar de obstáculos, e o mapa continua sendo
usado para planejar o caminho.

## 3. Os robôs ficam dependentes da Torre?

**Não, e isso vira regra de arquitetura.** A Torre **distribui** mapa e POIs;
ela não **guarda** eles para o robô consultar a cada passo. Cada robô tem a
cópia local em disco e navega sem a Torre.

| Com a Torre desligada | Funciona? |
|---|---|
| Robô navega até um POI (teste, demonstração) | ✅ sim, com a cópia local |
| Segurança (bumper, watchdog, teto de 15%) | ✅ sim, é toda local |
| Receber chamada das mesas (botões) | ❌ não, os botões falam com a Torre |
| Ver a frota numa tela só, E-Stop geral | ❌ não, é função da Torre |
| Atualizar o mapa nos robôs | ❌ não, espera a Torre voltar |

**Uma decisão que isso abre — como o robô recebe o destino sem a Torre?** Hoje,
pela auditoria de 22/09, **nenhum caminho de rede move o robô**: dashboard e
Torre só sabem mandar parar. Mandar o robô "ir até a mesa 3" é o primeiro
comando de rede que o põe em movimento, com ou sem a Torre. Caminhos possíveis:

- um **controle físico** no robô (botões ou o próprio joystick escolhendo o POI);
- abrir uma **exceção controlada** na regra: só POIs do mapa, só com login, e
  sempre sob o teto de 15% e o bumper.

Não decido isso sozinho: é mexer numa regra de segurança. Fica para discutirmos
antes de escrever a navegação.

**Proposta de regra (para confirmar):** *o robô tem que funcionar sozinho com a
cópia local; a Torre só sincroniza e coordena.* É a mesma filosofia offline-first
que o projeto já tem.

## 4. Observar e avançar no que for possível

**Sim, e há bastante coisa que não depende da decisão B ou C:**

- **Integrar o Aurora no robô 1** — mapear, salvar, exportar a grade 2D.
- **Marcar POIs no mapa** e guardar mapa + POIs como cópia local.
- **Sincronizar pela Torre** (distribuir o arquivo para os robôs).
- **Navegação autônoma do robô com o Aurora** — que é exatamente o gate da
  Fase 4: provar que a versão autônoma funciona.

E em paralelo, sem custo: um script que **grava varreduras do C1** sempre que o
robô estiver ligado no salão. Os dados vão se acumulando, e quando formos
decidir B ou C já teremos semanas de observação em vez de dois dias.

Os pré-requisitos de bancada continuam valendo antes de rodar autônomo:
**ADS1115** (bateria), **encoder direito** (odometria) e a **segunda camada**
acima do plano do LIDAR.
