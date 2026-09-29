import csv
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import Product, ProductVariant


class Command(BaseCommand):

    help = "Import product variants from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to the product variants CSV file"
        )

    REQUIRED_COLUMNS = [
        "product_code",
        "sku",
        "color",
        "storage",
        "attributes",
        "price",
        "stock",
        "is_active",
    ]

    @transaction.atomic
    def handle(self, *args, **options):

        csv_file = options["csv_file"]

        imported = 0
        skipped = 0
        errors = 0

        self.stdout.write("")
        self.stdout.write("================================")
        self.stdout.write("   PRODUCT VARIANT IMPORT")
        self.stdout.write("================================")

        try:

            with open(csv_file, "r", encoding="utf-8-sig", newline="") as file:

                reader = csv.DictReader(file)

                if not reader.fieldnames:
                    self.stdout.write(
                        self.style.ERROR("ERROR: CSV header not found.")
                    )
                    return

                missing_columns = [
                    column
                    for column in self.REQUIRED_COLUMNS
                    if column not in reader.fieldnames
                ]

                if missing_columns:
                    self.stdout.write(
                        self.style.ERROR(
                            "ERROR: Missing columns: "
                            + ", ".join(missing_columns)
                        )
                    )
                    return

                for row_number, row in enumerate(reader, start=2):

                    try:

                        product_code = row["product_code"].strip()
                        sku = row["sku"].strip()
                        color = row["color"].strip()
                        storage = row["storage"].strip()
                        attributes_text = row["attributes"].strip()
                        price = row["price"].strip()
                        stock = row["stock"].strip()
                        is_active = row["is_active"].strip().lower()

                        if not product_code:
                            raise ValueError("Product code is empty.")

                        if not sku:
                            raise ValueError("SKU is empty.")

                        product = Product.objects.filter(
                            product_code=product_code
                        ).first()

                        if not product:
                            raise ValueError(
                                f"Product not found: {product_code}"
                            )

                        if ProductVariant.objects.filter(
                            sku=sku
                        ).exists():
                            skipped += 1

                            self.stdout.write(
                                self.style.WARNING(
                                    f"⚠ Skipped row {row_number}: "
                                    f"SKU already exists: {sku}"
                                )
                            )

                            continue

                        try:
                            attributes = json.loads(
                                attributes_text
                            ) if attributes_text else {}

                        except json.JSONDecodeError:
                            raise ValueError(
                                "Invalid JSON in attributes."
                            )

                        if is_active in ("true", "1", "yes"):
                            active_value = True

                        elif is_active in ("false", "0", "no"):
                            active_value = False

                        else:
                            raise ValueError(
                                "is_active must be True or False."
                            )

                        variant = ProductVariant.objects.create(
                            product=product,
                            sku=sku,
                            color=color,
                            storage=storage,
                            attributes=attributes,
                            price=price,
                            stock=int(stock),
                            is_active=active_value,
                        )

                        imported += 1

                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✓ Imported variant: "
                                f"{product_code} → {variant.sku}"
                            )
                        )

                    except Exception as e:

                        errors += 1

                        self.stdout.write(
                            self.style.ERROR(
                                f"✗ Row {row_number}: {e}"
                            )
                        )

        except FileNotFoundError:

            self.stdout.write(
                self.style.ERROR(
                    f"ERROR: CSV file not found: {csv_file}"
                )
            )
            return

        self.stdout.write("")
        self.stdout.write("================================")
        self.stdout.write("   VARIANT IMPORT COMPLETE")
        self.stdout.write("================================")
        self.stdout.write(f"Imported : {imported}")
        self.stdout.write(f"Skipped  : {skipped}")
        self.stdout.write(f"Errors   : {errors}")
        self.stdout.write("================================")