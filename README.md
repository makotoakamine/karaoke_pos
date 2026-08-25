# Karaokê POS

Sistema de ponto de venda para karaokê. Projeto Django 5.x com Bootstrap 5.3
compilado localmente via Sass (nenhum recurso vem de CDN).

A interface está em português brasileiro (pt-br).

## Estrutura

- **`config/`** – módulo de configurações do Django (`config.settings.dev`).
  - `config/urls.py` – URLs raiz, inclui `core.urls` em `/`.
- **`core/`** – app inicial com a view da página inicial.
- **`templates/base.html`** – esqueleto da página: navbar superior + bloco
  `content` que toda página filha estende. Carrega o CSS compilado localmente e
  o bundle JS do Bootstrap servido localmente.
- **`templates/core/index.html`** – página inicial que estende `base.html`.
- **`static/scss/main.scss`** – ponto de entrada do Sass; sobrescreve
  variáveis do Bootstrap **antes** de importá-lo, permitindo customização do tema.
- **`static/css/main.css`** – CSS compilado (gerado, ignorado pelo git).
- **`static/vendor/js/bootstrap.bundle.min.js`** – bundle JS do Bootstrap
  (Popper incluído) servido localmente.
- **`requirements.txt`** – pin do Django.
- **`package.json`** – deps npm (Bootstrap 5.3 + Sass) e scripts de build.

## Pré-requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (gerenciador de ambientes/dependências Python da Astral)
- Node.js 20+ e npm

## Configuração do ambiente (a partir de um clone limpo)

Execute todos os comandos a partir da raiz do repositório.

```bash
# 1. Criar o ambiente virtual com uv e instalar as dependências Python
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# 2. Instalar as dependências de frontend (Bootstrap + Sass)
npm install

# 3. Compilar o CSS do Bootstrap a partir do Sass
#    (gera static/css/main.css a partir de static/scss/main.scss)
npm run build:css

# 4. Copiar o bundle JS do Bootstrap para static/ (servido localmente)
npm run build:js

# 5. Aplicar as migrações do banco de dados (SQLite)
.venv/bin/python manage.py migrate

# 6. Rodar o servidor de desenvolvimento
.venv/bin/python manage.py runserver
```

Abra <http://127.0.0.1:8000/> no navegador. A página inicial deve carregar
estilizada pelo Bootstrap compilado localmente, com a barra de navegação roxa
no topo.

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