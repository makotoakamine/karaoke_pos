"""Give each order line a free-text note for the kitchen (#229).

Purely additive and safe on existing data: the column is ``NOT NULL`` with an
empty-string default, so every row already written gets ``""`` — "this line has
no special request", which is the normal case — and no order placed before this
migration changes in any way.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_order_tab_table_optional'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='notes',
            field=models.CharField(blank=True, default='', help_text='Pedido especial do cliente para esta linha ("com gelo e limão").', max_length=200, verbose_name='observações'),
        ),
    ]
