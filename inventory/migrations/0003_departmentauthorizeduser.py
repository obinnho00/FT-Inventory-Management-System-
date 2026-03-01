from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_departmentaccesscode_machinepart_last_action_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="DepartmentAuthorizedUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="authorized_users",
                        to="inventory.department",
                    ),
                ),
            ],
            options={
                "db_table": "inventory_department_authorized_user",
                "ordering": ["department__name", "first_name", "last_name"],
                "unique_together": {("department", "first_name", "last_name")},
            },
        ),
    ]
