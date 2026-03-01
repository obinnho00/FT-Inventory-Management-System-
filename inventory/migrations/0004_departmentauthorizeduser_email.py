from django.db import migrations, models


def set_placeholder_emails(apps, schema_editor):
    DepartmentAuthorizedUser = apps.get_model("inventory", "DepartmentAuthorizedUser")
    for row in DepartmentAuthorizedUser.objects.filter(email__isnull=True):
        row.email = f"user-{row.pk}@pending.local"
        row.save(update_fields=["email"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_departmentauthorizeduser"),
    ]

    operations = [
        migrations.AddField(
            model_name="departmentauthorizeduser",
            name="email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.RunPython(set_placeholder_emails, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="departmentauthorizeduser",
            name="email",
            field=models.EmailField(max_length=254),
        ),
        migrations.AlterModelOptions(
            name="departmentauthorizeduser",
            options={"db_table": "inventory_department_authorized_user", "ordering": ["department__name", "first_name", "last_name", "email"]},
        ),
        migrations.AlterUniqueTogether(
            name="departmentauthorizeduser",
            unique_together={("department", "email")},
        ),
    ]
