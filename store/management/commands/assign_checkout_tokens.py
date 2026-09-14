import uuid

from django.core.management.base import BaseCommand

from store.models import Order


class Command(BaseCommand):
    help = "Assign unique checkout tokens to existing orders"

    def handle(self, *args, **options):
        orders = Order.objects.filter(
            checkout_token__isnull=True
        )

        count = 0

        for order in orders:
            order.checkout_token = uuid.uuid4()
            order.save(
                update_fields=["checkout_token"]
            )
            count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully assigned checkout tokens to {count} order(s)."
            )
        )