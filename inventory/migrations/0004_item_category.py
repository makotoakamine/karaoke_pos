"""Attach every item to a category (#223).

The category is required — there is no uncategorised bucket — so the column is
added NOT NULL. We are still in development: a fresh clone has no items at all
when this runs, and a developer database picks up the first starter category
seeded by 0003 immediately before. No backfill machinery beyond that.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_seed_starter_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="category",
            field=models.ForeignKey(
                default=1,
                help_text="Categoria do item no catálogo (obrigatória).",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="items",
                to="inventory.category",
                verbose_name="categoria",
            ),
            preserve_default=False,
        ),
    ]
