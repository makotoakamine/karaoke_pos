"""Give each order line a kitchen prepared flag (#236).

Purely additive and safe on existing data: the column is ``NOT NULL`` with a
``False`` default, so every row already written is treated as "not yet
prepared" — the normal case for a fresh order line. The kitchen screen's
per-line toggle flips this flag; the line stays on the card, visibly struck
through, and never disappears. Printed tickets are unchanged by this
migration; the paper rendering of the flag ships in #237.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_order_item_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='is_prepared',
            field=models.BooleanField(default=False, help_text='Marcado pela cozinha quando esta linha está pronta. O card de pedidos da cozinha (#236) oferece um botão por linha para alternar este estado; a linha nunca some do card, apenas é riscada. A impressão em papel do flag virá em #237.', verbose_name='preparado'),
        ),
    ]
