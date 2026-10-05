"""Seed/update the catalogue from an .xlsx menu spreadsheet (#398).

The house keeps its menu in a spreadsheet, one item per row::

    Categoria | Item | Descrição | Estoque | Preço | Cozinha? | Observações

:func:`import_items` reads the first worksheet of such a file and upserts the
catalogue from it. It is a plain function over a file object — no request, no
form — so it can be exercised directly in tests and reused from a management
command later.

Rules worth knowing before changing anything here:

* Columns are located by header name (trimmed, case-insensitive), never by
  position, so staff can reorder or add columns freely. ``Descrição`` is
  optional; ``Observações`` is internal and always ignored.
* An item is identified by ``(category, name)``, not by name alone: the menu
  sells "Nikuyasai Tamanho M" both as a donburi and on the teppan, at
  different prices.
* Names are matched case-insensitively in Python (``str.casefold``) rather
  than with ``__iexact``, because SQLite only folds ASCII and the menu is full
  of accents.
* A broken file (unreadable, or missing a required header) imports nothing and
  raises :class:`SpreadsheetImportError`. A broken *row* is skipped and
  reported; the rest of the file is still committed, in one transaction.
* Nothing is ever deleted, and ``is_active`` is only set on new items.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import unicodedata

from django.db import transaction

from .models import Category, Item

COL_CATEGORY = "categoria"
COL_NAME = "item"
COL_DESCRIPTION = "descrição"
COL_STOCK = "estoque"
COL_PRICE = "preço"
COL_KITCHEN = "cozinha?"

REQUIRED_COLUMNS = {
    COL_CATEGORY: "Categoria",
    COL_NAME: "Item",
    COL_STOCK: "Estoque",
    COL_PRICE: "Preço",
    COL_KITCHEN: "Cozinha?",
}

# Largest price that fits Item.price (max_digits=10, decimal_places=2).
MAX_PRICE = Decimal("99999999.99")
CATEGORY_NAME_MAX = Category._meta.get_field("name").max_length
ITEM_NAME_MAX = Item._meta.get_field("name").max_length


class SpreadsheetImportError(Exception):
    """The file as a whole cannot be imported; nothing was written."""


@dataclass
class SkippedRow:
    row: int
    name: str
    reason: str


@dataclass
class ImportResult:
    categories_created: int = 0
    items_created: int = 0
    items_updated: int = 0
    skipped: list = field(default_factory=list)


def _key(text: str) -> str:
    """Comparison key for names: NFC-normalised, case-folded."""
    return unicodedata.normalize("NFC", text).casefold()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _parse_price(value):
    """Return the price as a 2-place Decimal, or raise ``ValueError(reason)``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("preço ausente")
    if isinstance(value, bool):
        raise ValueError("preço inválido")
    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
    else:
        raw = str(value).strip().replace("R$", "").replace(" ", "")
        if "," in raw:
            # Brazilian notation: "1.234,50" -> "1234.50".
            raw = raw.replace(".", "").replace(",", ".")
    try:
        price = Decimal(raw)
    except InvalidOperation:
        raise ValueError("preço inválido")
    if not price.is_finite():
        raise ValueError("preço inválido")
    if price < 0:
        raise ValueError("preço negativo")
    price = price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if price > MAX_PRICE:
        raise ValueError("preço alto demais")
    return price


def _parse_stock(value) -> int:
    """Return the stock as an int (empty means 0), or raise ``ValueError``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    if isinstance(value, bool):
        raise ValueError("estoque inválido")
    if isinstance(value, int):
        stock = value
    elif isinstance(value, (float, Decimal)):
        if not value == value or not float(value).is_integer():
            raise ValueError("estoque deve ser um número inteiro")
        stock = int(value)
    else:
        try:
            stock = int(str(value).strip())
        except ValueError:
            raise ValueError("estoque deve ser um número inteiro")
    if stock < 0:
        raise ValueError("estoque negativo")
    return stock


def _read_rows(file):
    """Yield ``(row_number, {column_key: value})`` for every non-empty row.

    Raises :class:`SpreadsheetImportError` if the workbook cannot be opened or
    the header row lacks a required column.
    """
    # Imported lazily so the rest of the inventory app does not pay for it.
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(file, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
    except Exception:
        # openpyxl surfaces a corrupt or non-xlsx upload as any of a handful
        # of zip/XML/KeyError exceptions; to staff they all mean the same.
        raise SpreadsheetImportError(
            "Não foi possível ler o arquivo. Envie uma planilha Excel no formato .xlsx."
        )

    if not rows:
        raise SpreadsheetImportError("A planilha está vazia.")

    columns = {}
    for index, header in enumerate(rows[0]):
        key = _key(_text(header))
        if key and key not in columns:
            columns[key] = index

    missing = [label for key, label in REQUIRED_COLUMNS.items() if key not in columns]
    if missing:
        raise SpreadsheetImportError(
            "A planilha não tem a(s) coluna(s) obrigatória(s): "
            + ", ".join(missing)
            + ". A primeira linha deve conter os cabeçalhos "
            "Categoria, Item, Estoque, Preço e Cozinha?."
        )

    for number, values in enumerate(rows[1:], start=2):
        if all(_text(v) == "" for v in values):
            continue
        yield number, {
            key: values[index] if index < len(values) else None
            for key, index in columns.items()
        }


def import_items(file) -> ImportResult:
    """Import the catalogue from an .xlsx file object; see the module docstring."""
    rows = list(_read_rows(file))
    result = ImportResult()

    with transaction.atomic():
        categories = {_key(c.name): c for c in Category.objects.all()}
        items = {
            (item.category_id, _key(item.name)): item for item in Item.objects.all()
        }

        for number, row in rows:
            category_name = _text(row.get(COL_CATEGORY))
            name = _text(row.get(COL_NAME))

            def skip(reason):
                result.skipped.append(SkippedRow(row=number, name=name, reason=reason))

            if not category_name:
                skip("categoria ausente")
                continue
            if len(category_name) > CATEGORY_NAME_MAX:
                skip(f"nome da categoria passa de {CATEGORY_NAME_MAX} caracteres")
                continue
            if not name:
                skip("nome do item ausente")
                continue
            if len(name) > ITEM_NAME_MAX:
                skip(f"nome do item passa de {ITEM_NAME_MAX} caracteres")
                continue
            try:
                price = _parse_price(row.get(COL_PRICE))
                stock = _parse_stock(row.get(COL_STOCK))
            except ValueError as exc:
                skip(str(exc))
                continue

            description = _text(row.get(COL_DESCRIPTION))
            requires_kitchen = _key(_text(row.get(COL_KITCHEN))) == "s"

            category = categories.get(_key(category_name))
            if category is None:
                category = Category.objects.create(name=category_name)
                categories[_key(category_name)] = category
                result.categories_created += 1

            item = items.get((category.pk, _key(name)))
            if item is None:
                item = Item.objects.create(
                    name=name,
                    category=category,
                    price=price,
                    stock=stock,
                    description=description,
                    requires_kitchen_preparation=requires_kitchen,
                    is_active=True,
                )
                items[(category.pk, _key(name))] = item
                result.items_created += 1
            else:
                item.price = price
                item.stock = stock
                item.description = description
                item.requires_kitchen_preparation = requires_kitchen
                item.save(
                    update_fields=[
                        "price",
                        "stock",
                        "description",
                        "requires_kitchen_preparation",
                        "updated_at",
                    ]
                )
                result.items_updated += 1

    return result
