from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0014_inventoryreminder"),
    ]

    operations = [
        migrations.AddField(
            model_name="departmentauthorizeduser",
            name="email_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="departmentauthorizeduser",
            name="email_verification_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="departmentauthorizeduser",
            name="email_verification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="departmentauthorizeduser",
            name="email_verification_token",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
    ]
