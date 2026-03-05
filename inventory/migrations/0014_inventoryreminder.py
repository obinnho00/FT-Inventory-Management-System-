from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryReminder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("alert_quantity", models.PositiveIntegerField(default=1)),
                ("notify_email", models.EmailField(max_length=254)),
                (
                    "created_by_first_name",
                    models.CharField(blank=True, max_length=100),
                ),
                ("created_by_last_name", models.CharField(blank=True, max_length=100)),
                ("created_by_email", models.EmailField(blank=True, max_length=254)),
                ("is_active", models.BooleanField(default=True)),
                ("alert_sent", models.BooleanField(default=False)),
                ("last_alert_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_reminders",
                        to="inventory.department",
                    ),
                ),
                (
                    "machine_part",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_reminders",
                        to="inventory.machinepart",
                    ),
                ),
            ],
            options={
                "db_table": "inventory_inventory_reminder",
                "ordering": [
                    "department__name",
                    "machine_part__machine__name",
                    "machine_part__part__model_number",
                ],
                "unique_together": {("department", "machine_part", "notify_email")},
            },
        ),
    ]
