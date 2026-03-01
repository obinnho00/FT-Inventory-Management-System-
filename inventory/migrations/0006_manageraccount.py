from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0005_machinepart_last_used_quantity"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagerAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(max_length=100)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("access_code_hash", models.CharField(max_length=128)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("departments", models.ManyToManyField(blank=True, related_name="manager_accounts", to="inventory.department")),
            ],
            options={
                "db_table": "inventory_manager_account",
                "ordering": ["first_name", "last_name", "email"],
            },
        ),
    ]
