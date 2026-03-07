from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0016_manageraccount_email_verification"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorderrequest",
            name="downtime_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
