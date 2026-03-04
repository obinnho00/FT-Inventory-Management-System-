from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0010_station_qr_png"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkOrderRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.TextField(blank=True)),
                ("priority", models.PositiveSmallIntegerField(choices=[(1, "High"), (2, "Medium"), (3, "Low")], default=2)),
                ("status", models.CharField(choices=[("NEW", "New"), ("COMING", "Coming"), ("COMPLETED", "Completed")], default="NEW", max_length=20)),
                ("scanned_at", models.DateTimeField(auto_now_add=True)),
                ("accessed_at", models.DateTimeField(blank=True, null=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="work_orders", to="inventory.department")),
                ("machine", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_orders", to="inventory.machine")),
                ("station", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="work_orders", to="inventory.station")),
            ],
            options={
                "db_table": "inventory_work_order_request",
                "ordering": ["priority", "-scanned_at"],
            },
        ),
    ]
