# Karaokê POS

Sistema de ponto de venda para karaokê. Projeto Django 5.x com Bootstrap 5.3
compilado localmente via Sass (nenhum recurso vem de CDN).

A interface está em português brasileiro (pt-br).

## Estrutura

- **`config/`** – módulo de configurações do Django (`config.settings.dev`).
  - `config/urls.py` – URLs raiz, inclui `core.urls` em `/`.
- **`core/`** – app inicial com a página de landing/login e a home autenticada.
  - `core/views.py` – `LandingLoginView` (envolve `LoginView`) em `/` e
    `HomeView` (stub autenticado) em `/home/`.
  - `core/urls.py` – `/` (login), `/home/` (home) e `/logout/`.
- **`inventory/`** – app de catálogo de itens vendáveis (#107) e das suas
  categorias (#223).
  - `inventory/models.py` – `Category` (nome único, ordenação alfabética) e
    `Item` (nome, FK obrigatória para `Category`, preço, estoque,
    `is_active`). A FK é `PROTECT`: uma categoria com itens vinculados não
    pode ser excluída, mesma convenção usada entre `OrderItem` e `Item`.
  - `inventory/views.py` – CRUD de itens e de categorias (login required) via
    class-based views. A exclusão de categoria em uso é recusada com uma
    mensagem legível em vez de estourar um erro.
  - `inventory/urls.py` – `/estoque/` (lista), `/estoque/novo/` (criar),
    `/estoque/<pk>/editar/` (editar) e `/estoque/<pk>/excluir/` (excluir);
    `/estoque/categorias/` (lista), `/estoque/categorias/nova/` (criar),
    `/estoque/categorias/<pk>/editar/` (editar) e
    `/estoque/categorias/<pk>/excluir/` (excluir). As telas de categoria são
    alcançadas pelo botão "Categorias" na página de estoque — a navbar não
    ganhou entrada nova.
  - `inventory/migrations/0003_seed_starter_categories.py` – data migration
    que semeia as categorias iniciais ("bebidas não alcoólicas", "bebidas
    alcoólicas" e "comidas"), para que um clone novo já suba usável.
  - `inventory/management/commands/seed_demo.py` – comando
    `uv run manage.py seed_demo`, que semeia um catálogo de demonstração em
    pt-BR (ver "Dados de demonstração" abaixo).
  - `inventory/models.py` – `NoteSuggestion` (#230): sugestões de observação
    por item (FK `CASCADE`, `related_name="note_suggestions"`, únicas por
    `(item, texto)`). São editadas no próprio formulário do item, no campo
    "Sugestões de observação" (uma por linha), e o `#232` vai renderizá-las
    como atalhos de um toque ao lançar o item no pedido. Não há FK dos pedidos
    para as sugestões: a observação da linha (#229) é texto livre copiado no
    momento do pedido, então editar ou excluir uma sugestão nunca mexe em
    pedidos passados.
  - `inventory/admin.py` – registra `Item` e `Category` no admin do Django
    como fallback, com as sugestões de observação como inline do item.
- **`tables/`** – app de gestão de mesas (#108).
  - `tables/models.py` – `Table` (nome/número único, lugares, status
    livre/ocupada, `is_active`).
  - `tables/views.py` – lista/visão geral com toggle manual de status +
    criar/editar (login required) via class-based views.
  - `tables/urls.py` – `/mesas/` (lista), `/mesas/nova/` (criar) e
    `/mesas/<pk>/editar/` (editar).
  - `tables/admin.py` – registra `Table` no admin do Django como fallback.
- **`tabs/`** – app de comandas (#222).
  - `tabs/models.py` – `Tab` (nome livre, status aberta/fechada, FK opcional
    para `tables.Table` apenas como referência de entrega, `created_at`,
    `updated_at` e `closed_at`). Não há `is_active`: "fechada" **é** o estado
    de aposentadoria da comanda. Duas comandas abertas não podem ter o mesmo
    nome — a regra é validação no `clean()` do modelo (e não uma coluna
    `unique`) justamente para que o nome volte a ficar livre depois que a
    comanda anterior for fechada. A FK usa `SET_NULL`, então desativar ou
    excluir a mesa não leva a comanda junto.
  - `tabs/views.py` – visão geral (login required) que lista as comandas
    abertas por padrão e alcança as fechadas pelo filtro `?status=closed` na
    mesma tela, mais criar/editar via class-based views. Fechar uma comanda é
    um POST para a própria lista, no mesmo padrão do toggle livre/ocupada de
    `/mesas/`; reabrir está fora de escopo.
  - `tabs/urls.py` – `/comandas/` (lista), `/comandas/nova/` (criar) e
    `/comandas/<pk>/editar/` (editar).
  - `tabs/admin.py` – registra `Tab` no admin do Django como fallback.
- **`orders/`** – app de pedidos (#109, #224, #225, #229, #231).
  - `orders/models.py` – `Order` (FK obrigatória para `tabs.Tab`, FK opcional
    para `tables.Table`, ambas `PROTECT`, status aberta/encerrada,
    `created_at`) e `OrderItem` (FK para o pedido, FK para `inventory.Item`,
    `quantity`, `unit_price` com snapshot do preço no momento do pedido e
    `notes`, a observação livre da linha — "com gelo e limão"). O
    pedido pertence à comanda; a mesa é só contexto de entrega e pode ficar
    vazia; a observação é opcional e o normal é a linha não ter nenhuma.
  - `orders/views.py` – página de abertura de pedido (login required) com
    seleção de comanda (obrigatória, só comandas abertas) + mesa (opcional) +
    formset de itens; o POST roda numa transação única, relê a comanda com
    `select_for_update` e recusa comandas fechadas, valida o estoque de cada
    linha contra o estoque atual, decrementa o estoque e cria o pedido com
    seus itens. Se qualquer linha excede o estoque, toda a submissão é
    rejeitada e nada muda. O fluxo de pedido não escreve mais em
    `tables.Table.status`. Desde #225 a view também entrega ao template os
    dados do seletor por toque — `open_tabs`, `sellable_items` e
    `item_categories` — para a filtragem acontecer no cliente, sem endpoint
    JSON nem polling; o contrato do POST não mudou. Desde #231 a página é um
    assistente de três passos, mas só no cliente: a única coisa que a view
    acrescentou foi `submission_rejected`, para que uma submissão recusada
    volte no passo onde está o problema em vez de num passo 1 em branco. O
    catálogo entregue ao garçom não leva preço nenhum — `unit_price` continua
    sendo gravado no pedido, só não é renderizado na tela de quem anota. Também a tela de cozinha (login required) em `/pedidos/cozinha/`
    que lista todos os pedidos abertos, do mais antigo ao mais recente, em
    cards grandes do Bootstrap; um endpoint de polling em
    `/pedidos/cozinha/fila/` devolve só o fragmento dos cards e um pequeno
    JavaScript no template troca o conteúdo a cada ~5 segundos, sem
    websockets nem framework JS. O botão "Pronto" em cada pedido faz POST
    (com CSRF) para `/pedidos/cozinha/<pk>/pronto/` e muda o status para
    "encerrada"; pedidos encerrados nunca aparecem na tela. Nem a comanda nem
    a ocupação das mesas são tocadas aqui. O card da cozinha usa o nome da
    comanda como título e mostra a mesa embaixo só quando o pedido tem uma.
    Cada linha mostra a observação do garçom (#229) logo abaixo do item, só
    quando ela existe.
    Desde #228 cada card tem também um botão "Imprimir", que faz POST para
    `/pedidos/<pk>/imprimir/` e manda o cupom da cozinha para a impressora
    térmica — ver ["Impressão térmica"](#impressão-térmica-cupom-de-cozinha-228).
    Imprimir **não** mexe no status do pedido: só "Pronto" tira o card da tela.
  - `orders/services/printer.py` – entrega dos bytes ESC/POS à impressora,
    portado do projeto irmão Okinawa POS. Tenta, nesta ordem: o device
    explícito de `KARAOKE_PRINTER_DEVICE`, a fila do sistema (CUPS com
    `lp -o raw` no Linux, spooler RAW no Windows), os devices USB/seriais
    comuns e, por fim, o dump em arquivo do modo de teste. Quando nada
    responde, levanta `PrinterError` com um texto legível.
  - `orders/services/receipts.py` – composição do conteúdo do cupom
    (`ReceiptBuilder`, constantes ESC/POS, `normalize_text` e `strip_escpos`),
    também portado do Okinawa POS. Só o cupom de cozinha é montado aqui:
    cabeçalho com o nome da comanda, a mesa (quando houver), o número do
    pedido e a hora, e uma linha por item com a quantidade — sem preços —
    seguida da observação da linha (#229), recuada sob o item e quebrada na
    largura do papel, quando houver. Os acentos são normalizados para ASCII
    porque as impressoras térmicas usam code pages DOS (CP437/CP850).
  - `orders/urls.py` – `/pedidos/novo/` (abrir pedido), `/pedidos/cozinha/`
    (tela de cozinha), `/pedidos/cozinha/fila/` (polling dos cards),
    `/pedidos/cozinha/<pk>/pronto/` (marcar pedido como pronto) e
    `/pedidos/<pk>/imprimir/` (imprimir o cupom de cozinha).
  - `orders/admin.py` – registra `Order` e `OrderItem` no admin do Django
    como fallback.
- **`templates/orders/order_form.html`** – a página `/pedidos/novo/` (#225,
  #229, #231). Renderiza os campos reais do formulário (select de comanda,
  select de mesa e o formset de linhas) e, quando o JavaScript inicializa,
  esconde os que substitui e passa a dirigi-los. Desde #231 a página é um **assistente de três
  passos** — 1 comanda, 2 itens, 3 confirmação — inteiramente no cliente: são
  três seções (`data-step="1|2|3"`) do *mesmo* formulário que o script mostra e
  esconde, com um único POST no fim, exatamente o contrato de #224/#225.
  - **Passo 1 — Comanda**: busca por nome nas comandas abertas, um toque
    escolhe, mais o select de mesa ("opcional, apenas onde entregar"). Sem
    comanda escolhida o "Avançar" fica desabilitado e a razão aparece acima
    dele.
  - **Passo 2 — Itens**: a lista do que já está no pedido, cada linha com
    stepper de quantidade, campo de observação para a cozinha (#229) e
    "Remover", e a superfície de adicionar item (chips de categoria + busca +
    grade). Essa superfície é um bloco fechado em si (`#add-item-surface`)
    porque #232 vai trocá-la por um modal. Com zero linhas não se avança.
  - **Passo 3 — Confirmação**: recapitulação só de leitura (comanda, mesa ou
    "sem mesa", cada item com a quantidade e a observação, quando houver) e o
    **único** "Registrar pedido" do fluxo — o script também recusa qualquer
    submit vindo de outro passo.

  O indicador de progresso no topo marca o passo atual e os já vencidos; cada
  número é um botão, então dá para voltar tocando nele. Voltar e avançar não
  perdem nada: o estado mora nos campos reais (o select de comanda, o select de
  mesa e os inputs ocultos do formset), não numa cópia do script.

  **Nenhum preço aparece em lugar nenhum do fluxo** (#231): nem nos botões do
  catálogo, nem por linha, nem como total — o garçom só anota. A contabilidade
  de preço saiu do script, não foi escondida.

  Com o JavaScript desligado os três passos simplesmente aparecem empilhados,
  como o formulário longo que a página sempre foi — inclusive o campo de
  observação de cada linha do formset — e enviam normalmente. Quando o
  servidor recusa a submissão (estoque insuficiente, comanda fechada), o erro
  é renderizado *acima* dos passos — visível em qualquer um deles — e o
  assistente se reconstrói a partir das linhas que voltaram, abrindo no passo 2
  (ou no 1, se o problema for a comanda).
- **`templates/base.html`** – esqueleto da página: navbar superior + bloco
  `content` que toda página filha estende. Carrega o CSS compilado localmente e
  o bundle JS do Bootstrap servido localmente. A navbar mostra "Entrar" para
  visitantes deslogados e "Início/Mesas/Comandas/Pedidos/Cozinha/Estoque/Sair"
  para autenticados.
- **`templates/core/landing.html`** – landing page com a marca do restaurante e
  o formulário de login (username/senha) estilizado pelo Bootstrap.
- **`templates/core/home.html`** – home autenticada (stub) que futuros painéis
  vão ampliar.
- **`static/scss/main.scss`** – ponto de entrada do Sass; sobrescreve
  variáveis do Bootstrap **antes** de importá-lo, permitindo customização do
  tema. Define o tema escuro de cantos retos (#203) — ver
  ["Tema escuro"](#tema-escuro-tech-203).
- **`static/css/main.css`** – CSS compilado (gerado, ignorado pelo git).
- **`static/vendor/js/bootstrap.bundle.min.js`** – bundle JS do Bootstrap
  (Popper incluído) servido localmente.
- **`pyproject.toml`** / **`uv.lock`** – metadados e lock das dependências
  Python (Django 5.2.7) gerenciadas via [uv](https://docs.astral.sh/uv/).
- **`package.json`** – deps npm (Bootstrap 5.3 + Sass) e scripts de build.

## Pré-requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (gerenciador de ambientes/dependências Python
  da Astral) — instale seguindo
  <https://docs.astral.sh/uv/getting-started/installation/>
- Node.js 20+ e npm

## Configuração do ambiente (a partir de um clone limpo)

Execute todos os comandos a partir da raiz do repositório. O Python e as
dependências Django são gerenciados pelo `uv`: um `uv sync` cria o ambiente
virtual (`.venv/`) e instala tudo que está no `uv.lock`.

```bash
# 1. Sincronizar o ambiente Python (cria .venv/ e instala as dependências)
uv sync

# 2. Aplicar as migrações do banco de dados (SQLite)
uv run manage.py migrate

# 3. Criar a conta de administrador (único login do sistema por enquanto)
uv run manage.py createsuperuser

# 4. Rodar o servidor de desenvolvimento
uv run manage.py runserver
```

O build do frontend (Bootstrap + Sass) é separado e ainda precisa ser rodado
uma vez, pois nenhum recurso vem de CDN:

```bash
# Instalar as dependências de frontend (Bootstrap + Sass)
npm install

# Compilar o CSS do Bootstrap a partir do Sass e copiar o bundle JS
# (gera static/css/main.css a partir de static/scss/main.scss
#  e copia static/vendor/js/bootstrap.bundle.min.js)
npm run build
```

Abra <http://127.0.0.1:8000/> no navegador. A página de landing/login deve
carregar estilizada pelo Bootstrap compilado localmente, com o tema escuro
aplicado (fundo quase preto, barra de navegação plana com borda inferior) e o
formulário de acesso centralizado.

## Dados de demonstração

Para mostrar o sistema funcionando sem cadastrar item por item na mão, o app
`inventory` traz um comando que popula o catálogo com ~19 itens em pt-BR
plausíveis para um karaokê (refrigerante lata, cerveja long neck, porção de
batata frita, ...), distribuídos pelas três categorias iniciais:

```bash
uv run manage.py seed_demo
```

O comando imprime um resumo do que criou e do que já existia. Depois de rodar,
`/estoque/` lista os itens com categoria, preço e estoque, e `/pedidos/novo/`
já mostra os filtros por categoria com produtos para vender. Um dos itens é
semeado como inativo, de propósito, para deixar visível o caminho de item fora
do catálogo de vendas.

Alguns itens já vêm com sugestões de observação (#230): a Coca-Cola oferece
"gelo" e "rodela de limão", o Guaraná oferece "gelo" e "rodela de laranja" — a
mesma sugestão pode existir em itens diferentes, só não duas vezes no mesmo
item. Abra o item em `/estoque/` para ver e editar a lista.

Pontos importantes:

- **É seguro rodar de novo.** Tudo passa por `get_or_create` — categorias por
  nome, itens por `(nome, categoria)` e sugestões por `(item, texto)` — então
  uma segunda execução não cria duplicatas e apenas relata que tudo já existia.
- **Não sobrescreve nada.** Se você editar o preço ou o estoque de um item
  semeado, a edição permanece intacta nas execuções seguintes. O comando nunca
  apaga nem atualiza linhas existentes (não há `--flush`).
- **Reaproveita as categorias da migração 0003.** As categorias "bebidas não
  alcoólicas", "bebidas alcoólicas" e "comidas" são buscadas pelo nome, nunca
  por PK, então `/estoque/categorias/` não ganha nomes duplicados.

## Impressão térmica (cupom de cozinha) (#228)

Na tela `/pedidos/cozinha/`, cada card traz um botão **"Imprimir"** ao lado de
"Pronto". Ele faz um POST (com CSRF) para `/pedidos/<pk>/imprimir/`, que monta o
cupom de cozinha em ESC/POS e o envia à impressora térmica. A resposta é JSON:
`{"success": true, "message": ...}` quando o cupom saiu, ou HTTP 503 com
`{"success": false, "error": ...}` quando nenhuma impressora respondeu — a
mensagem aparece no rodapé do próprio card e o botão volta a ficar habilitado,
nunca uma falha silenciosa.

Imprimir é uma ação **somente leitura** sobre o pedido: o status não muda, então
reimprimir um cupom perdido não tira o card da tela da cozinha.

O botão continua funcionando nos cards que chegam pelo polling porque a tela tem
**um único listener delegado** em `#kitchen-queue` (o container que nunca é
substituído), e não um listener por botão.

### Variáveis de ambiente

| Variável | Padrão | Para que serve |
|----------|--------|----------------|
| `KARAOKE_PRINTER_NAME` | *(vazio)* | Nome da fila no CUPS (Linux) ou da impressora no Windows. Quando definido, é tentado antes da lista de nomes comuns. |
| `KARAOKE_PRINTER_DEVICE` | *(vazio)* | Caminho direto do device (ex.: `/dev/usb/lp0` no Linux, `COM3` no Windows). É a rota mais confiável e tem prioridade sobre todas as outras. |
| `KARAOKE_PRINTER_DRY_RUN` | *(desligado)* | Com `1`, `true` ou `yes`, não tenta impressora nenhuma: grava o cupom em arquivo. É o modo de desenvolvimento/QA. |
| `KARAOKE_PRINTER_DUMP_DIR` | `receipts_out/` na raiz do projeto | Onde os cupons do modo de teste são gravados (o diretório é criado se não existir). |
| `KARAOKE_RECEIPT_WIDTH` | `48` | Largura do papel em caracteres. 48 = bobina de 80mm (Elgin i9 / Bematech). |
| `KARAOKE_RECEIPT_LEFT_MARGIN` | `2` | Espaços à esquerda de cada linha, para o texto não nascer colado na borda do papel. |

### Testando sem impressora

```bash
KARAOKE_PRINTER_DRY_RUN=1 uv run manage.py runserver
```

Abra `/pedidos/cozinha/`, clique em "Imprimir" num card e o cupom é gravado em
`receipts_out/` em dois arquivos:

- `pedido-<pk>-cozinha.bin` – o fluxo ESC/POS cru, exatamente o que iria para a
  impressora;
- `pedido-<pk>-cozinha.txt` – a mesma coisa legível, sem os comandos de
  controle. É o arquivo para conferir o conteúdo:

```
Comanda Joao & Familia
** COZINHA **
  ==============================================
PEDIDO #1
  ==============================================
  Mesa: Mesa 7
  Hora: 12/09/2026 00:38
  ----------------------------------------------
  PREPARAR
  ----------------------------------------------
  3x Caipirinha de limao
  2x Porcao de batata frita com cheddar e bacon
  ----------------------------------------------
  Total de itens:                              2
  Total de unidades:                           5
```

As linhas do cabeçalho sem margem são as que a **impressora** centraliza; o
`.txt` mostra os caracteres como saem do compositor, sem simular a centralização.

`receipts_out/` está no `.gitignore`.

## Conta de administrador

Por enquanto há um único tipo de usuário — o administrador — criado via
`createsuperuser`. Não há tela de cadastro, recuperação de senha ou gestão de
usuários; papéis e permissões por usuário ficam fora do escopo deste estágio.

```bash
uv run manage.py createsuperuser
```

Informe nome de usuário, e-mail (opcional) e senha quando solicitado. Esse
usuário é o que consegue entrar pela landing page em `/` e chegar à página
inicial autenticada em `/home/`.

## Desenvolvendo o estilo

Para recompilar o CSS automaticamente ao editar o Sass:

```bash
npm run watch:css
```

### Tema escuro "tech" (#203)

A interface usa um tema escuro de cantos retos: `templates/base.html` define
`data-bs-theme="dark"` no `<html>` e `static/scss/main.scss` ajusta a paleta
escura do Bootstrap antes do `@import`. As decisões que definem o visual:

- `$enable-rounded: false` (mais `$border-radius*: 0`) — **nenhum** canto
  arredondado em botões, cards, inputs, badges ou alertas.
- `$enable-shadows: false` — superfícies planas separadas por bordas de 1px;
  os templates usam `border` no lugar de `shadow-sm`.
- Paleta: fundo `#0a0a0f`, cards `#121218`, inputs `#17171f`, bordas `#2a2a33`.
- Acento roxo `#7c3aed` (identidade original clareada para fundo escuro).
- Rótulos de formulário, legendas e cabeçalhos de tabela em caixa alta,
  pequenos e espaçados ("spec sheet").

As classes Bootstrap dos widgets ficam em `orders/forms.py` e
`inventory/forms.py` (`form-select`, `form-control`, `form-check-input`),
não nos templates, para que cada linha renderizada carregue o próprio
estilo. Em `/pedidos/novo/` não existe botão "Adicionar linha" no caminho
sem JavaScript — ele dependeria justamente do JavaScript que pode estar
desligado; o formset já vem com cinco linhas em branco (`extra=5`) e, com o
JavaScript ligado, o assistente escreve as linhas que quiser no passo 2.

O tema foi estendido às demais páginas em #204, reaproveitando os utilitários
de `main.scss` (`.karaoke-page-header`, `.karaoke-actions`, `.karaoke-micro`,
`.karaoke-chip*`, `.karaoke-btn-ghost`):

- `/` (landing) — um único card plano com a marca, rótulos em caixa alta e
  botão "Entrar" de largura total.
- `/home/` — grade de cards de navegação (`.karaoke-nav-card`) para Estoque,
  Mesas, Comandas, Novo pedido e Cozinha; o logout é um botão outline no
  cabeçalho.
- `/comandas/` — mesma tabela escura, com chips de status, marcador
  "— sem mesa" para comandas sem mesa e o filtro Abertas/Fechadas no
  cabeçalho. A tela não introduziu CSS novo: reaproveita
  `.karaoke-page-header`, `.karaoke-table`, `.karaoke-chip*`,
  `.karaoke-row-actions-split`, `.karaoke-row-inactive` e
  `.karaoke-btn-ghost`.
- `/mesas/` — mesma tabela escura de `/estoque/`, com badges quadrados e
  ações de largura uniforme (`.karaoke-row-actions-split`, necessário porque
  o toggle de status é um `<form>` e "Editar" um link).
- `/pedidos/cozinha/` — comandas planas com uma borda-acento grossa à
  esquerda no lugar do cabeçalho roxo preenchido, e botão "Pronto" grande e
  quadrado. A borda e o tempo decorrido **escalam com a idade da comanda**:
  acento até 15 min, âmbar (`.kitchen-card-late`) acima de 15, vermelho
  (`.kitchen-card-overdue`) acima de 30. O cálculo vive no filtro
  `orders/templatetags/kitchen_tags.py` (`minutes_since`) e não na view, para
  que o endpoint de polling receba a escalada de graça. O rodapé do card
  (`.kitchen-card-actions`) põe "Pronto" e "Imprimir" na mesma linha: "Pronto"
  segue primário e ocupando a largura que tinha, "Imprimir"
  (`.kitchen-btn-print`) é outline quadrado e maiúsculo para não ser apertado
  por reflexo. Abaixo dos dois, `.kitchen-print-notice` mostra o resultado da
  impressão sem modal nenhum. Em telas abaixo de 400px os dois botões
  empilham, para nenhum ficar estreito demais para o toque.
- Formulários de item/mesa e a confirmação de exclusão — card plano, rótulos
  em caixa alta e barra de ações alinhada à direita (`Cancelar` outline,
  ação destrutiva em `btn-danger`).
- `/estoque/categorias/` (#223) — reaproveita a mesma marcação de
  `/estoque/`: cabeçalho com hairline, card plano com borda, `.karaoke-table`
  e `.karaoke-row-actions`. Nenhuma classe nova de CSS foi necessária.
- `/pedidos/novo/` (#225, #231) — o seletor por toque, agora em três passos.
  Os alvos de toque (`.karaoke-pick` numa grade `.karaoke-pick-grid` de
  `auto-fill`) são superfícies planas com borda de 1px, no espírito de
  `.karaoke-nav-card`; a fila de categorias (`.karaoke-chip-row` +
  `.karaoke-filter-chip`) rola na horizontal em vez de quebrar em várias
  linhas; a lista de linhas (`.karaoke-summary*`) usa um stepper quadrado
  (`.karaoke-qty`) e o campo de observação (`.karaoke-note-input`, #229) cai
  numa linha inteira sob ele. O indicador de passos (`.karaoke-steps` +
  `.karaoke-step-chip`, com `.karaoke-step-num` e `.karaoke-step-label`) é uma
  trilha de três números sublinhados pelo mesmo hairline do resto do app, com
  o passo atual em roxo e os vencidos em roxo esmaecido. A barra fixa no
  rodapé do card (`.karaoke-submit-bar`, `position: sticky`) deixou de mostrar
  total e passou a ser a navegação: onde o garçom está
  (`.karaoke-wizard-status`), por que ainda não dá para avançar
  (`.karaoke-wizard-hint`) e os botões Voltar/Avançar/Registrar pedido, sempre
  sob o polegar. A recapitulação do passo 3 (`.karaoke-recap*`) é só linhas de
  definição, quantidades e a observação de cada item (`.karaoke-recap-note`),
  sem controle nenhum. Em 360px a grade cai para uma
  coluna, os rótulos dos passos somem (ficam só os números, já que a barra
  soletra o nome do passo logo abaixo) e as ações da barra dividem a linha
  inteira.

### Customizando o tema do Bootstrap

Edite as variáveis no topo de `static/scss/main.scss` (antes do
`@import "../../node_modules/bootstrap/scss/bootstrap"`) e rode
`npm run build:css`. Por exemplo, alterar:

```scss
$primary: #dc3545; /* vermelho */
```

…e recompilar muda visivelmente a cor primária (navbar, links, etc.) na
página renderizada.

## Scripts npm

| Script           | Descrição                                                       |
|------------------|-----------------------------------------------------------------|
| `npm run build:css` | Compila `static/scss/main.scss` -> `static/css/main.css`       |
| `npm run watch:css`| Observa o Sass e recompila em mudanças                          |
| `npm run build:js`  | Copia o bundle JS do Bootstrap para `static/vendor/js/`        |
| `npm run build`     | Roda `build:css` e `build:js`                                  |