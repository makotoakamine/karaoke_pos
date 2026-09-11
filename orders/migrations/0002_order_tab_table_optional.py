"""Hang orders off a tab and demote the table to optional context (#224).

Destructive on purpose: ``Order.tab`` is mandatory and there is no sensible tab
to invent for pre-#224 rows, so the two order tables are dropped and recreated
rather than back-filled. The task explicitly does not require preserving the
existing orders, and this app has no production data yet.
"""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
        ('orders', '0001_initial'),
        ('tables', '0001_initial'),
        ('tabs', '0001_initial'),
    ]

    operations = [
        # OrderItem first: it points at Order, so the child table goes before
        # the parent.
        migrations.DeleteModel(name='OrderItem'),
        migrations.DeleteModel(name='Order'),
        migrations.CreateModel(
            name='Order',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('open', 'Aberta'), ('done', 'Encerrada')], default='open', help_text='Pedidos novos começam em "aberta"; o fluxo de encerramento (#110) a move para "encerrada".', max_length=10, verbose_name='status')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='atualizado em')),
                ('tab', models.ForeignKey(help_text='Comanda à qual o pedido está vinculado.', on_delete=django.db.models.deletion.PROTECT, related_name='orders', to='tabs.tab', verbose_name='comanda')),
                ('table', models.ForeignKey(blank=True, help_text='Mesa onde entregar o pedido (opcional, apenas contexto de entrega).', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='orders', to='tables.table', verbose_name='mesa')),
            ],
            options={
                'verbose_name': 'pedido',
                'verbose_name_plural': 'pedidos',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='OrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.PositiveIntegerField(help_text='Quantidade vendida deste item no pedido (no mínimo 1).', validators=[django.core.validators.MinValueValidator(1)], verbose_name='quantidade')),
                ('unit_price', models.DecimalField(decimal_places=2, help_text='Preço unitário do item no momento do pedido (snapshot, não muda).', max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='preço unitário')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='order_lines', to='inventory.item', verbose_name='item')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='orders.order', verbose_name='pedido')),
            ],
            options={
                'verbose_name': 'item do pedido',
                'verbose_name_plural': 'itens do pedido',
                'ordering': ['item__name'],
            },
        ),
    ]
