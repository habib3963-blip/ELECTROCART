from django.core.management.base import BaseCommand
from store.models import (
    Product,
    ProductImage,
    ProductVariant,
    ProductSpecification,
)


class Command(BaseCommand):

    help = "Validate ELECTROCART product catalogue data"

    def handle(self, *args, **options):

        errors = 0
        warnings = 0

        self.stdout.write("")
        self.stdout.write("========================================")
        self.stdout.write("     ELECTROCART CATALOGUE VALIDATION")
        self.stdout.write("========================================")

        products = Product.objects.all()

        self.stdout.write("")
        self.stdout.write(f"Products          : {products.count()}")
        self.stdout.write(
            f"Product Images    : {ProductImage.objects.count()}"
        )
        self.stdout.write(
            f"Product Variants  : {ProductVariant.objects.count()}"
        )
        self.stdout.write(
            f"Specifications    : {ProductSpecification.objects.count()}"
        )

        self.stdout.write("")
        self.stdout.write("----------------------------------------")
        self.stdout.write("PRODUCT VALIDATION")
        self.stdout.write("----------------------------------------")

        for product in products:

            if not product.product_code:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {product.name}: Product code missing"
                    )
                )

            if product.price < 0:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {product.product_code}: Negative price"
                    )
                )

            if product.mrp is not None and product.mrp < 0:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {product.product_code}: Negative MRP"
                    )
                )

            if product.mrp is not None and product.mrp < product.price:
                warnings += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ {product.product_code}: MRP is below selling price"
                    )
                )

            if not product.description.strip():
                warnings += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ {product.product_code}: Description is empty"
                    )
                )

            if product.stock < 0:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {product.product_code}: Negative stock"
                    )
                )

        self.stdout.write("")
        self.stdout.write("----------------------------------------")
        self.stdout.write("IMAGE VALIDATION")
        self.stdout.write("----------------------------------------")

        for product in products:

            images = ProductImage.objects.filter(
                product=product
            )

            if not images.exists():
                warnings += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ {product.product_code}: No product images"
                    )
                )
                continue

            primary_count = images.filter(
                is_primary=True
            ).count()

            if primary_count == 0:
                warnings += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ {product.product_code}: No primary image"
                    )
                )

            elif primary_count > 1:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {product.product_code}: "
                        f"Multiple primary images ({primary_count})"
                    )
                )

        self.stdout.write("")
        self.stdout.write("----------------------------------------")
        self.stdout.write("VARIANT VALIDATION")
        self.stdout.write("----------------------------------------")

        for variant in ProductVariant.objects.all():

            if not variant.sku.strip():
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Variant ID {variant.id}: SKU missing"
                    )
                )

            if variant.price < 0:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {variant.sku}: Negative price"
                    )
                )

            if variant.stock < 0:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {variant.sku}: Negative stock"
                    )
                )

        self.stdout.write("")
        self.stdout.write("----------------------------------------")
        self.stdout.write("SPECIFICATION VALIDATION")
        self.stdout.write("----------------------------------------")

        for specification in ProductSpecification.objects.all():

            if not specification.name.strip():
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Specification {specification.id}: Name missing"
                    )
                )

            if not specification.value.strip():
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {specification.product.product_code}: "
                        f"Specification value missing"
                    )
                )

            if specification.sort_order < 0:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Specification {specification.id}: "
                        f"Negative sort order"
                    )
                )

        self.stdout.write("")
        self.stdout.write("========================================")
        self.stdout.write("        VALIDATION COMPLETE")
        self.stdout.write("========================================")
        self.stdout.write(f"Errors   : {errors}")
        self.stdout.write(f"Warnings : {warnings}")
        self.stdout.write("========================================")

        if errors == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ Catalogue validation passed."
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    "✗ Catalogue validation found errors."
                )
            )