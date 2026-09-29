import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import Product, ProductSpecification


class Command(BaseCommand):

    help = "Import product specifications from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to the product specifications CSV file"
        )

    REQUIRED_COLUMNS = [
        "product_code",
        "name",
        "value",
        "sort_order",
    ]

    @transaction.atomic
    def handle(self, *args, **options):

        csv_file = options["csv_file"]

        imported = 0
        skipped = 0
        errors = 0

        self.stdout.write("")
        self.stdout.write("================================")
        self.stdout.write("   PRODUCT SPECIFICATION IMPORT")
        self.stdout.write("================================")

        try:

            with open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as file:

                reader = csv.DictReader(file)

                if not reader.fieldnames:
                    self.stdout.write(
                        self.style.ERROR(
                            "ERROR: CSV header not found."
                        )
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
                        name = row["name"].strip()
                        value = row["value"].strip()
                        sort_order = row["sort_order"].strip()

                        if not product_code:
                            raise ValueError(
                                "Product code is empty."
                            )

                        if not name:
                            raise ValueError(
                                "Specification name is empty."
                            )

                        if not value:
                            raise ValueError(
                                "Specification value is empty."
                            )

                        product = Product.objects.filter(
                            product_code=product_code
                        ).first()

                        if not product:
                            raise ValueError(
                                f"Product not found: {product_code}"
                            )

                        try:
                            sort_order_value = int(sort_order)
                        except ValueError:
                            raise ValueError(
                                "sort_order must be a number."
                            )

                        if sort_order_value < 0:
                            raise ValueError(
                                "sort_order cannot be negative."
                            )

                        if ProductSpecification.objects.filter(
                            product=product,
                            name=name,
                            value=value
                        ).exists():

                            skipped += 1

                            self.stdout.write(
                                self.style.WARNING(
                                    f"⚠ Skipped row {row_number}: "
                                    f"Specification already exists: "
                                    f"{product_code} → {name}"
                                )
                            )

                            continue

                        specification = ProductSpecification.objects.create(
                            product=product,
                            name=name,
                            value=value,
                            sort_order=sort_order_value,
                        )

                        imported += 1

                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✓ Imported specification: "
                                f"{product_code} → "
                                f"{specification.name}"
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
        self.stdout.write("   SPECIFICATION IMPORT COMPLETE")
        self.stdout.write("================================")
        self.stdout.write(f"Imported : {imported}")
        self.stdout.write(f"Skipped  : {skipped}")
        self.stdout.write(f"Errors   : {errors}")
        self.stdout.write("================================")