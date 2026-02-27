import os
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage

from inventory.models import Part


class Command(BaseCommand):
    help = "Migrate existing local Part images to Cloudinary storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional max number of parts to migrate.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-upload even if the file already appears to be Cloudinary-hosted.",
        )

    def handle(self, *args, **options):
        if not os.environ.get("CLOUDINARY_URL"):
            self.stdout.write(self.style.ERROR("CLOUDINARY_URL is not set. Configure it first, then run again."))
            return

        storage_name = default_storage.__class__.__name__
        if "Cloudinary" not in storage_name:
            self.stdout.write(
                self.style.WARNING(
                    f"Current default storage is {storage_name}, not Cloudinary. "
                    "Deploy with CLOUDINARY_URL so this command runs under MediaCloudinaryStorage."
                )
            )
            return

        parts = Part.objects.exclude(image="").exclude(image__isnull=True).order_by("id")

        limit = options["limit"]
        if limit and limit > 0:
            parts = parts[:limit]

        migrated = 0
        skipped = 0
        failed = 0

        media_root = Path(getattr(settings, "MEDIA_ROOT", ""))

        for part in parts:
            current_name = str(part.image.name or "")
            lower_name = current_name.lower()

            if not options["force"] and (
                lower_name.startswith("http://res.cloudinary.com")
                or lower_name.startswith("https://res.cloudinary.com")
            ):
                skipped += 1
                continue

            local_file_path = media_root / current_name
            if not local_file_path.exists():
                self.stdout.write(self.style.WARNING(f"Missing local file for {part.model_number}: {current_name}"))
                failed += 1
                continue

            try:
                filename = local_file_path.name
                with local_file_path.open("rb") as file_handle:
                    part.image.save(filename, File(file_handle), save=True)
                migrated += 1
                self.stdout.write(self.style.SUCCESS(f"Migrated: {part.model_number} -> {part.image.name}"))
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"Failed {part.model_number}: {exc}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Migrated={migrated}, Skipped={skipped}, Failed={failed}"
            )
        )
