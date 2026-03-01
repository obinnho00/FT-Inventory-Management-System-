from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_departmentauthorizeduser_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="machinepart",
            name="last_used_quantity",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
