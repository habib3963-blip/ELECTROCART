from .models import Cart


def cart_count(request):
    count = 0

    if request.session.session_key:
        cart = Cart.objects.filter(
            session_key=request.session.session_key
        ).first()

        if cart:
            count = sum(
                item.quantity
                for item in cart.items.all()
            )

    return {
        "cart_count": count
    }