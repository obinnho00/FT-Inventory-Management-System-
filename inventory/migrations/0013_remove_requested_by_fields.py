from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0012_workorderrequest_actor_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="workorderrequest",
            name="requested_by_email",
        ),
        migrations.RemoveField(
            model_name="workorderrequest",
            name="requested_by_first_name",
        ),
        migrations.RemoveField(
            model_name="workorderrequest",
            name="requested_by_last_name",
        ),
    ]
