from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0009_station_qr_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="station",
            name="qr_png",
            field=models.FileField(blank=True, null=True, upload_to="station_qr_images/"),
        ),
    ]
