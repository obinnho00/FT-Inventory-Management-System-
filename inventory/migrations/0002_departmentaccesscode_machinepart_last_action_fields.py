from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DepartmentAccessCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=50)),
                (
                    "department",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="access_code",
                        to="inventory.department",
                    ),
                ),
            ],
            options={
                "db_table": "inventory_department_access_code",
            },
        ),
        migrations.AddField(
            model_name="machinepart",
            name="last_action_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="machinepart",
            name="last_action_by_first_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="machinepart",
            name="last_action_by_last_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="machinepart",
            name="last_action_type",
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
