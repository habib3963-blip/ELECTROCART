import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import Product, ProductImage


class Command(BaseCommand):
    help = "Import product images from a CSV file"

    REQUIRED_COLUMNS = {
        "product_code",
        "image_url",
        "alt_text",
        "is_primary",
        "sort_order",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to the product images CSV file",
        )

    def handle(self, *args, **options):

        csv_file = options["csv_file"]

        imported = 0
        skipped = 0
        errors = 0

        try:
            file = open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline="",
            )

        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(
                    f"CSV file not found: {csv_file}"
                )
            )
            return

        with file:

            reader = csv.DictReader(file)

            if not reader.fieldnames:
                self.stdout.write(
                    self.style.ERROR(
                        "CSV file is empty."
                    )
                )
                return

            columns = {
                column.strip()
                for column in reader.fieldnames
                if column
            }

            missing_columns = (
                self.REQUIRED_COLUMNS - columns
            )

            if missing_columns:
                self.stdout.write(
                    self.style.ERROR(
                        "Missing CSV columns: "
                        + ", ".join(
                            sorted(missing_columns)
                        )
                    )
                )
                return

            for row_number, row in enumerate(
                reader,
                start=2,
            ):

                try:
                    product_code = (
                        row.get("product_code", "")
                        .strip()
                    )

                    image_url = (
                        row.get("image_url", "")
                        .strip()
                    )

                    alt_text = (
                        row.get("alt_text", "")
                        .strip()
                    )

                    is_primary_value = (
                        row.get("is_primary", "")
                        .strip()
                        .lower()
                    )

                    sort_order_value = (
                        row.get("sort_order", "")
                        .strip()
                    )

                    # -----------------------------------------
                    # VALIDATION
                    # -----------------------------------------

                    if not product_code:
                        raise ValueError(
                            "product_code is required"
                        )

                    if not image_url:
                        raise ValueError(
                            "image_url is required"
                        )

                    # -----------------------------------------
                    # FIND PRODUCT
                    # -----------------------------------------

                    product = Product.objects.filter(
                        product_code=product_code
                    ).first()

                    if not product:
                        raise ValueError(
                            f"Product not found: "
                            f"{product_code}"
                        )

                    # -----------------------------------------
                    # PRIMARY STATUS
                    # -----------------------------------------

                    if is_primary_value in {
                        "true",
                        "1",
                        "yes",
                    }:
                        is_primary = True

                    elif is_primary_value in {
                        "false",
                        "0",
                        "no",
                    }:
                        is_primary = False

                    else:
                        raise ValueError(
                            "is_primary must be "
                            "True or False"
                        )

                    # -----------------------------------------
                    # SORT ORDER
                    # -----------------------------------------

                    try:
                        sort_order = int(
                            sort_order_value
                        )
                    except ValueError:
                        raise ValueError(
                            f"Invalid sort_order: "
                            f"{sort_order_value}"
                        )

                    if sort_order < 0:
                        raise ValueError(
                            "sort_order cannot be negative"
                        )

                    # -----------------------------------------
                    # DUPLICATE CHECK
                    # -----------------------------------------

                    already_exists = (
                        ProductImage.objects.filter(
                            product=product,
                            image_url=image_url,
                        ).exists()
                    )

                    if already_exists:
                        skipped += 1

                        self.stdout.write(
                            self.style.WARNING(
                                f"↷ Skipped duplicate: "
                                f"{product_code}"
                            )
                        )

                        continue

                    # -----------------------------------------
                    # CREATE IMAGE
                    # -----------------------------------------

                    with transaction.atomic():

                        # If this image is primary,
                        # remove primary status from
                        # other images of this product.
                        if is_primary:
                            ProductImage.objects.filter(
                                product=product,
                                is_primary=True,
                            ).update(
                                is_primary=False
                            )

                        ProductImage.objects.create(
                            product=product,
                            image_url=image_url,
                            alt_text=alt_text,
                            is_primary=is_primary,
                            sort_order=sort_order,
                        )

                    imported += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ Imported image: "
                            f"{product_code} "
                            f"(order {sort_order})"
                        )
                    )

                except Exception as e:

                    errors += 1

                    self.stdout.write(
                        self.style.ERROR(
                            f"✗ Row {row_number}: {e}"
                        )
                    )

        # ---------------------------------------------
        # FINAL REPORT
        # ---------------------------------------------

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "================================"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "   IMAGE IMPORT COMPLETE"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "================================"
            )
        )

        self.stdout.write(
            f"Imported : {imported}"
        )

        self.stdout.write(
            f"Skipped  : {skipped}"
        )

        self.stdout.write(
            f"Errors   : {errors}"
        )

        self.stdout.write(
            self.style.SUCCESS(
                "================================"
            )
        )