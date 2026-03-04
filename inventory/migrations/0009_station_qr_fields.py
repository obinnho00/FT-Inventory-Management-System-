from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0008_station_machine_station"),
    ]

    operations = [
        migrations.AddField(
            model_name="station",
            name="qr_image_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="station",
            name="qr_payload",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="station",
            name="qr_pdf",
            field=models.FileField(blank=True, null=True, upload_to="station_qr_pdfs/"),
        ),
    ]
