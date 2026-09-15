from decimal import Decimal
from django.utils import timezone

from .models import ProductOffer


def get_active_offer(product, base_price=None, now=None):
    """
    Return the active offer that gives the lowest sale price.

    For variant products, base_price is the variant price.
    For normal products, base_price is the product price.
    """
    if now is None:
        now = timezone.now()

    if base_price is None:
        base_price = Decimal(product.price)
    else:
        base_price = Decimal(base_price)

    offers = ProductOffer.objects.filter(
        product=product,
        is_active=True,
        valid_from__lte=now,
        valid_until__gte=now,
    )

    best_offer = None
    best_sale_price = None

    for offer in offers:
        sale_price = offer.get_sale_price(base_price)

        if best_sale_price is None or sale_price < best_sale_price:
            best_sale_price = sale_price
            best_offer = offer

    return best_offer


def get_effective_price(product, base_price=None, now=None):
    """
    Calculate the effective selling price after ProductOffer.
    """

    if now is None:
        now = timezone.now()

    if base_price is None:
        base_price = Decimal(product.price)

    base_price = Decimal(base_price)

    offer = get_active_offer(
        product,
        base_price=base_price,
        now=now,
    )

    if not offer:
        return {
            "original_price": base_price,
            "discount_amount": Decimal("0.00"),
            "sale_price": base_price,
            "discount_percentage": Decimal("0.00"),
            "offer": None,
        }

    discount_amount = offer.calculate_discount(base_price)

    sale_price = (
        base_price - discount_amount
    ).quantize(Decimal("0.01"))

    discount_percentage = (
        ((discount_amount / base_price) * Decimal("100"))
        if base_price > 0
        else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    return {
        "original_price": base_price,
        "discount_amount": discount_amount,
        "sale_price": sale_price,
        "discount_percentage": discount_percentage,
        "offer": offer,
    }


def get_effective_unit_price(product, base_price=None, now=None):
    """
    Return only the final unit selling price after offer.
    """

    pricing = get_effective_price(
        product,
        base_price=base_price,
        now=now,
    )

    return pricing["sale_price"]