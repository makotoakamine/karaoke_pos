"""Seed the starter categories so a fresh clone is usable straight away (#223).

Only the three buckets the house actually sells today. Staff can rename, add
to or delete them from ``/estoque/categorias/``; this migration just makes
sure the item form has something to pick from on the first run.
"""
from django.db import migrations

STARTER_CATEGORIES = [
    "bebidas não alcoólicas",
    "bebidas alcoólicas",
    "comidas",
]


def create_starter_categories(apps, schema_editor):
    Category = apps.get_model("inventory", "Category")
    for name in STARTER_CATEGORIES:
        Category.objects.get_or_create(name=name)


def delete_starter_categories(apps, schema_editor):
    """Drop the starter rows again.

    Safe to run unconditionally: reversing this migration is only reachable
    after 0004 has already removed ``Item.category``, so nothing points here.
    """
    Category = apps.get_model("inventory", "Category")
    Category.objects.filter(name__in=STARTER_CATEGORIES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_category"),
    ]

    operations = [
        migrations.RunPython(create_starter_categories, delete_starter_categories),
    ]
