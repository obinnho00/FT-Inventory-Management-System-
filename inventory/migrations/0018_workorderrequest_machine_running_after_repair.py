from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0017_workorderrequest_downtime_started_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorderrequest",
            name="machine_running_after_repair",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
