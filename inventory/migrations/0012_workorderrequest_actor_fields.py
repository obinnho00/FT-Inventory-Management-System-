from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0011_workorderrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorderrequest",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="completed_by_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="completed_by_first_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="completed_by_last_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="requested_by_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="requested_by_first_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="requested_by_last_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="technician_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="technician_first_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="workorderrequest",
            name="technician_last_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="workorderrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("NEW", "New"),
                    ("COMING", "Coming"),
                    ("COMPLETED", "Completed"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="NEW",
                max_length=20,
            ),
        ),
    ]
