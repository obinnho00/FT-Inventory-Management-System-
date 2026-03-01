from django.core.management.base import BaseCommand, CommandError

from inventory.models import AdminSetupKey


class Command(BaseCommand):
    help = "Create or update the DB-backed admin setup key used by the Admin Manager Setup page."

    def add_arguments(self, parser):
        parser.add_argument(
            "--key",
            type=str,
            help="Admin setup key value to store (required in non-interactive usage).",
        )

    def handle(self, *args, **options):
        key_value = (options.get("key") or "").strip()

        if not key_value:
            key_value = input("Enter new admin setup key: ").strip()

        if not key_value:
            raise CommandError("Admin setup key cannot be empty.")

        if len(key_value) < 6:
            raise CommandError("Admin setup key must be at least 6 characters.")

        admin_key = AdminSetupKey.objects.filter(is_active=True).order_by("-updated_at").first()

        if admin_key:
            admin_key.set_key(key_value)
            admin_key.save(update_fields=["key_hash", "updated_at"])
            self.stdout.write(self.style.SUCCESS("Admin setup key updated in DB."))
        else:
            admin_key = AdminSetupKey(is_active=True)
            admin_key.set_key(key_value)
            admin_key.save()
            self.stdout.write(self.style.SUCCESS("Admin setup key created in DB."))
