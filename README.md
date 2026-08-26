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
  variáveis do Bootstrap **antes** de importá-lo, permitindo customização do tema.
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
carregar estilizada pelo Bootstrap compilado localmente, com a barra de
navegação roxa no topo e o formulário de acesso centralizado.

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