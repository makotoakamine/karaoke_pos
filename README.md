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
- **`inventory/`** – app de catálogo de itens vendáveis (#107).
  - `inventory/models.py` – `Item` (nome, preço, estoque, `is_active`).
  - `inventory/views.py` – CRUD de itens (login required) via class-based views.
  - `inventory/urls.py` – `/estoque/` (lista), `/estoque/novo/` (criar),
    `/estoque/<pk>/editar/` (editar) e `/estoque/<pk>/excluir/` (excluir).
  - `inventory/admin.py` – registra `Item` no admin do Django como fallback.
- **`tables/`** – app de gestão de mesas (#108).
  - `tables/models.py` – `Table` (nome/número único, lugares, status
    livre/ocupada, `is_active`).
  - `tables/views.py` – lista/visão geral com toggle manual de status +
    criar/editar (login required) via class-based views.
  - `tables/urls.py` – `/mesas/` (lista), `/mesas/nova/` (criar) e
    `/mesas/<pk>/editar/` (editar).
  - `tables/admin.py` – registra `Table` no admin do Django como fallback.
- **`orders/`** – app de pedidos (#109).
  - `orders/models.py` – `Order` (FK para `tables.Table`, status
    aberta/encerrada, `created_at`) e `OrderItem` (FK para o pedido, FK para
    `inventory.Item`, `quantity`, `unit_price` com snapshot do preço no
    momento do pedido).
  - `orders/views.py` – página de abertura de pedido (login required) com
    seleção de mesa + formset de itens; o POST roda numa transação única,
    valida o estoque de cada linha contra o estoque atual, decrementa o
    estoque, cria o pedido com seus itens e marca a mesa como ocupada. Se
    qualquer linha excede o estoque, toda a submissão é rejeitada e nada
    muda. Também a tela de cozinha (login required) em `/pedidos/cozinha/`
    que lista todos os pedidos abertos, do mais antigo ao mais recente, em
    cards grandes do Bootstrap; um endpoint de polling em
    `/pedidos/cozinha/fila/` devolve só o fragmento dos cards e um pequeno
    JavaScript no template troca o conteúdo a cada ~5 segundos, sem
    websockets nem framework JS. O botão "Pronto" em cada pedido faz POST
    (com CSRF) para `/pedidos/cozinha/<pk>/pronto/` e muda o status para
    "encerrada"; pedidos encerrados nunca aparecem na tela. A ocupação das
    mesas não é tocada aqui.
  - `orders/urls.py` – `/pedidos/novo/` (abrir pedido), `/pedidos/cozinha/`
    (tela de cozinha), `/pedidos/cozinha/fila/` (polling dos cards) e
    `/pedidos/cozinha/<pk>/pronto/` (marcar pedido como pronto).
  - `orders/admin.py` – registra `Order` e `OrderItem` no admin do Django
    como fallback.
- **`templates/base.html`** – esqueleto da página: navbar superior + bloco
  `content` que toda página filha estende. Carrega o CSS compilado localmente e
  o bundle JS do Bootstrap servido localmente. A navbar mostra "Entrar" para
  visitantes deslogados e "Início/Mesas/Pedidos/Cozinha/Estoque/Sair" para
  autenticados.
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
não nos templates: a linha extra criada pelo botão "Adicionar item" em
`/pedidos/novo/` é um clone do HTML já renderizado, então o estilo precisa
vir do próprio widget.

O tema foi estendido às demais páginas em #204, reaproveitando os utilitários
de `main.scss` (`.karaoke-page-header`, `.karaoke-actions`, `.karaoke-micro`,
`.karaoke-chip*`, `.karaoke-btn-ghost`):

- `/` (landing) — um único card plano com a marca, rótulos em caixa alta e
  botão "Entrar" de largura total.
- `/home/` — grade de cards de navegação (`.karaoke-nav-card`) para Estoque,
  Mesas, Novo pedido e Cozinha; o logout é um botão outline no cabeçalho.
- `/mesas/` — mesma tabela escura de `/estoque/`, com badges quadrados e
  ações de largura uniforme (`.karaoke-row-actions-split`, necessário porque
  o toggle de status é um `<form>` e "Editar" um link).
- `/pedidos/cozinha/` — comandas planas com uma borda-acento grossa à
  esquerda no lugar do cabeçalho roxo preenchido, e botão "Pronto" grande e
  quadrado. A borda e o tempo decorrido **escalam com a idade da comanda**:
  acento até 15 min, âmbar (`.kitchen-card-late`) acima de 15, vermelho
  (`.kitchen-card-overdue`) acima de 30. O cálculo vive no filtro
  `orders/templatetags/kitchen_tags.py` (`minutes_since`) e não na view, para
  que o endpoint de polling receba a escalada de graça.
- Formulários de item/mesa e a confirmação de exclusão — card plano, rótulos
  em caixa alta e barra de ações alinhada à direita (`Cancelar` outline,
  ação destrutiva em `btn-danger`).

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