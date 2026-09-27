import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from store.models import Product, Brand, Category


class Command(BaseCommand):
    help = "Import products from a CSV file"

    REQUIRED_COLUMNS = {
        "product_code",
        "name",
        "brand",
        "category",
        "description",
        "mrp",
        "price",
        "stock",
        "badge",
        "is_active",
        "image",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to the CSV file",
        )

    def handle(self, *args, **options):

        csv_file = options["csv_file"]

        imported = 0
        updated = 0
        skipped = 0
        errors = 0

        try:
            file = open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline=""
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
                start=2
            ):

                try:
                    product_code = (
                        row.get("product_code", "")
                        .strip()
                    )

                    name = (
                        row.get("name", "")
                        .strip()
                    )

                    brand_name = (
                        row.get("brand", "")
                        .strip()
                    )

                    category_name = (
                        row.get("category", "")
                        .strip()
                    )

                    description = (
                        row.get("description", "")
                        .strip()
                    )

                    price_value = (
                        row.get("price", "")
                        .strip()
                    )

                    mrp_value = (
                        row.get("mrp", "")
                        .strip()
                    )

                    stock_value = (
                        row.get("stock", "")
                        .strip()
                    )

                    badge = (
                        row.get("badge", "")
                        .strip()
                    )

                    is_active_value = (
                        row.get("is_active", "")
                        .strip()
                        .lower()
                    )

                    image = (
                        row.get("image", "")
                        .strip()
                    )

                    # -----------------------------------------
                    # BASIC VALIDATION
                    # -----------------------------------------

                    if not product_code:
                        raise ValueError(
                            "product_code is required"
                        )

                    if not name:
                        raise ValueError(
                            "name is required"
                        )

                    if not brand_name:
                        raise ValueError(
                            "brand is required"
                        )

                    if not category_name:
                        raise ValueError(
                            "category is required"
                        )

                    if not price_value:
                        raise ValueError(
                            "price is required"
                        )

                    if not stock_value:
                        raise ValueError(
                            "stock is required"
                        )

                    # -----------------------------------------
                    # PRICE
                    # -----------------------------------------

                    try:
                        price = Decimal(price_value)
                    except InvalidOperation:
                        raise ValueError(
                            f"Invalid price: {price_value}"
                        )

                    if price < 0:
                        raise ValueError(
                            "price cannot be negative"
                        )

                    # -----------------------------------------
                    # MRP
                    # -----------------------------------------

                    mrp = None

                    if mrp_value:
                        try:
                            mrp = Decimal(mrp_value)
                        except InvalidOperation:
                            raise ValueError(
                                f"Invalid MRP: {mrp_value}"
                            )

                        if mrp < 0:
                            raise ValueError(
                                "MRP cannot be negative"
                            )

                    # -----------------------------------------
                    # STOCK
                    # -----------------------------------------

                    try:
                        stock = int(stock_value)
                    except ValueError:
                        raise ValueError(
                            f"Invalid stock: {stock_value}"
                        )

                    if stock < 0:
                        raise ValueError(
                            "stock cannot be negative"
                        )

                    # -----------------------------------------
                    # BADGE
                    # -----------------------------------------

                    valid_badges = {
                        choice[0]
                        for choice in Product.BADGE_CHOICES
                    }

                    if badge not in valid_badges:
                        raise ValueError(
                            f"Invalid badge: {badge}"
                        )

                    # -----------------------------------------
                    # ACTIVE STATUS
                    # -----------------------------------------

                    if is_active_value in {
                        "true",
                        "1",
                        "yes",
                    }:
                        is_active = True

                    elif is_active_value in {
                        "false",
                        "0",
                        "no",
                    }:
                        is_active = False

                    else:
                        raise ValueError(
                            f"Invalid is_active value: "
                            f"{is_active_value}"
                        )

                    # -----------------------------------------
                    # CREATE / UPDATE
                    # -----------------------------------------

                    with transaction.atomic():

                        brand, _ = Brand.objects.get_or_create(
                            name=brand_name,
                            defaults={
                                "slug": slugify(
                                    brand_name
                                ),
                            },
                        )

                        category, _ = (
                            Category.objects.get_or_create(
                                name=category_name
                            )
                        )

                        product = Product.objects.filter(
                            product_code=product_code
                        ).first()

                        if product:

                            product.name = name
                            product.brand = brand
                            product.category = category
                            product.description = description
                            product.mrp = mrp
                            product.price = price
                            product.stock = stock
                            product.badge = badge
                            product.is_active = is_active
                            product.image = image

                            product.save()

                            updated += 1

                            self.stdout.write(
                                self.style.WARNING(
                                    f"↻ Updated: "
                                    f"{product_code} - {name}"
                                )
                            )

                        else:

                            Product.objects.create(
                                product_code=product_code,
                                name=name,
                                brand=brand,
                                category=category,
                                description=description,
                                mrp=mrp,
                                price=price,
                                stock=stock,
                                badge=badge,
                                is_active=is_active,
                                image=image,
                            )

                            imported += 1

                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"✓ Imported: "
                                    f"{product_code} - {name}"
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
                "       IMPORT COMPLETE"
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
            f"Updated  : {updated}"
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