from django.core.management.base import BaseCommand

from inventory.views import _process_pending_inventory_reminders


class Command(BaseCommand):
    help = "Process pending inventory reminder emails that reached threshold and were not sent yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--department-id",
            type=int,
            action="append",
            dest="department_ids",
            help="Optional department id filter. Can be provided multiple times.",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="",
            help="Optional reminder recipient email filter.",
        )

    def handle(self, *args, **options):
        department_ids = options.get("department_ids") or None
        notify_email = (options.get("email") or "").strip()

        _process_pending_inventory_reminders(
            department_ids=department_ids,
            notify_email=notify_email,
        )

        self.stdout.write(self.style.SUCCESS("Pending reminder email processing completed."))
