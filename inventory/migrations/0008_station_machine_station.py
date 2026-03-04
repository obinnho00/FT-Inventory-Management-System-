from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0007_adminsetupkey"),
    ]

    operations = [
        migrations.CreateModel(
            name="Station",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stations",
                        to="inventory.department",
                    ),
                ),
            ],
            options={
                "db_table": "inventory_station",
                "ordering": ["department__name", "name"],
                "unique_together": {("department", "name")},
            },
        ),
        migrations.AddField(
            model_name="machine",
            name="station",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="machines",
                to="inventory.station",
            ),
        ),
    ]
