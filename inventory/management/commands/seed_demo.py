"""Populate a fresh database with a small pt-BR demo catalogue (#227).

The point is to let someone clone the repo, migrate and immediately have
something to show on ``/estoque/`` and ``/pedidos/`` without typing rows by
hand. It is deliberately *additive*: the command only ever calls
``get_or_create``, so re-running it is safe and any price or stock a user
edited by hand survives untouched. There is no ``--flush`` and nothing is
updated — destroying data a user curated is never worth the convenience.

The three categories come from the data migration
``0003_seed_starter_categories`` and are looked up by name, never by PK, so a
database where those rows were recreated (or the migration reversed) still
lands on a single category per name.

Some drinks also carry a couple of note suggestions (#230) so the chip list on
the add-item dialog has real data to show. They are seeded with the same
``get_or_create`` rule as everything else: a chip a user renamed stays renamed,
and re-running never duplicates one.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Category, Item, NoteSuggestion

# Category names as seeded by inventory/migrations/0003_seed_starter_categories.py.
NAO_ALCOOLICAS = "bebidas não alcoólicas"
ALCOOLICAS = "bebidas alcoólicas"
COMIDAS = "comidas"

# The demo catalogue, kept inline on purpose: one module-level list is easier to
# eyeball and diff than an external fixture, and it keeps the command free of
# any file/loader dependency. Prices are BRL with two decimal places.
DEMO_ITEMS = [
    # bebidas não alcoólicas
    {
        "name": "Refrigerante lata 350ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("7.00"),
        "stock": 96,
    },
    # The two canonical chip examples from #230: same "gelo" suggestion on both
    # items (allowed — uniqueness is per item), different citrus each.
    {
        "name": "Coca-Cola lata 350ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("8.00"),
        "stock": 72,
        "note_suggestions": ["gelo", "rodela de limão"],
    },
    {
        "name": "Guaraná lata 350ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("8.00"),
        "stock": 66,
        "note_suggestions": ["gelo", "rodela de laranja"],
    },
    {
        "name": "Água mineral 500ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("5.00"),
        "stock": 84,
    },
    {
        "name": "Suco de laranja natural 300ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("12.00"),
        "stock": 32,
    },
    {
        "name": "Energético lata 250ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("15.00"),
        "stock": 48,
    },
    {
        "name": "Água de coco 300ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("9.00"),
        "stock": 24,
    },
    # Out of season: seeded inactive so the inactive-item path is visible on
    # /estoque/ and the drink stays off the order page.
    {
        "name": "Suco de abacaxi com hortelã 300ml",
        "category": NAO_ALCOOLICAS,
        "price": Decimal("14.00"),
        "stock": 10,
        "is_active": False,
    },
    # bebidas alcoólicas
    {
        "name": "Cerveja long neck 355ml",
        "category": ALCOOLICAS,
        "price": Decimal("12.00"),
        "stock": 100,
    },
    {
        "name": "Chopp 300ml",
        "category": ALCOOLICAS,
        "price": Decimal("10.00"),
        "stock": 72,
    },
    {
        "name": "Caipirinha de limão",
        "category": ALCOOLICAS,
        "price": Decimal("18.00"),
        "stock": 45,
        "note_suggestions": ["sem açúcar", "com vodka"],
    },
    {
        "name": "Gin tônica",
        "category": ALCOOLICAS,
        "price": Decimal("26.00"),
        "stock": 38,
    },
    {
        "name": "Dose de whisky",
        "category": ALCOOLICAS,
        "price": Decimal("22.00"),
        "stock": 30,
    },
    {
        "name": "Dose de vodka",
        "category": ALCOOLICAS,
        "price": Decimal("16.00"),
        "stock": 34,
    },
    # comidas
    {
        "name": "Porção de batata frita",
        "category": COMIDAS,
        "price": Decimal("32.00"),
        "stock": 26,
        "note_suggestions": ["sem sal", "bem passada", "com cheddar"],
    },
    {
        "name": "Isca de frango",
        "category": COMIDAS,
        "price": Decimal("38.00"),
        "stock": 22,
    },
    {
        "name": "Calabresa acebolada",
        "category": COMIDAS,
        "price": Decimal("35.00"),
        "stock": 20,
    },
    {
        "name": "Pastel de queijo",
        "category": COMIDAS,
        "price": Decimal("14.00"),
        "stock": 40,
    },
    {
        "name": "Amendoim torrado",
        "category": COMIDAS,
        "price": Decimal("10.00"),
        "stock": 60,
    },
]


class Command(BaseCommand):
    help = (
        "Popula o banco com um catálogo de demonstração (categorias iniciais + "
        "itens em pt-BR). Pode ser rodado várias vezes: nada é duplicado nem "
        "sobrescrito."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        categories, categories_created = self._seed_categories()
        items_created, items_existing = self._seed_items(categories)
        suggestions_created = self._seed_note_suggestions()

        self.stdout.write("")
        if categories_created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Categorias criadas: {categories_created} "
                    f"(de {len(categories)})."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Categorias: as {len(categories)} já existiam, nenhuma criada."
                )
            )

        if items_created:
            self.stdout.write(
                self.style.SUCCESS(f"Itens criados: {items_created}.")
            )
        if items_existing:
            self.stdout.write(
                self.style.WARNING(
                    f"Itens que já existiam (mantidos como estão): {items_existing}."
                )
            )

        if suggestions_created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sugestões de observação criadas: {suggestions_created}."
                )
            )

        if not items_created and not categories_created and not suggestions_created:
            self.stdout.write(
                self.style.WARNING("Nada a fazer: o catálogo de demonstração já estava completo.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Catálogo de demonstração pronto. Veja /estoque/.")
            )

    def _seed_categories(self):
        """Return ``{name: Category}`` for the demo buckets, plus a created count.

        Looked up by name so the rows from migration 0003 are reused rather
        than duplicated; ``get_or_create`` only fills the gap if someone
        deleted one.
        """
        categories = {}
        created_count = 0
        for name in (NAO_ALCOOLICAS, ALCOOLICAS, COMIDAS):
            category, created = Category.objects.get_or_create(name=name)
            categories[name] = category
            if created:
                created_count += 1
                self.stdout.write(f"  + categoria \"{name}\"")
            else:
                self.stdout.write(f"  = categoria \"{name}\" (já existia)")
        return categories, created_count

    def _seed_items(self, categories):
        """Create the missing demo items; leave every existing row untouched.

        Identity is ``(name, category)``: the same drink name under a different
        bucket is a different item, and ``defaults`` means a row a user already
        edited keeps its price, stock and active flag.
        """
        created_count = 0
        existing_count = 0
        for spec in DEMO_ITEMS:
            category = categories[spec["category"]]
            item, created = Item.objects.get_or_create(
                name=spec["name"],
                category=category,
                defaults={
                    "price": spec["price"],
                    "stock": spec["stock"],
                    "is_active": spec.get("is_active", True),
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"  + item \"{item.name}\"")
            else:
                existing_count += 1
                self.stdout.write(f"  = item \"{item.name}\" (já existia)")
        return created_count, existing_count

    def _seed_note_suggestions(self):
        """Attach the demo chip lists to the items that declare one (#230).

        Runs over the items by name so a row someone created by hand before the
        first seed still gets its suggestions. ``get_or_create`` on
        ``(item, text)`` is exactly the model's unique constraint, so a second
        run creates nothing and an edited chip is left alone.
        """
        created_count = 0
        for spec in DEMO_ITEMS:
            texts = spec.get("note_suggestions")
            if not texts:
                continue
            for item in Item.objects.filter(name=spec["name"]):
                for text in texts:
                    _, created = NoteSuggestion.objects.get_or_create(
                        item=item, text=text
                    )
                    if created:
                        created_count += 1
                        self.stdout.write(
                            f"  + sugestão \"{text}\" em \"{item.name}\""
                        )
        return created_count
