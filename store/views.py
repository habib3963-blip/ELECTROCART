from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db import transaction, IntegrityError
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from .invoice_pdf import invoice_pdf_response
from django.contrib import messages


import json
import re
import uuid
import time
import razorpay


# Razorpay
razorpay_client = razorpay.Client(
    auth=(
        settings.RAZORPAY_KEY_ID,
        settings.RAZORPAY_KEY_SECRET,
    )
)


def _create_razorpay_order_safely(order_id, total):
    """
    Create a Razorpay order with bounded recovery for transient network
    failures.

    If the request reaches Razorpay but the response is lost/reset, first
    look up the unique receipt before retrying. This avoids accidentally
    creating a second Razorpay order for the same local order.
    """
    receipt = f"EC-{order_id}"
    amount = int(total * 100)

    payload = {
        "amount": amount,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "order_id": str(order_id),
        },
    }

    last_error = None

    for attempt in range(3):
        try:
            return razorpay_client.order.create(payload)

        except Exception as exc:
            last_error = exc

            # The request may have reached Razorpay even if the response
            # was lost. Search by our unique receipt before retrying.
            try:
                existing_orders = razorpay_client.order.all({
                    "receipt": receipt,
                    "count": 10,
                })

                for candidate in existing_orders.get("items", []):
                    if (
                        candidate.get("receipt") == receipt
                        and candidate.get("amount") == amount
                        and candidate.get("currency") == "INR"
                        and str(
                            candidate.get("notes", {}).get("order_id", "")
                        ) == str(order_id)
                    ):
                        return candidate

            except Exception:
                # The recovery lookup can fail for the same network reason.
                pass

            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))

    raise last_error



from .models import (
    Category,
    Product,
    ProductVariant,
    Wishlist,
    Cart,
    CartItem,
    Order,
    OrderItem,
    Payment,
    Address,
    Review,
    Coupon,
)

from .pricing import (
    get_effective_price,
    get_effective_unit_price,
)



def calculate_coupon_discount(coupon, cart_total):
    """
    Calculate the discount for a validated coupon.
    Returns a Decimal discount amount.
    """

    discount = Decimal("0.00")

    if coupon.discount_type == "PERCENT":
        discount = (
            cart_total * coupon.discount_value
        ) / Decimal("100")

        if coupon.maximum_discount is not None:
            discount = min(
                discount,
                coupon.maximum_discount
            )

    elif coupon.discount_type == "FIXED":
        discount = coupon.discount_value

    # Never allow discount greater than cart total.
    discount = min(discount, cart_total)

    return discount.quantize(
        Decimal("0.01")
    )



def get_cart_pricing(cart_item):
    """
    Return the effective pricing for one cart item.

    Variant price is the base price when a variant exists.
    Product price is used for legacy/non-variant cart items.
    Active ProductOffer is applied by the pricing service.
    """
    base_price = (
        cart_item.variant.price
        if cart_item.variant is not None
        else cart_item.product.price
    )

    return get_effective_price(
        cart_item.product,
        base_price=base_price,
    )


def get_cart_subtotal(cart_items):
    """
    Calculate the cart subtotal using effective sale prices.
    This subtotal is before any coupon discount.
    """
    subtotal = Decimal("0.00")

    for cart_item in cart_items:
        pricing = get_cart_pricing(cart_item)
        subtotal += (
            pricing["sale_price"] * cart_item.quantity
        ).quantize(Decimal("0.01"))

    return subtotal


def get_valid_session_coupon(request, cart_total):
    """
    Re-validate the coupon stored in the session against the current
    cart total. The browser/session discount amount is never trusted.
    Returns (coupon, discount, final_total).
    """
    coupon = None
    discount = Decimal("0.00")
    final_total = cart_total

    code = request.session.get("applied_coupon")

    if not code:
        return coupon, discount, final_total

    now = timezone.now()

    coupon = Coupon.objects.filter(
        code=str(code).strip().upper(),
        is_active=True,
        valid_from__lte=now,
        valid_until__gte=now,
    ).first()

    if not coupon:
        request.session.pop("applied_coupon", None)
        request.session.pop("coupon_discount", None)
        return None, discount, final_total

    if (
        coupon.usage_limit is not None
        and coupon.used_count >= coupon.usage_limit
    ):
        request.session.pop("applied_coupon", None)
        request.session.pop("coupon_discount", None)
        return None, discount, final_total

    if cart_total < coupon.minimum_order_amount:
        request.session.pop("applied_coupon", None)
        request.session.pop("coupon_discount", None)
        return None, discount, final_total

    discount = calculate_coupon_discount(
        coupon,
        cart_total
    )

    final_total = cart_total - discount

    return coupon, discount, final_total


def apply_coupon(request):
    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid request method."
            },
            status=405
        )

    code = request.POST.get("code", "").strip().upper()

    if not code:
        return JsonResponse(
            {
                "success": False,
                "message": "Please enter a coupon code."
            },
            status=400
        )

    now = timezone.now()

    coupon = Coupon.objects.filter(
        code=code,
        is_active=True,
        valid_from__lte=now,
        valid_until__gte=now,
    ).first()

    if not coupon:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid or expired coupon."
            },
            status=400
        )

    if (
        coupon.usage_limit is not None
        and coupon.used_count >= coupon.usage_limit
    ):
        return JsonResponse(
            {
                "success": False,
                "message": "This coupon usage limit has been reached."
            },
            status=400
        )

    cart = Cart.objects.filter(
        session_key=request.session.session_key
    ).first()

    if not cart:
        return JsonResponse(
            {
                "success": False,
                "message": "Your cart is empty."
            },
            status=400
        )

    cart_items = list(
        cart.items.select_related("product", "variant")
    )

    if not cart_items:
        return JsonResponse(
            {
                "success": False,
                "message": "Your cart is empty."
            },
            status=400
        )

    # Coupon is calculated on the sale subtotal.
    cart_total = get_cart_subtotal(cart_items)

    if cart_total < coupon.minimum_order_amount:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    f"Minimum order amount is "
                    f"₹{coupon.minimum_order_amount}."
                )
            },
            status=400
        )

    discount = calculate_coupon_discount(
        coupon,
        cart_total
    )

    final_total = (
        cart_total - discount
    ).quantize(Decimal("0.01"))

    request.session["applied_coupon"] = coupon.code
    request.session["coupon_discount"] = str(discount)
    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "message": f"Coupon {coupon.code} applied successfully!",
            "coupon": coupon.code,
            "cart_total": str(cart_total),
            "discount": str(discount),
            "final_total": str(final_total),
        }
    )


def home(request):
    search_query = request.GET.get("search", "").strip()
    category_name = request.GET.get("category", "").strip()
    min_price = request.GET.get("min_price", "").strip()
    max_price = request.GET.get("max_price", "").strip()
    rating = request.GET.get("rating", "").strip()
    sort = request.GET.get("sort", "").strip()

    # ---------------------------------------------------------
    # BASE PRODUCT QUERY
    # ---------------------------------------------------------
    products = Product.objects.filter(
        is_active=True
    ).select_related("category")

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------
    if search_query:
        from django.db.models import Q

        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    # ---------------------------------------------------------
    # CATEGORY FILTER
    # ---------------------------------------------------------
    if category_name:
        products = products.filter(
            category__name__iexact=category_name
        )

    # ---------------------------------------------------------
    # PRICE FILTERS
    # Use Decimal for money values.
    # ---------------------------------------------------------
    try:
        if min_price:
            min_price_decimal = Decimal(min_price)

            if min_price_decimal >= Decimal("0.00"):
                products = products.filter(
                    price__gte=min_price_decimal
                )
    except (TypeError, ValueError, ArithmeticError):
        pass

    try:
        if max_price:
            max_price_decimal = Decimal(max_price)

            if max_price_decimal >= Decimal("0.00"):
                products = products.filter(
                    price__lte=max_price_decimal
                )
    except (TypeError, ValueError, ArithmeticError):
        pass

    # ---------------------------------------------------------
    # RATING FILTER
    # ---------------------------------------------------------
    allowed_ratings = {
        "2",
        "3",
        "4",
    }

    if rating in allowed_ratings:
        products = products.filter(
            rating__gte=Decimal(rating)
        )

    # ---------------------------------------------------------
    # SORTING
    # ---------------------------------------------------------
    allowed_sorts = {
        "price_asc",
        "price_desc",
        "rating",
        "newest",
    }

    if sort in allowed_sorts:

        if sort == "price_asc":
            products = products.order_by("price")

        elif sort == "price_desc":
            products = products.order_by("-price")

        elif sort == "rating":
            products = products.order_by("-rating")

        elif sort == "newest":
            products = products.order_by("-created_at")

    categories = Category.objects.all()

    return render(request, "home.html", {
        "products": products,
        "categories": categories,
        "search_query": search_query,
        "category_name": category_name,
        "min_price": min_price,
        "max_price": max_price,
        "rating": rating,
        "sort": sort,
    })


# =========================================================
# PRODUCT DETAIL
# =========================================================

def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("category"),
        pk=pk,
        is_active=True
    )

    # Track recently viewed products
    recently_viewed = request.session.get("recently_viewed", [])

    # Remove current product if already present
    recently_viewed = [
        product_id
        for product_id in recently_viewed
        if product_id != product.id
    ]

    # Add current product at the beginning
    recently_viewed.insert(0, product.id)

    # Keep only the latest 8 products
    recently_viewed = recently_viewed[:8]

    request.session["recently_viewed"] = recently_viewed
    request.session.modified = True

    # Get previously viewed products
    previously_viewed_ids = [
        product_id
        for product_id in recently_viewed
        if product_id != product.id
    ]

    recently_viewed_products = list(
        Product.objects
        .filter(
            id__in=previously_viewed_ids,
            is_active=True
        )
        .select_related("category")
    )

    # Preserve session order
    recently_viewed_products.sort(
        key=lambda item: previously_viewed_ids.index(item.id)
    )

    # Active variants

    variants = list(
        product.variants.filter(
            is_active=True
        ).order_by("color", "storage", "price")
    )

    # Product-level pricing
    product_pricing = get_effective_price(product)

    # Variant-level pricing
    variant_pricing = []

    for variant in variants:
        pricing = get_effective_price(
            product,
            base_price=variant.price,
        )

        variant_pricing.append({
            "variant": variant,
            "pricing": pricing,
        })

    # ---------------------------------------------------------
    # RELATED PRODUCTS
    # Same category + active + current product excluded
    # ---------------------------------------------------------
    related_products = (
        Product.objects
        .filter(
            category=product.category,
            is_active=True
        )
        .exclude(pk=product.pk)
        .select_related("category")
        .order_by("-created_at")[:6]
    )

    # ---------------------------------------------------------
    # REVIEWS
    # ---------------------------------------------------------
    reviews = (
        Review.objects
        .filter(product=product, is_approved=True)
        .select_related("user", "order_item")
        .order_by("-created_at")
    )

    review_count = reviews.count()

    if review_count:
        rating_total = sum(review.rating for review in reviews)
        average_rating = round(rating_total / review_count, 1)
    else:
        average_rating = 0

    rating_distribution = {}

    for rating in range(5, 0, -1):
        rating_count = sum(
            1 for review in reviews
            if review.rating == rating
        )

        percentage = (
            round((rating_count / review_count) * 100)
            if review_count
            else 0
        )

        rating_distribution[rating] = {
            "count": rating_count,
            "percentage": percentage,
        }

    # ---------------------------------------------------------
    # REVIEW ELIGIBILITY
    # ---------------------------------------------------------
    can_review = False
    review_order_items = []

    if request.user.is_authenticated:

        review_order_items = list(
            OrderItem.objects
            .filter(
                product=product,
                order__user=request.user,
                order__status="Delivered"
            )
            .select_related("order", "variant")
            .order_by("-order__created_at")
        )

        reviewed_order_item_ids = set(
            Review.objects
            .filter(
                product=product,
                user=request.user,
                order_item__isnull=False
            )
            .values_list("order_item_id", flat=True)
        )

        review_order_items = [
            item
            for item in review_order_items
            if item.id not in reviewed_order_item_ids
        ]

        can_review = bool(review_order_items)

    return render(request, "product_detail.html", {
        "product": product,

        # Pricing
        "product_pricing": product_pricing,
        "variant_pricing": variant_pricing,

        # Variants
        "variants": variants,
        "has_variants": bool(variants),

        # ⭐ Related Products
        "related_products": related_products,
        "recently_viewed_products": recently_viewed_products,

        # Reviews
        "reviews": reviews,
        "review_count": review_count,
        "average_rating": average_rating,
        "rating_distribution": rating_distribution,
        "can_review": can_review,
        "review_order_items": review_order_items,
    })



# =========================================================
# SUBMIT REVIEW
# =========================================================

@login_required(login_url="/account/login/")
def submit_review(request, pk):

    # Reviews can only be submitted through POST.
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method."
        }, status=405)

    # --------------------------------------------------
    # GET PRODUCT
    # --------------------------------------------------

    product = get_object_or_404(
        Product,
        pk=pk,
        is_active=True
    )

    # --------------------------------------------------
    # GET FORM DATA
    # --------------------------------------------------

    order_item_id = request.POST.get(
        "order_item_id",
        ""
    ).strip()

    rating = request.POST.get(
        "rating",
        ""
    ).strip()

    title = request.POST.get(
        "title",
        ""
    ).strip()

    comment = request.POST.get(
        "comment",
        ""
    ).strip()

    # --------------------------------------------------
    # ORDER ITEM VALIDATION
    # --------------------------------------------------

    try:
        order_item_id = int(order_item_id)
    except (TypeError, ValueError):
        return JsonResponse({
            "success": False,
            "message": "Please select a valid purchase."
        }, status=400)

    order_item = (
        OrderItem.objects
        .select_related("order", "product", "variant")
        .filter(
            id=order_item_id,
            product=product,
            order__user=request.user,
            order__status="Delivered",
        )
        .first()
    )

    if not order_item:
        return JsonResponse({
            "success": False,
            "message": (
                "You can review this product only after "
                "purchasing and receiving it."
            )
        }, status=403)

    # --------------------------------------------------
    # RATING VALIDATION
    # --------------------------------------------------

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return JsonResponse({
            "success": False,
            "message": "Please select a rating."
        }, status=400)

    if rating < 1 or rating > 5:
        return JsonResponse({
            "success": False,
            "message": "Rating must be between 1 and 5."
        }, status=400)

    # --------------------------------------------------
    # TEXT VALIDATION
    # --------------------------------------------------

    if len(title) > 150:
        return JsonResponse({
            "success": False,
            "message": "Review title is too long."
        }, status=400)

    if len(comment) > 5000:
        return JsonResponse({
            "success": False,
            "message": "Review comment is too long."
        }, status=400)

    # --------------------------------------------------
    # DUPLICATE REVIEW PROTECTION
    # --------------------------------------------------

    if Review.objects.filter(
        user=request.user,
        order_item=order_item
    ).exists():

        return JsonResponse({
            "success": False,
            "message": "You have already reviewed this purchase."
        }, status=409)

    # --------------------------------------------------
    # CREATE REVIEW
    # --------------------------------------------------

    try:
        with transaction.atomic():

            review = Review.objects.create(
                product=product,
                user=request.user,
                order_item=order_item,
                rating=rating,
                title=title,
                comment=comment,
                is_approved=True,
            )

            # --------------------------------------------------
            # UPDATE PRODUCT RATING
            # --------------------------------------------------

            approved_reviews = Review.objects.filter(
                product=product,
                is_approved=True,
            )

            review_count = approved_reviews.count()

            if review_count:
                rating_total = sum(
                    review_obj.rating
                    for review_obj in approved_reviews
                )

                average_rating = round(
                    rating_total / review_count,
                    1
                )
            else:
                average_rating = 0

            product.rating = average_rating
            product.reviews = review_count

            product.save(
                update_fields=[
                    "rating",
                    "reviews",
                ]
            )

    except IntegrityError:

        # Handles a simultaneous duplicate submission safely.
        return JsonResponse({
            "success": False,
            "message": "You have already reviewed this purchase."
        }, status=409)

    return JsonResponse({
        "success": True,
        "message": "Your review has been submitted successfully.",
        "review": {
            "id": review.id,
            "rating": review.rating,
            "title": review.title,
            "comment": review.comment,
            "username": request.user.username,
        },
        "average_rating": float(product.rating),
        "review_count": product.reviews,
    })


# =========================================================
# TOGGLE WISHLIST
# =========================================================

def toggle_wishlist(request, pk):

    # Security: wishlist changes must be POST
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method."
        }, status=405)

    product = get_object_or_404(
        Product,
        pk=pk,
        is_active=True
    )

    # Create session if required
    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key

    wishlist, created = Wishlist.objects.get_or_create(
        session_key=session_key
    )

    if product in wishlist.products.all():
        wishlist.products.remove(product)
        added = False
        message = "Removed from wishlist"
    else:
        wishlist.products.add(product)
        added = True
        message = "Added to wishlist"

    return JsonResponse({
        "success": True,
        "added": added,
        "message": message,
    })


# =========================================================
# WISHLIST PAGE
# =========================================================

def wishlist(request):

    if not request.session.session_key:
        return render(request, "wishlist.html", {
            "wishlist": None,
            "products": [],
        })

    wishlist = Wishlist.objects.filter(
        session_key=request.session.session_key
    ).first()

    if not wishlist:
        return render(request, "wishlist.html", {
            "wishlist": None,
            "products": [],
        })

    products = wishlist.products.filter(
        is_active=True
    )

    return render(request, "wishlist.html", {
        "wishlist": wishlist,
        "products": products,
    })


# =========================================================
# ADD TO CART
# =========================================================

def add_to_cart(request, pk):

    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method."
        }, status=405)

    product = get_object_or_404(
        Product,
        pk=pk,
        is_active=True
    )

    # --------------------------------------------------
    # VARIANT VALIDATION
    # --------------------------------------------------
    # Products with active variants must receive a valid
    # variant belonging to this exact product.
    variant_id = request.POST.get("variant_id", "").strip()
    active_variants_exist = product.variants.filter(
        is_active=True
    ).exists()

    variant = None

    if active_variants_exist:
        try:
            variant_id = int(variant_id)
        except (TypeError, ValueError):
            variant_id = None

        if not variant_id:
            return JsonResponse({
                "success": False,
                "message": "Please select a product variant."
            }, status=400)

        variant = get_object_or_404(
            ProductVariant,
            id=variant_id,
            product=product,
            is_active=True
        )

    # --------------------------------------------------
    # DETERMINE STOCK SOURCE
    # --------------------------------------------------
    # Variant products use variant stock. Legacy products
    # without variants continue using Product.stock.
    available_stock = (
        variant.stock
        if variant is not None
        else product.stock
    )

    if available_stock <= 0:

        if request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":

            return JsonResponse({
                "success": False,
                "message": "This product variant is currently out of stock."
            }, status=400)

        return redirect("cart")

    # Get quantity
    try:
        quantity = int(
            request.POST.get("quantity", 1)
        )
    except (TypeError, ValueError):
        quantity = 1

    # Quantity should never be less than 1
    if quantity < 1:
        quantity = 1

    # Quantity cannot exceed available stock
    if quantity > available_stock:
        quantity = available_stock

    # Session
    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key

    # Get / create cart
    cart, created = Cart.objects.get_or_create(
        session_key=session_key
    )

    # Variant is part of the cart item's identity.
    # This allows Black/128GB and Black/256GB to exist
    # as separate cart items.
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant
    )

    # Add quantity
    if created:
        cart_item.quantity = quantity
    else:
        new_quantity = cart_item.quantity + quantity

        # Cannot exceed available stock
        if new_quantity > available_stock:
            new_quantity = available_stock

        cart_item.quantity = new_quantity

    cart_item.save()

    # AJAX response
    if request.headers.get(
        "X-Requested-With"
    ) == "XMLHttpRequest":

        cart_count = sum(
            item.quantity
            for item in cart.items.all()
        )

        return JsonResponse({
            "success": True,
            "cart_count": cart_count,
            "message": (
                "Variant added to cart"
                if variant
                else "Product added to cart"
            )
        })

    # Normal request
    return redirect("cart")


# =========================================================
# CART
# =========================================================

def cart(request):
    session_key = request.session.session_key

    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    cart, _ = Cart.objects.get_or_create(
        session_key=session_key
    )

    items = list(
        cart.items.select_related(
            "product",
            "variant"
        )
    )

    # ---------------------------------------------------------
    # EFFECTIVE SALE PRICING
    # ---------------------------------------------------------
    for item in items:
        pricing = get_cart_pricing(item)

        item.effective_unit_price = pricing["sale_price"]

        item.effective_total_price = (
            pricing["sale_price"] * item.quantity
        ).quantize(Decimal("0.01"))

        item.original_unit_price = pricing["original_price"]
        item.discount_amount = pricing["discount_amount"]
        item.discount_percentage = pricing["discount_percentage"]
        item.offer = pricing["offer"]

    # ---------------------------------------------------------
    # CART SUBTOTAL
    # ---------------------------------------------------------
    subtotal = sum(
        (item.effective_total_price for item in items),
        Decimal("0.00")
    ).quantize(Decimal("0.01"))

    # ---------------------------------------------------------
    # SERVER-SIDE COUPON REVALIDATION
    # ---------------------------------------------------------
    coupon, coupon_discount, final_total = (
        get_valid_session_coupon(
            request,
            subtotal
        )
    )

    return render(
        request,
        "cart.html",
        {
            "cart": cart,
            "items": items,
            "total": subtotal,
            "coupon": coupon,
            "coupon_discount": coupon_discount,
            "final_total": final_total,
        },
    )




def update_cart_quantity(request, item_id):
    # Security: quantity changes must be POST
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method."
        }, status=405)

    # Session check
    if not request.session.session_key:
        return JsonResponse({
            "success": False,
            "message": "Cart session not found."
        }, status=400)

    # Only get item from current user's cart
    item = get_object_or_404(
        CartItem.objects.select_related(
            "product",
            "variant",
            "cart"
        ),
        id=item_id,
        cart__session_key=request.session.session_key
    )

    action = request.POST.get("action")

    if action == "increase":
        available_stock = (
            item.variant.stock
            if item.variant is not None
            else item.product.stock
        )

        if item.quantity < available_stock:
            item.quantity += 1
            item.save(update_fields=["quantity"])

    elif action == "decrease":
        if item.quantity > 1:
            item.quantity -= 1
            item.save(update_fields=["quantity"])

    else:
        return JsonResponse({
            "success": False,
            "message": "Invalid cart action."
        }, status=400)

    # Recalculate using offer-aware prices.
    cart_items = list(
        item.cart.items.select_related(
            "product",
            "variant"
        )
    )

    subtotal = get_cart_subtotal(cart_items)

    # Revalidate coupon after quantity changes.
    coupon, coupon_discount, final_total = (
        get_valid_session_coupon(
            request,
            subtotal
        )
    )

    current_pricing = get_cart_pricing(item)

    item_total = (
        current_pricing["sale_price"] * item.quantity
    ).quantize(Decimal("0.01"))

    return JsonResponse({
        "success": True,
        "quantity": item.quantity,
        "item_total": float(item_total),
        "cart_total": float(subtotal),
        "discount": float(coupon_discount),
        "final_total": float(final_total),
        "coupon": coupon.code if coupon else "",
    })




def remove_from_cart(request, item_id):
    # Security: removal must be POST
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method."
        }, status=405)

    if not request.session.session_key:
        return JsonResponse({
            "success": False,
            "message": "Cart session not found."
        }, status=400)

    item = get_object_or_404(
        CartItem.objects.select_related(
            "cart",
            "product",
            "variant"
        ),
        id=item_id,
        cart__session_key=request.session.session_key
    )

    cart = item.cart
    item.delete()

    cart_items = list(
        cart.items.select_related(
            "product",
            "variant"
        )
    )

    subtotal = get_cart_subtotal(cart_items)

    # Revalidate coupon after removing an item.
    coupon, coupon_discount, final_total = (
        get_valid_session_coupon(
            request,
            subtotal
        )
    )

    cart_count = sum(
        cart_item.quantity
        for cart_item in cart.items.all()
    )

    return JsonResponse({
        "success": True,
        "cart_total": float(subtotal),
        "discount": float(coupon_discount),
        "final_total": float(final_total),
        "coupon": coupon.code if coupon else "",
        "cart_count": cart_count,
    })




def checkout(request):

    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key

    cart = Cart.objects.filter(
        session_key=session_key
    ).first()

    if not cart:
        return redirect("cart")

    items = cart.items.select_related("product", "variant")

    addresses = (
        Address.objects.filter(
            user=request.user
        ).order_by("-is_default", "-created_at")
        if request.user.is_authenticated
        else Address.objects.none()
    )
    
    if not items.exists():

        checkout_token = request.session.get("checkout_token")

        if checkout_token:
            try:
                checkout_token = uuid.UUID(checkout_token)

                existing_order = Order.objects.filter(
                    checkout_token=checkout_token,
                    session_key=session_key
                ).first()

                if existing_order:
                    request.session.pop(
                        "checkout_token",
                        None
                    )

                    return redirect(
                        "order_success",
                        order_id=existing_order.id
                    )

            except (ValueError, TypeError):
                request.session.pop(
                    "checkout_token",
                    None
                )

        return redirect("cart")

    # --------------------------------------------------
    # CREATE / GET STABLE CHECKOUT TOKEN
    # --------------------------------------------------

    if not request.session.get("checkout_token"):
        request.session["checkout_token"] = str(
            uuid.uuid4()
        )

    checkout_token = request.session.get(
        "checkout_token"
    )

    try:
        checkout_token = uuid.UUID(
            checkout_token
        )

    except (ValueError, TypeError):

        checkout_token = uuid.uuid4()

        request.session["checkout_token"] = str(
            checkout_token
        )

    # --------------------------------------------------
    # CHECK IF THIS CHECKOUT ALREADY CREATED AN ORDER
    # --------------------------------------------------

    existing_order = Order.objects.filter(
        checkout_token=checkout_token,
        session_key=session_key
    ).first()

    if existing_order:

        # If an online payment is still pending,
        # allow the user to continue with payment.
        existing_payment = Payment.objects.filter(
            order=existing_order
        ).first()

        if (
            existing_payment
            and existing_payment.payment_method == "ONLINE"
            and existing_payment.payment_status == "PENDING"
            and existing_payment.razorpay_order_id
        ):

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": existing_order.total_amount,
                    "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                    "razorpay_order_id": (
                        existing_payment.razorpay_order_id
                    ),
                    "local_order_id": existing_order.id,
                    "customer_name": existing_order.customer_name,
                    "customer_email": existing_order.email,
                    "customer_phone": existing_order.phone,
                }
            )

        request.session.pop(
            "checkout_token",
            None
        )

        return redirect(
            "order_success",
            order_id=existing_order.id
        )

    # --------------------------------------------------
    # CALCULATE SALE-AWARE TOTAL
    # --------------------------------------------------
    # Product/variant price -> active ProductOffer -> sale price.
    # Coupon is applied after the sale subtotal.
    # --------------------------------------------------

    total = get_cart_subtotal(items)

    # ==================================================
    # SERVER-SIDE COUPON VALIDATION
    # ==================================================
    coupon, discount, final_total = get_valid_session_coupon(
        request,
        total
    )

    # ==================================================
    # RETRY EXISTING ONLINE PAYMENT
    # ==================================================

    retry_order_id = request.session.get("retry_order_id")

    if retry_order_id:

        try:
            retry_order_id = int(retry_order_id)
        except (TypeError, ValueError):
            request.session.pop("retry_order_id", None)
            retry_order_id = None

    if retry_order_id:

        retry_order = (
            Order.objects
            .filter(
                id=retry_order_id,
                session_key=session_key
            )
            .select_related("payment")
            .prefetch_related("items__product")
            .first()
        )

        if not retry_order:
            request.session.pop("retry_order_id", None)

        else:
            retry_payment_record = getattr(
                retry_order,
                "payment",
                None
            )

            if (
                retry_payment_record
                and retry_payment_record.payment_method == "ONLINE"
                and retry_payment_record.payment_status == "PENDING"
                and retry_payment_record.razorpay_order_id
            ):
                return render(
                    request,
                    "checkout.html",
                    {
                        "cart": cart,
                        "items": items,
                        "addresses": addresses,
                        "total": retry_order.total_amount,
                        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                        "razorpay_order_id": (
                            retry_payment_record.razorpay_order_id
                        ),
                        "local_order_id": retry_order.id,
                        "customer_name": retry_order.customer_name,
                        "customer_email": retry_order.email,
                        "customer_phone": retry_order.phone,
                    }
                )

            request.session.pop("retry_order_id", None)

    # ==================================================
    # POST - PLACE ORDER
    # ==================================================

    if request.method == "POST":

        customer_name = request.POST.get(
            "customer_name",
            ""
        ).strip()

        email = request.POST.get(
            "email",
            ""
        ).strip()

        phone = request.POST.get(
            "phone",
            ""
        ).strip()

        address = request.POST.get(
            "address",
            ""
        ).strip()

        city = request.POST.get(
            "city",
            ""
        ).strip()

        state = request.POST.get(
            "state",
            ""
        ).strip()

        pincode = request.POST.get(
            "pincode",
            ""
        ).strip()

        # --------------------------------------------------
        # SAVED ADDRESS VALIDATION
        # --------------------------------------------------

        saved_address_id = request.POST.get(
            "saved_address_id",
            ""
        ).strip()

        if saved_address_id and not request.user.is_authenticated:
            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": "Saved addresses are available only to logged-in users.",
                },
            )

        if saved_address_id and request.user.is_authenticated:

            try:
                saved_address_id = int(saved_address_id)
            except (TypeError, ValueError):
                return render(
                    request,
                    "checkout.html",
                    {
                        "cart": cart,
                        "items": items,
                        "addresses": addresses,
                        "total": total,
                        "error": "Invalid saved address selection.",
                    },
                )

            saved_address = Address.objects.filter(
                id=saved_address_id,
                user=request.user,
            ).first()

            if not saved_address:
                return render(
                    request,
                    "checkout.html",
                    {
                        "cart": cart,
                        "items": items,
                        "addresses": addresses,
                        "total": total,
                        "error": (
                            "The selected saved address is not "
                            "available for your account."
                        ),
                    },
                )

            # The database address is authoritative.
            customer_name = saved_address.full_name
            phone = saved_address.phone
            address = saved_address.address_line

            if saved_address.landmark:
                address = (
                    f"{address}, {saved_address.landmark}"
                )

            city = saved_address.city
            state = saved_address.state
            pincode = saved_address.pincode

        payment_method = request.POST.get(
            "payment_method",
            ""
        ).strip().upper()

        # --------------------------------------------------
        # PAYMENT METHOD VALIDATION
        # --------------------------------------------------
        # Only server-approved payment methods are accepted.
        if payment_method not in {"COD", "ONLINE"}:
            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": "Please select a valid payment method.",
                },
            )

        # --------------------------------------------------
        # REQUIRED FIELD VALIDATION
        # --------------------------------------------------

        if not all([
            customer_name,
            email,
            phone,
            address,
            city,
            state,
            pincode,
        ]):

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "Please fill in all required details."
                    ),
                }
            )

        # --------------------------------------------------
        # NAME VALIDATION
        # --------------------------------------------------

        # Allow normal names with spaces, hyphens, apostrophes and dots.
        if (
            len(customer_name) < 2
            or not re.fullmatch(
                r"[\w\s.\-']+",
                customer_name,
                flags=re.UNICODE,
            )
            or not any(ch.isalpha() for ch in customer_name)
        ):

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "Please enter a valid name."
                    ),
                }
            )

        # --------------------------------------------------
        # EMAIL VALIDATION
        # --------------------------------------------------

        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email
        ):

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "Please enter a valid email address."
                    ),
                }
            )

        # --------------------------------------------------
        # PHONE VALIDATION
        # --------------------------------------------------

        if not re.fullmatch(
            r"[6-9]\d{9}",
            phone
        ):

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "Phone number must contain exactly 10 digits."
                    ),
                }
            )

        # --------------------------------------------------
        # ADDRESS / CITY / STATE VALIDATION
        # --------------------------------------------------

        if len(address) < 10:
            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": "Please enter a complete delivery address.",
                }
            )

        if (
            len(city) < 2
            or not re.fullmatch(r"[\w\s.\-']+", city, flags=re.UNICODE)
            or not any(ch.isalpha() for ch in city)
        ):
            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": "Please enter a valid city.",
                }
            )

        if (
            len(state) < 2
            or not re.fullmatch(r"[\w\s.\-']+", state, flags=re.UNICODE)
            or not any(ch.isalpha() for ch in state)
        ):
            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": "Please enter a valid state.",
                }
            )

        # --------------------------------------------------
        # PINCODE VALIDATION
        # --------------------------------------------------

        if not re.fullmatch(
            r"[1-9]\d{5}",
            pincode
        ):

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "Pincode must contain exactly 6 digits."
                    ),
                }
            )

        # --------------------------------------------------
        # PAYMENT METHOD VALIDATION
        # --------------------------------------------------

        if payment_method not in [
            "COD",
            "ONLINE"
        ]:

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "Please select a valid payment method."
                    ),
                }
            )

        # ==================================================
        # FINAL CART / CHECKOUT PROTECTION
        # ==================================================
        # Re-check the cart immediately before order creation. The cart
        # may have changed after the checkout page was first loaded.
        fresh_items = cart.items.select_related("product", "variant")

        if not fresh_items.exists():
            request.session.pop("checkout_token", None)
            return redirect("cart")

        # Use the freshly queried cart for the transaction below.
        items = fresh_items

        # ==================================================
        # CREATE ORDER
        # ==================================================

        try:

            with transaction.atomic():

                # --------------------------------------------------
                # RE-CHECK EXISTING ORDER
                # --------------------------------------------------

                existing_order = Order.objects.filter(
                    checkout_token=checkout_token,
                    session_key=session_key
                ).first()

                if existing_order:

                    existing_payment = Payment.objects.filter(
                        order=existing_order
                    ).first()

                    if (
                        existing_payment
                        and existing_payment.payment_method == "ONLINE"
                        and existing_payment.payment_status == "PENDING"
                        and existing_payment.razorpay_order_id
                    ):

                        order = existing_order
                        payment = existing_payment

                    else:

                        request.session.pop(
                            "checkout_token",
                            None
                        )

                        return redirect(
                            "order_success",
                            order_id=existing_order.id
                        )

                else:

                    # --------------------------------------------------
                    # STOCK VALIDATION (LOCK PRODUCTS / VARIANTS)
                    # --------------------------------------------------
                    # Variant stock is authoritative for variant products.
                    # Legacy products without variants continue using Product.stock.
                    # Each exact inventory record is locked to prevent overselling.

                    locked_inventory = {}
                    locked_unit_prices = {}

                    for cart_item in items:

                        product = (
                            Product.objects
                            .select_for_update()
                            .filter(pk=cart_item.product_id)
                            .first()
                        )

                        if not product:
                            return render(
                                request,
                                "checkout.html",
                                {
                                    "cart": cart,
                                    "items": items,
                                    "addresses": addresses,
                                    "total": total,
                                    "error": "A product in your cart is no longer available.",
                                }
                            )

                        if not product.is_active:
                            return render(
                                request,
                                "checkout.html",
                                {
                                    "cart": cart,
                                    "items": items,
                                    "addresses": addresses,
                                    "total": total,
                                    "error": (
                                        f"{product.name} "
                                        "is no longer available."
                                    ),
                                }
                            )

                        if cart_item.variant_id:
                            variant = (
                                ProductVariant.objects
                                .select_for_update()
                                .filter(
                                    pk=cart_item.variant_id,
                                    product_id=product.id,
                                    is_active=True,
                                )
                                .first()
                            )

                            if not variant:
                                return render(
                                    request,
                                    "checkout.html",
                                    {
                                        "cart": cart,
                                        "items": items,
                                        "addresses": addresses,
                                        "total": total,
                                        "error": (
                                            f"{product.name} variant "
                                            "is no longer available."
                                        ),
                                    }
                                )

                            available_stock = variant.stock
                            unit_price = variant.price
                            inventory_key = ("variant", variant.id)
                            locked_inventory[inventory_key] = (
                                variant,
                                cart_item.quantity,
                            )

                        else:
                            available_stock = product.stock
                            unit_price = product.price
                            inventory_key = ("product", product.id)
                            locked_inventory[inventory_key] = (
                                product,
                                cart_item.quantity,
                            )

                        # Calculate the offer-aware sale price from the
                        # locked inventory price. This becomes the OrderItem
                        # price snapshot for this purchase.
                        effective_unit_price = get_effective_unit_price(
                            product,
                            base_price=unit_price,
                        )

                        locked_unit_prices[inventory_key] = (
                            effective_unit_price
                        )

                        if available_stock <= 0:
                            return render(
                                request,
                                "checkout.html",
                                {
                                    "cart": cart,
                                    "items": items,
                                    "addresses": addresses,
                                    "total": total,
                                    "error": (
                                        f"{product.name} "
                                        "is currently out of stock."
                                    ),
                                }
                            )

                        if cart_item.quantity > available_stock:
                            return render(
                                request,
                                "checkout.html",
                                {
                                    "cart": cart,
                                    "items": items,
                                    "addresses": addresses,
                                    "total": total,
                                    "error": (
                                        f"Only {available_stock} "
                                        f"item(s) of {product.name} "
                                        "are currently available."
                                    ),
                                }
                            )

                    # --------------------------------------------------
                    # RE-CALCULATE TOTAL FROM LOCKED INVENTORY
                    # --------------------------------------------------

                    total = Decimal("0.00")

                    for cart_item in items:
                        inventory_key = (
                            ("variant", cart_item.variant_id)
                            if cart_item.variant_id
                            else ("product", cart_item.product_id)
                        )

                        total += (
                            locked_unit_prices[inventory_key]
                            * cart_item.quantity
                        ).quantize(Decimal("0.01"))

                    total = total.quantize(Decimal("0.01"))

                    # --------------------------------------------------
                    # RE-VALIDATE COUPON FROM LOCKED CART TOTAL
                    # --------------------------------------------------
                    # This is the authoritative calculation used for the
                    # Order and Razorpay amount. Never trust the browser
                    # displayed total or the session discount value.
                    coupon, discount, final_total = (
                        get_valid_session_coupon(
                            request,
                            total
                        )
                    )

                    # --------------------------------------------------
                    # CREATE ORDER
                    # --------------------------------------------------

                    order = Order.objects.create(
                        session_key=session_key,
                        user=request.user if request.user.is_authenticated else None,
                        checkout_token=checkout_token,
                        customer_name=customer_name,
                        email=email,
                        phone=phone,
                        address=address,
                        city=city,
                        state=state,
                        pincode=pincode,
                        total_amount=final_total,
                        coupon=coupon,
                        discount_amount=discount,
                        status="Pending",
                    )

                    # --------------------------------------------------
                    # CREATE PAYMENT
                    # --------------------------------------------------

                    payment = Payment.objects.create(
                        order=order,
                        payment_method=payment_method,
                        payment_status="PENDING",
                    )

                    # --------------------------------------------------
                    # CREATE RAZORPAY ORDER
                    # --------------------------------------------------

                    if payment_method == "ONLINE":

                        razorpay_order = _create_razorpay_order_safely(
                            order.id,
                            final_total,
                        )

                        payment.razorpay_order_id = (
                            razorpay_order["id"]
                        )

                        payment.save(
                            update_fields=[
                                "razorpay_order_id"
                            ]
                        )

                    # --------------------------------------------------
                    # CREATE ORDER ITEMS
                    # --------------------------------------------------

                    for cart_item in items:

                        if cart_item.variant_id:
                            variant = locked_inventory[
                                ("variant", cart_item.variant_id)
                            ][0]
                            product = (
                                Product.objects
                                .select_related("category")
                                .get(pk=cart_item.product_id)
                            )

                            OrderItem.objects.create(
                                order=order,
                                product=product,
                                variant=variant,
                                quantity=cart_item.quantity,
                                price=locked_unit_prices[
                                    ("variant", cart_item.variant_id)
                                ],
                            )

                            # Reduce exact variant stock.
                            variant.stock -= cart_item.quantity
                            variant.save(
                                update_fields=["stock"]
                            )

                        else:
                            product = locked_inventory[
                                ("product", cart_item.product_id)
                            ][0]

                            OrderItem.objects.create(
                                order=order,
                                product=product,
                                variant=None,
                                quantity=cart_item.quantity,
                                price=locked_unit_prices[
                                    ("product", cart_item.product_id)
                                ],
                            )

                            # Reduce legacy product stock.
                            product.stock -= cart_item.quantity
                            product.save(
                                update_fields=["stock"]
                            )

                    # --------------------------------------------------
                    # CLEAR CART
                    # --------------------------------------------------

                    cart.items.all().delete()

        except IntegrityError:

            # Another identical checkout request
            # may have created the order first.

            existing_order = Order.objects.filter(
                checkout_token=checkout_token,
                session_key=session_key
            ).first()

            if existing_order:

                existing_payment = Payment.objects.filter(
                    order=existing_order
                ).first()

                if (
                    existing_payment
                    and existing_payment.payment_method == "ONLINE"
                    and existing_payment.payment_status == "PENDING"
                    and existing_payment.razorpay_order_id
                ):

                    return render(
                        request,
                        "checkout.html",
                        {
                            "cart": cart,
                            "items": items,
                            "addresses": addresses,
                            "total": existing_order.total_amount,
                            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                            "razorpay_order_id": (
                                existing_payment.razorpay_order_id
                            ),
                            "local_order_id": existing_order.id,
                            "customer_name": existing_order.customer_name,
                            "customer_email": existing_order.email,
                            "customer_phone": existing_order.phone,
                        }
                    )

                request.session.pop(
                    "checkout_token",
                    None
                )

                return redirect(
                    "order_success",
                    order_id=existing_order.id
                )

            raise

        except Exception:
            # The atomic transaction rolls back local order/stock changes.
            # Keep the cart intact and show a safe message instead of a
            # Django debug error page.
            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": total,
                    "error": (
                        "We couldn't connect to Razorpay right now. "
                        "Your cart is safe. Please try again in a moment."
                    ),
                },
            )

        # ==================================================
        # ONLINE PAYMENT
        # ==================================================

        if payment_method == "ONLINE":

            return render(
                request,
                "checkout.html",
                {
                    "cart": cart,
                    "items": items,
                    "addresses": addresses,
                    "total": final_total,
                    "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                    "razorpay_order_id": payment.razorpay_order_id,
                    "local_order_id": order.id,
                    "customer_name": customer_name,
                    "customer_email": email,
                    "customer_phone": phone,
                }
            )

        # ==================================================
        # COD
        # ==================================================

        request.session.pop(
            "checkout_token",
            None
        )

        request.session.pop(
            "applied_coupon",
            None
        )

        request.session.pop(
            "coupon_discount",
            None
        )

        return redirect(
            "order_success",
            order_id=order.id
        )

    # ==================================================
    # GET - SHOW CHECKOUT
    # ==================================================

    return render(
        request,
        "checkout.html",
        {
            "cart": cart,
            "items": items,
            "addresses": addresses,
            "total": total,
        }
    )


def verify_payment(request):

    if request.method != "POST":
        return redirect("cart")

    # =========================================================
    # GET PAYMENT DETAILS
    # =========================================================

    order_id = request.POST.get(
        "order_id",
        ""
    ).strip()

    razorpay_payment_id = request.POST.get(
        "razorpay_payment_id",
        ""
    ).strip()

    razorpay_order_id = request.POST.get(
        "razorpay_order_id",
        ""
    ).strip()

    razorpay_signature = request.POST.get(
        "razorpay_signature",
        ""
    ).strip()

    # =========================================================
    # BASIC VALIDATION
    # =========================================================

    if not all([
        order_id,
        razorpay_payment_id,
        razorpay_order_id,
        razorpay_signature,
    ]):

        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "Required payment details are missing."
                )
            }
        )

    # =========================================================
    # GET LOCAL ORDER
    # =========================================================

    order = get_object_or_404(
        Order,
        id=order_id,
        session_key=request.session.session_key
    )

    # =========================================================
    # GET LOCAL PAYMENT
    # =========================================================

    payment = get_object_or_404(
        Payment,
        order=order
    )

    # =========================================================
    # DUPLICATE PAYMENT PROTECTION
    # =========================================================

    if payment.payment_status == "PAID":

        request.session.pop(
            "checkout_token",
            None
        )

        return redirect(
            "order_success",
            order_id=order.id
        )

    # =========================================================
    # PAYMENT TYPE / RAZORPAY ORDER VALIDATION
    # =========================================================

    # This endpoint is only for ONLINE payments.
    # COD orders must never be marked paid through Razorpay verification.
    if payment.payment_method != "ONLINE":
        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "This order is not configured for online payment."
                )
            }
        )

    if payment.razorpay_order_id != razorpay_order_id:

        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "Invalid Razorpay order."
                )
            }
        )

    # =========================================================
    # VERIFY RAZORPAY SIGNATURE
    # =========================================================

    try:

        razorpay_client.utility.verify_payment_signature({

            "razorpay_order_id":
                razorpay_order_id,

            "razorpay_payment_id":
                razorpay_payment_id,

            "razorpay_signature":
                razorpay_signature,

        })

    except razorpay.errors.SignatureVerificationError:

        # Do not mutate payment state from an untrusted client response.
        # A verified Razorpay webhook remains authoritative.
        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "The payment signature is invalid."
                )
            }
        )

    # =========================================================
    # FETCH PAYMENT FROM RAZORPAY
    # =========================================================

    try:

        razorpay_payment = (
            razorpay_client.payment.fetch(
                razorpay_payment_id
            )
        )

    except Exception:

        # Keep the local payment pending when Razorpay cannot be queried.
        # The webhook/retry flow can reconcile it later.
        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Unable to verify the payment "
                    "with Razorpay. Please try again."
                )
            }
        )

    # =========================================================
    # VERIFY RAZORPAY ORDER ID FROM PAYMENT
    # =========================================================

    fetched_order_id = razorpay_payment.get(
        "order_id"
    )

    if fetched_order_id != payment.razorpay_order_id:

        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "Payment does not belong to this order."
                )
            }
        )

    # =========================================================
    # VERIFY AMOUNT
    # =========================================================

    expected_amount = int(
        Decimal(str(order.total_amount)) * 100
    )

    received_amount = int(
        razorpay_payment.get(
            "amount",
            0
        )
    )

    if received_amount != expected_amount:

        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "Payment amount does not match "
                    "the order amount."
                )
            }
        )

    # =========================================================
    # VERIFY CURRENCY
    # =========================================================

    if razorpay_payment.get(
        "currency"
    ) != "INR":

        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment verification failed. "
                    "Invalid payment currency."
                )
            }
        )

    # =========================================================
    # VERIFY CAPTURED STATUS
    # =========================================================

    payment_status = razorpay_payment.get(
        "status"
    )

    payment_captured = razorpay_payment.get(
        "captured",
        False
    )

    if (
        payment_status != "captured"
        or payment_captured is not True
    ):

        payment.payment_status = "PENDING"

        payment.save(
            update_fields=[
                "payment_status",
                "updated_at",
            ]
        )

        return render(
            request,
            "order_success.html",
            {
                "payment_error": (
                    "Payment has not been captured yet. "
                    "Please wait or try again."
                )
            }
        )

    # =========================================================
    # FINAL DATABASE UPDATE
    # =========================================================

    with transaction.atomic():

        payment = (
            Payment.objects
            .select_for_update()
            .get(
                order=order
            )
        )

        order = (
            Order.objects
            .select_for_update()
            .get(
                id=order.id
            )
        )

        # Prevent duplicate verification
        if payment.payment_status == "PAID":

            request.session.pop(
                "checkout_token",
                None
            )

            return redirect(
                "order_success",
                order_id=order.id
            )

        # -----------------------------------------------------
        # PAYMENT ID REUSE PROTECTION
        # -----------------------------------------------------

        payment_with_same_id = (
            Payment.objects
            .filter(razorpay_payment_id=razorpay_payment_id)
            .exclude(pk=payment.pk)
            .first()
        )

        if payment_with_same_id:
            return render(
                request,
                "order_success.html",
                {
                    "payment_error": (
                        "Payment verification failed. "
                        "This Razorpay payment is already linked to another order."
                    )
                }
            )

        # -----------------------------------------------------
        # PAYMENT DETAILS
        # -----------------------------------------------------

        payment.razorpay_payment_id = (
            razorpay_payment_id
        )

        payment.razorpay_order_id = (
            razorpay_order_id
        )

        payment.razorpay_signature = (
            razorpay_signature
        )

        payment.transaction_id = (
            razorpay_payment_id
        )

        payment.payment_status = "PAID"

        payment.paid_at = timezone.now()

        payment.stock_released = False

        payment.save(
            update_fields=[
                "razorpay_payment_id",
                "razorpay_order_id",
                "razorpay_signature",
                "transaction_id",
                "payment_status",
                "paid_at",
                "stock_released",
                "updated_at",
            ]
        )

        # -----------------------------------------------------
        # ORDER STATUS
        # -----------------------------------------------------

        order.status = "Confirmed"

        # Keep Order payment status synchronized
        order.payment_status = "Paid"

        order.payment_method = "ONLINE"

        order.save(
            update_fields=[
                "status",
                "payment_status",
                "payment_method",
            ]
        )

    # =========================================================
    # CLEAR CHECKOUT SESSION
    # =========================================================

    request.session.pop(
        "checkout_token",
        None
    )

    request.session.pop(
        "retry_order_id",
        None
    )

    request.session.pop(
        "applied_coupon",
        None
    )

    request.session.pop(
        "coupon_discount",
        None
    )

    # =========================================================
    # SUCCESS
    # =========================================================

    return redirect(
        "order_success",
        order_id=order.id
    )


# =========================================================
# INVENTORY HELPERS
# =========================================================

def _restore_order_stock_and_cart(order):
    """
    Restore the inventory reserved by an order and put the items
    back into the customer's session cart.

    Caller should run this inside transaction.atomic().
    """
    cart, _ = Cart.objects.get_or_create(
        session_key=order.session_key
    )

    for order_item in order.items.select_related("product", "variant"):
        product = Product.objects.select_for_update().get(
            pk=order_item.product_id
        )

        if order_item.variant_id:
            variant = ProductVariant.objects.select_for_update().get(
                pk=order_item.variant_id,
                product_id=product.id,
            )

            variant.stock += order_item.quantity
            variant.save(update_fields=["stock"])

            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                variant=variant,
                defaults={"quantity": order_item.quantity}
            )
        else:
            product.stock += order_item.quantity
            product.save(update_fields=["stock"])

            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                variant=None,
                defaults={"quantity": order_item.quantity}
            )

        if not created:
            cart_item.quantity += order_item.quantity
            cart_item.save(update_fields=["quantity"])


def _reserve_order_stock(order):
    """
    Re-reserve stock for an order after a failed payment attempt.

    Returns True when all items can be reserved.
    Caller should run this inside transaction.atomic().
    """
    order_items = list(
        order.items.select_related("product", "variant")
    )

    locked_inventory = []

    # Lock and validate every exact inventory record before changing stock.
    for order_item in order_items:
        product = Product.objects.select_for_update().get(
            pk=order_item.product_id
        )

        if not product.is_active:
            return False

        if order_item.variant_id:
            variant = ProductVariant.objects.select_for_update().filter(
                pk=order_item.variant_id,
                product_id=product.id,
                is_active=True,
            ).first()

            if not variant or variant.stock < order_item.quantity:
                return False

            locked_inventory.append(
                (variant, order_item.quantity, "variant")
            )
        else:
            if product.stock < order_item.quantity:
                return False

            locked_inventory.append(
                (product, order_item.quantity, "product")
            )

    # Only change stock after every item has passed validation.
    for inventory, quantity, inventory_type in locked_inventory:
        inventory.stock -= quantity
        inventory.save(update_fields=["stock"])

    return True


# =========================================================
# RAZORPAY WEBHOOK
# =========================================================

@csrf_exempt
def razorpay_webhook(request):

    # --------------------------------------------------
    # ONLY POST REQUESTS
    # --------------------------------------------------

    if request.method != "POST":
        return HttpResponse(
            "Method Not Allowed",
            status=405
        )

    # --------------------------------------------------
    # GET WEBHOOK SECRET
    # --------------------------------------------------

    webhook_secret = getattr(
        settings,
        "RAZORPAY_WEBHOOK_SECRET",
        None
    )

    if not webhook_secret:
        return HttpResponse(
            "Webhook secret is not configured.",
            status=500
        )

    # --------------------------------------------------
    # VERIFY RAW BODY SIGNATURE BEFORE PARSING JSON
    # --------------------------------------------------

    raw_body = request.body

    webhook_signature = request.headers.get(
        "X-Razorpay-Signature",
        ""
    )

    if not webhook_signature:
        return HttpResponse(
            "Missing webhook signature.",
            status=400
        )

    try:
        razorpay_client.utility.verify_webhook_signature(
            raw_body.decode("utf-8"),
            webhook_signature,
            webhook_secret
        )
    except Exception:
        return HttpResponse(
            "Invalid webhook signature.",
            status=400
        )

    # --------------------------------------------------
    # PARSE JSON ONLY AFTER SIGNATURE VERIFICATION
    # --------------------------------------------------

    try:
        payload = json.loads(
            raw_body.decode("utf-8")
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(
            "Invalid JSON payload.",
            status=400
        )

    event = payload.get("event", "")

    # Razorpay's order.paid payload also contains the
    # payment entity, so payment/order information is
    # available from the same location.
    payment_entity = (
        payload
        .get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )

    razorpay_order_id = payment_entity.get("order_id")
    razorpay_payment_id = payment_entity.get("id")
    amount = payment_entity.get("amount")
    currency = payment_entity.get("currency")
    payment_status = payment_entity.get("status")
    captured = payment_entity.get("captured")

    # --------------------------------------------------
    # IGNORE EVENTS WE DON'T HANDLE
    # --------------------------------------------------

    if event not in [
        "payment.captured",
        "payment.failed",
        "order.paid",
    ]:
        return HttpResponse(
            "Event ignored.",
            status=200
        )

    if not razorpay_order_id:
        return HttpResponse(
            "Razorpay order ID missing.",
            status=400
        )

    # --------------------------------------------------
    # FIND LOCAL PAYMENT + LOCK IT
    # --------------------------------------------------

    try:
        with transaction.atomic():

            payment = (
                Payment.objects
                .select_for_update()
                .select_related("order")
                .get(
                    razorpay_order_id=razorpay_order_id
                )
            )

            order = (
                Order.objects
                .select_for_update()
                .get(pk=payment.order_id)
            )

            # ==================================================
            # SUCCESSFUL PAYMENT
            # ==================================================

            if event in [
                "payment.captured",
                "order.paid",
            ]:

                # Security validation.
                expected_amount = int(
                    Decimal(str(order.total_amount)) * 100
                )

                if amount != expected_amount:
                    return HttpResponse(
                        "Invalid payment amount.",
                        status=400
                    )

                if currency != "INR":
                    return HttpResponse(
                        "Invalid payment currency.",
                        status=400
                    )

                if payment_status != "captured":
                    return HttpResponse(
                        "Payment is not captured.",
                        status=400
                    )

                if captured is not True:
                    return HttpResponse(
                        "Payment capture not confirmed.",
                        status=400
                    )

                # --------------------------------------------------
                # DUPLICATE SUCCESS EVENT
                # --------------------------------------------------

                if payment.payment_status == "PAID":

                    # A successful payment must always leave the
                    # order in the paid/confirmed state.
                    if (
                        order.status != "Confirmed"
                        or order.payment_status != "Paid"
                        or order.payment_method != "ONLINE"
                    ):
                        order.status = "Confirmed"
                        order.payment_status = "Paid"
                        order.payment_method = "ONLINE"
                        order.save(
                            update_fields=[
                                "status",
                                "payment_status",
                                "payment_method",
                            ]
                        )

                    return HttpResponse(
                        "Already processed.",
                        status=200
                    )

                # --------------------------------------------------
                # IMPORTANT LATE-SUCCESS PROTECTION
                # --------------------------------------------------
                # A previous payment attempt may have failed and
                # released stock. If a later payment attempt for
                # the SAME Razorpay order is captured, reserve the
                # stock again before confirming the order.

                if payment.stock_released:

                    stock_reserved = _reserve_order_stock(order)

                    if not stock_reserved:
                        # Payment is genuinely captured, but inventory
                        # is no longer available. Do not silently mark
                        # the order as fulfilled without stock.
                        #
                        # Returning 500 asks Razorpay to retry the
                        # webhook. The database transaction rolls back.
                        return HttpResponse(
                            "Payment captured but stock is unavailable.",
                            status=500
                        )

                    payment.stock_released = False

                # --------------------------------------------------
                # PAYMENT ID OWNERSHIP CHECK
                # --------------------------------------------------

                if razorpay_payment_id:
                    conflicting_payment = (
                        Payment.objects
                        .filter(razorpay_payment_id=razorpay_payment_id)
                        .exclude(pk=payment.pk)
                        .exists()
                    )

                    if conflicting_payment:
                        return HttpResponse(
                            "Payment ID is already linked to another order.",
                            status=400
                        )

                # --------------------------------------------------
                # SAVE PAYMENT
                # --------------------------------------------------

                payment.payment_status = "PAID"

                if razorpay_payment_id:
                    payment.razorpay_payment_id = (
                        razorpay_payment_id
                    )
                    payment.transaction_id = (
                        razorpay_payment_id
                    )

                payment.paid_at = (
                    payment.paid_at
                    or timezone.now()
                )

                payment.save(
                    update_fields=[
                        "payment_status",
                        "razorpay_payment_id",
                        "transaction_id",
                        "paid_at",
                        "stock_released",
                        "updated_at",
                    ]
                )

                # --------------------------------------------------
                # CONFIRM ORDER
                # --------------------------------------------------

                order.status = "Confirmed"
                order.payment_status = "Paid"
                order.payment_method = "ONLINE"

                order.save(
                    update_fields=[
                        "status",
                        "payment_status",
                        "payment_method",
                    ]
                )

                return HttpResponse(
                    "Payment processed.",
                    status=200
                )

            # ==================================================
            # FAILED PAYMENT
            # ==================================================

            if event == "payment.failed":

                # A successful payment is final for this order.
                # Never let a late failure event undo it.
                if payment.payment_status == "PAID":
                    return HttpResponse(
                        "Payment already successful.",
                        status=200
                    )

                payment.payment_status = "FAILED"

                # --------------------------------------------------
                # RESTORE STOCK + CART ONLY ONCE
                # --------------------------------------------------

                if not payment.stock_released:
                    _restore_order_stock_and_cart(order)
                    payment.stock_released = True

                payment.save(
                    update_fields=[
                        "payment_status",
                        "stock_released",
                        "updated_at",
                    ]
                )

                # --------------------------------------------------
                # KEEP ORDER RETRYABLE
                # --------------------------------------------------

                if order.status != "Cancelled":
                    order.status = "Pending"
                    order.payment_status = "Failed"

                    order.save(
                        update_fields=[
                            "status",
                            "payment_status",
                        ]
                    )

                return HttpResponse(
                    "Payment failure processed.",
                    status=200
                )

    except Payment.DoesNotExist:
        # Unknown Razorpay order/payment: acknowledge the webhook
        # so Razorpay does not keep retrying an unrelated event.
        return HttpResponse(
            "Payment not found. Event ignored.",
            status=200
        )

    except Exception:
        # Unexpected processing error: return 500 so Razorpay can retry.
        return HttpResponse(
            "Webhook processing failed.",
            status=500
        )


def mark_payment_failed(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid request method."
            },
            status=405
        )

    order_id = request.POST.get("order_id", "").strip()
    razorpay_order_id = request.POST.get("razorpay_order_id", "").strip()
    razorpay_payment_id = request.POST.get("razorpay_payment_id", "").strip()

    if not order_id or not razorpay_order_id:
        return JsonResponse(
            {
                "success": False,
                "message": "Payment details are missing."
            },
            status=400
        )

    # The browser's payment.failed event is only a signal.
    # Confirm the actual Razorpay state server-side before releasing stock.
    # Prefer the exact payment ID, but fall back to the Razorpay order's
    # payment collection because a transient payment-fetch failure should
    # not incorrectly report that cart recovery failed.
    razorpay_payment = None

    try:
        if razorpay_payment_id:
            razorpay_payment = razorpay_client.payment.fetch(
                razorpay_payment_id
            )
    except Exception:
        razorpay_payment = None

    if razorpay_payment is None:
        try:
            payment_collection = razorpay_client.order.payments(
                razorpay_order_id
            )
            payment_items = payment_collection.get("items", [])

            # First try the exact payment ID, if the browser supplied one.
            if razorpay_payment_id:
                for item in payment_items:
                    if item.get("id") == razorpay_payment_id:
                        razorpay_payment = item
                        break

            # Otherwise select a failed payment belonging to this order.
            if razorpay_payment is None:
                expected_amount = None
                try:
                    local_order = Order.objects.get(
                        id=order_id,
                        session_key=request.session.session_key
                    )
                    expected_amount = int(
                        Decimal(str(local_order.total_amount)) * 100
                    )
                except Order.DoesNotExist:
                    pass

                failed_items = [
                    item for item in payment_items
                    if item.get("status") == "failed"
                    and item.get("order_id") == razorpay_order_id
                    and item.get("currency") == "INR"
                    and (
                        expected_amount is None
                        or item.get("amount") == expected_amount
                    )
                ]

                if failed_items:
                    razorpay_payment = failed_items[-1]

        except Exception:
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Razorpay has not confirmed the failed payment yet. "
                        "Your payment status will be reconciled automatically."
                    )
                },
                status=409
            )

    if razorpay_payment is None:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Razorpay has not confirmed the failed payment yet. "
                    "Please wait a moment and try again."
                )
            },
            status=409
        )

    fetched_payment_id = razorpay_payment.get("id")
    fetched_order_id = razorpay_payment.get("order_id")
    fetched_status = razorpay_payment.get("status")
    fetched_amount = razorpay_payment.get("amount")
    fetched_currency = razorpay_payment.get("currency")

    if fetched_order_id != razorpay_order_id:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid Razorpay payment mapping."
            },
            status=400
        )

    if fetched_payment_id and razorpay_payment_id and fetched_payment_id != razorpay_payment_id:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid Razorpay payment ID."
            },
            status=400
        )

    if fetched_currency != "INR":
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid payment currency."
            },
            status=400
        )

    try:
        order = Order.objects.get(
            id=order_id,
            session_key=request.session.session_key
        )
    except Order.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "message": "Order not found."
            },
            status=404
        )

    expected_amount = int(Decimal(str(order.total_amount)) * 100)
    if fetched_amount != expected_amount:
        return JsonResponse(
            {
                "success": False,
                "message": "Payment amount does not match the order."
            },
            status=400
        )

    if fetched_status == "captured":
        return JsonResponse(
            {
                "success": True,
                "message": "Payment succeeded. Please refresh the page."
            }
        )

    if fetched_status != "failed":
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Payment is not confirmed as failed yet. "
                    "Please wait for Razorpay confirmation."
                )
            },
            status=409
        )

    try:
        with transaction.atomic():

            order = (
                Order.objects
                .select_for_update()
                .get(
                    id=order_id,
                    session_key=request.session.session_key
                )
            )

            payment = (
                Payment.objects
                .select_for_update()
                .get(order=order)
            )

            if payment.payment_status == "PAID":
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Payment is already successful."
                    }
                )

            if payment.payment_method != "ONLINE":
                return JsonResponse(
                    {
                        "success": False,
                        "message": "Invalid payment method."
                    },
                    status=400
                )

            if payment.razorpay_order_id != fetched_order_id:
                return JsonResponse(
                    {
                        "success": False,
                        "message": "Invalid Razorpay order."
                    },
                    status=400
                )

            conflicting_payment = (
                Payment.objects
                .filter(razorpay_payment_id=fetched_payment_id)
                .exclude(pk=payment.pk)
                .exists()
                if fetched_payment_id
                else False
            )

            if conflicting_payment:
                return JsonResponse(
                    {
                        "success": False,
                        "message": "Payment is already linked to another order."
                    },
                    status=409
                )

            if not payment.stock_released:
                _restore_order_stock_and_cart(order)
                payment.stock_released = True

            payment.payment_status = "FAILED"
            if fetched_payment_id:
                payment.razorpay_payment_id = fetched_payment_id

            payment.save(
                update_fields=[
                    "payment_status",
                    "razorpay_payment_id",
                    "stock_released",
                    "updated_at",
                ]
            )

            if order.status != "Cancelled":
                order.status = "Pending"
                order.payment_status = "Failed"
                order.save(
                    update_fields=[
                        "status",
                        "payment_status",
                    ]
                )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Payment failed. Stock and cart restored."
                )
            }
        )

    except Payment.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "message": "Payment record not found."
            },
            status=404
        )


def retry_payment(request, order_id):

    if request.method != "POST":
        return redirect("my_orders")

    if not request.session.session_key:
        return redirect("home")

    try:
        with transaction.atomic():

            order = (
                Order.objects
                .select_for_update()
                .get(
                    id=order_id,
                    session_key=request.session.session_key
                )
            )

            payment = (
                Payment.objects
                .select_for_update()
                .get(order=order)
            )

            if payment.payment_method != "ONLINE":
                return redirect("order_detail", order_id=order.id)

            if payment.payment_status == "PAID":
                return redirect("order_detail", order_id=order.id)

            if order.status in ["Cancelled", "Delivered"]:
                return redirect("order_detail", order_id=order.id)

            if not payment.razorpay_order_id:
                return redirect("order_detail", order_id=order.id)

            order_items = list(
                order.items.select_related("product", "variant")
            )

            if not order_items:
                return redirect("order_detail", order_id=order.id)

            # Lock every exact inventory record before checking/reserving stock.
            locked_inventory = []

            for order_item in order_items:
                product = (
                    Product.objects
                    .select_for_update()
                    .filter(pk=order_item.product_id)
                    .first()
                )

                if not product or not product.is_active:
                    return redirect("order_detail", order_id=order.id)

                if order_item.variant_id:
                    variant = (
                        ProductVariant.objects
                        .select_for_update()
                        .filter(
                            pk=order_item.variant_id,
                            product_id=product.id,
                            is_active=True,
                        )
                        .first()
                    )

                    if not variant:
                        return redirect("order_detail", order_id=order.id)

                    # If stock was already released for this payment attempt,
                    # reserve the exact variant again.
                    if payment.stock_released and variant.stock < order_item.quantity:
                        return redirect("order_detail", order_id=order.id)

                    locked_inventory.append(
                        (variant, order_item.quantity)
                    )
                else:
                    # Legacy product without variants.
                    if payment.stock_released and product.stock < order_item.quantity:
                        return redirect("order_detail", order_id=order.id)

                    locked_inventory.append(
                        (product, order_item.quantity)
                    )

            # Re-reserve only after every inventory record passed validation.
            if payment.stock_released:
                for inventory, quantity in locked_inventory:
                    inventory.stock -= quantity
                    inventory.save(update_fields=["stock"])

                payment.stock_released = False

            payment.payment_status = "PENDING"
            payment.razorpay_payment_id = None
            payment.razorpay_signature = None
            payment.transaction_id = None
            payment.paid_at = None

            payment.save(
                update_fields=[
                    "payment_status",
                    "stock_released",
                    "razorpay_payment_id",
                    "razorpay_signature",
                    "transaction_id",
                    "paid_at",
                    "updated_at",
                ]
            )

            order.status = "Pending"
            order.payment_status = "Pending"
            order.payment_method = "ONLINE"

            order.save(
                update_fields=[
                    "status",
                    "payment_status",
                    "payment_method",
                ]
            )

            request.session["retry_order_id"] = order.id

        return redirect("checkout")

    except Order.DoesNotExist:
        return redirect("my_orders")

    except Payment.DoesNotExist:
        return redirect("my_orders")


# =========================================================
# ORDER SUCCESS
# =========================================================

def order_success(request, order_id):

    # Security: only allow current session's order
    if not request.session.session_key:
        return redirect("home")

    order = get_object_or_404(
        Order,
        id=order_id,
        session_key=request.session.session_key
    )

    return render(request, "order_success.html", {
        "order": order,
    })


# =========================================================
# MY ORDERS
# =========================================================

def my_orders(request):

    if not request.session.session_key:
        return render(request, "my_orders.html", {
            "orders": [],
            "search_query": "",
            "status_filter": "",
        })

    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    orders = (
        Order.objects
        .filter(
            session_key=request.session.session_key
        )
        .select_related("payment")
        .order_by("-created_at")
    )

    # SEARCH
    if search_query:
        from django.db.models import Q

        search_filter = Q(
            customer_name__icontains=search_query
        )

        # Allow searching by Order ID
        if search_query.isdigit():
            search_filter |= Q(
                id=int(search_query)
            )

        orders = orders.filter(search_filter)

    # STATUS FILTER
    valid_statuses = {
        "Pending",
        "Confirmed",
        "Processing",
        "Shipped",
        "Out for Delivery",
        "Delivered",
        "Cancelled",
    }

    if status_filter in valid_statuses:
        orders = orders.filter(
            status=status_filter
        )

    return render(request, "my_orders.html", {
        "orders": orders,
        "search_query": search_query,
        "status_filter": status_filter,
    })

# =========================================================
# ORDER DETAIL
# =========================================================

def order_detail(request, order_id):

    if not request.session.session_key:
        return redirect("home")

    order = get_object_or_404(
            Order.objects.select_related(
                "payment"
            ).prefetch_related(
                "items__product",
                "items__variant"
            ),
            id=order_id,
            session_key=request.session.session_key
        )

    return render(request, "order_detail.html", {
        "order": order,
    })


# =========================================================
# SECURE REORDER
# =========================================================

def reorder_order(request, order_id):

    # Reorder must be POST
    if request.method != "POST":
        return redirect("my_orders")

    # Session security
    if not request.session.session_key:
        return redirect("home")

    try:
        with transaction.atomic():

            # -------------------------------------------------
            # GET CURRENT USER'S ORDER
            # -------------------------------------------------

            order = (
                Order.objects
                .prefetch_related(
                    "items__product",
                    "items__variant"
                )
                .get(
                    id=order_id,
                    session_key=request.session.session_key
                )
            )

            order_items = list(
                order.items.all()
            )

            if not order_items:
                messages.error(
                    request,
                    "This order has no items to reorder."
                )

                return redirect("my_orders")

            # -------------------------------------------------
            # GET / CREATE CURRENT SESSION CART
            # -------------------------------------------------

            cart, created = Cart.objects.get_or_create(
                session_key=request.session.session_key
            )

            # -------------------------------------------------
            # VALIDATE EVERYTHING FIRST
            # -------------------------------------------------

            reorder_items = []

            for order_item in order_items:

                product = (
                    Product.objects
                    .select_for_update()
                    .filter(
                        pk=order_item.product_id,
                        is_active=True
                    )
                    .first()
                )

                if not product:

                    messages.error(
                        request,
                        "One or more products are no longer available."
                    )

                    return redirect("my_orders")

                # ---------------------------------------------
                # VARIANT PRODUCT
                # ---------------------------------------------

                if order_item.variant_id:

                    variant = (
                        ProductVariant.objects
                        .select_for_update()
                        .filter(
                            pk=order_item.variant_id,
                            product_id=product.id,
                            is_active=True
                        )
                        .first()
                    )

                    if not variant:

                        messages.error(
                            request,
                            f"{product.name} variant is no longer available."
                        )

                        return redirect("my_orders")

                    available_stock = variant.stock

                # ---------------------------------------------
                # LEGACY PRODUCT WITHOUT VARIANT
                # ---------------------------------------------

                else:

                    variant = None
                    available_stock = product.stock

                # -------------------------------------------------
                # STOCK VALIDATION
                # -------------------------------------------------

                if available_stock < order_item.quantity:

                    messages.error(
                        request,
                        f"{product.name} does not have enough stock."
                    )

                    return redirect("my_orders")

                # -------------------------------------------------
                # STORE VALIDATED ITEM
                # -------------------------------------------------

                reorder_items.append(
                    (
                        product,
                        variant,
                        order_item.quantity
                    )
                )

            # -------------------------------------------------
            # ADD ITEMS TO CART
            # -------------------------------------------------

            for product, variant, quantity in reorder_items:

                cart_item, created = CartItem.objects.get_or_create(
                    cart=cart,
                    product=product,
                    variant=variant
                )

                if created:

                    cart_item.quantity = quantity

                else:

                    available_stock = (
                        variant.stock
                        if variant is not None
                        else product.stock
                    )

                    new_quantity = (
                        cart_item.quantity + quantity
                    )

                    if new_quantity > available_stock:

                        messages.error(
                            request,
                            f"{product.name} cannot be reordered because "
                            f"the cart quantity would exceed available stock."
                        )

                        return redirect("my_orders")

                    cart_item.quantity = new_quantity

                cart_item.save()

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        messages.success(
            request,
            "Previous order added to your cart successfully."
        )

        return redirect("cart")

    except Order.DoesNotExist:

        return redirect("my_orders")    



# =========================================================
# CANCEL ORDER
# =========================================================

def cancel_order(request, order_id):

    # Security: cancellation must be POST
    if request.method != "POST":
        return redirect("my_orders")

    # Session check
    if not request.session.session_key:
        return redirect("home")

    try:
        with transaction.atomic():

            # GET + LOCK CURRENT USER'S ORDER
            order = (
                Order.objects
                .select_for_update()
                .get(
                    id=order_id,
                    session_key=request.session.session_key
                )
            )

            # GET + LOCK PAYMENT
            payment = (
                Payment.objects
                .select_for_update()
                .get(order=order)
            )

            # =================================================
            # CANCELLATION STATUS RULE
            # =================================================

            # Cancellation is allowed ONLY before shipment
            allowed_cancel_statuses = [
                "Pending",
                "Confirmed",
                "Processing",
            ]

            if order.status not in allowed_cancel_statuses:
                return redirect(
                    "order_detail",
                    order_id=order.id
                )
                
            # ONLINE PAID ORDER
            # Refund integration is not implemented yet.
            if (
                payment.payment_method == "ONLINE"
                and payment.payment_status == "PAID"
            ):
                return redirect(
                    "order_detail",
                    order_id=order.id
                )

            # =================================================
            # RESTORE STOCK + CART
            # =================================================

            # Prevent double stock restoration
            if not payment.stock_released:

                _restore_order_stock_and_cart(order)

                payment.stock_released = True

                payment.save(
                    update_fields=[
                        "stock_released",
                        "updated_at",
                    ]
                )

            # =================================================
            # CANCEL ORDER
            # =================================================

            order.status = "Cancelled"

            if payment.payment_status == "FAILED":
                order.payment_status = "Failed"
            else:
                order.payment_status = "Pending"

            order.save(
                update_fields=[
                    "status",
                    "payment_status",
                ]
            )

            # =================================================
            # CLEAR STALE CHECKOUT STATE
            # =================================================

            # Clear checkout token if it belongs to this order
            if (
                str(request.session.get("checkout_token"))
                == str(order.checkout_token)
            ):
                request.session.pop(
                    "checkout_token",
                    None
                )

            # Clear retry-payment reference if it belongs
            # to this order
            if (
                request.session.get("retry_order_id")
                == order.id
            ):
                request.session.pop(
                    "retry_order_id",
                    None
                )

            request.session.modified = True

        return redirect(
            "order_detail",
            order_id=order.id
        )

    except Order.DoesNotExist:
        return redirect("my_orders")

    except Payment.DoesNotExist:
        return redirect("my_orders")

        
# =========================================================
# USER AUTHENTICATION & ACCOUNT
# =========================================================


# =========================================================
# ACCOUNT
# =========================================================

@login_required(login_url="/account/login/")
def account(request):
    user = request.user

    # User ke session se cart/wishlist identify karna
    session_key = request.session.session_key

    # Agar session available nahi hai to create karo
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    # Cart
    cart_obj = Cart.objects.filter(
        session_key=session_key
    ).first()

    cart_count = 0

    if cart_obj:
        cart_count = sum(
            item.quantity
            for item in cart_obj.items.all()
        )

    # Wishlist
    wishlist_obj = Wishlist.objects.filter(
        session_key=session_key
    ).first()

    wishlist_count = 0

    if wishlist_obj:
        wishlist_count = wishlist_obj.products.count()

    # Orders
    orders = Order.objects.filter(
        email__iexact=user.email
    ).order_by("-created_at")

    order_count = orders.count()

    # Recent orders
    recent_orders = orders[:5]

    context = {
        "user": user,
        "cart_count": cart_count,
        "wishlist_count": wishlist_count,
        "order_count": order_count,
        "recent_orders": recent_orders,
    }

    return render(
        request,
        "accounts/account.html",
        context
    )

# =========================================================
# REGISTER
# =========================================================

def register(request):

    # Already logged in
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":

        username = request.POST.get(
            "username",
            ""
        ).strip()

        email = request.POST.get(
            "email",
            ""
        ).strip().lower()

        password = request.POST.get(
            "password",
            ""
        )

        confirm_password = request.POST.get(
            "confirm_password",
            ""
        )

        # -------------------------------------------------
        # REQUIRED FIELDS
        # -------------------------------------------------

        if not all([
            username,
            email,
            password,
            confirm_password,
        ]):

            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Please fill in all fields.",
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # USERNAME VALIDATION
        # -------------------------------------------------

        if len(username) < 3:

            return render(
                request,
                "accounts/register.html",
                {
                    "error": (
                        "Username must contain at least "
                        "3 characters."
                    ),
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # EMAIL VALIDATION
        # -------------------------------------------------

        if "@" not in email or "." not in email:

            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Please enter a valid email address.",
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # USERNAME ALREADY EXISTS
        # -------------------------------------------------

        if User.objects.filter(
            username__iexact=username
        ).exists():

            return render(
                request,
                "accounts/register.html",
                {
                    "error": (
                        "This username is already taken."
                    ),
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # EMAIL ALREADY EXISTS
        # -------------------------------------------------

        if User.objects.filter(
            email__iexact=email
        ).exists():

            return render(
                request,
                "accounts/register.html",
                {
                    "error": (
                        "An account with this email "
                        "already exists."
                    ),
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # PASSWORD MATCH
        # -------------------------------------------------

        if password != confirm_password:

            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Passwords do not match.",
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # PASSWORD LENGTH
        # -------------------------------------------------

        if len(password) < 8:

            return render(
                request,
                "accounts/register.html",
                {
                    "error": (
                        "Password must contain at least "
                        "8 characters."
                    ),
                    "username": username,
                    "email": email,
                }
            )

        # -------------------------------------------------
        # CREATE USER
        # -------------------------------------------------

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        # -------------------------------------------------
        # LOGIN AFTER REGISTRATION
        # -------------------------------------------------

        login(
            request,
            user
        )

        return redirect("account")

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    return render(
        request,
        "accounts/register.html"
    )


# =========================================================
# LOGIN
# =========================================================

def user_login(request):

    # Already logged in
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":

        login_identifier = request.POST.get(
            "login_identifier",
            ""
        ).strip()

        password = request.POST.get(
            "password",
            ""
        )

        # -------------------------------------------------
        # REQUIRED FIELDS
        # -------------------------------------------------

        if not login_identifier or not password:

            return render(
                request,
                "accounts/login.html",
                {
                    "error": (
                        "Please enter your username/email "
                        "and password."
                    ),
                    "login_identifier": login_identifier,
                }
            )

        # -------------------------------------------------
        # ALLOW LOGIN USING EMAIL OR USERNAME
        # -------------------------------------------------

        username = login_identifier

        email_user = User.objects.filter(
            email__iexact=login_identifier
        ).first()

        if email_user:

            username = email_user.username

        # -------------------------------------------------
        # AUTHENTICATE
        # -------------------------------------------------

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is None:

            return render(
                request,
                "accounts/login.html",
                {
                    "error": (
                        "Invalid username/email or password."
                    ),
                    "login_identifier": login_identifier,
                }
            )

        # -------------------------------------------------
        # LOGIN
        # -------------------------------------------------

        login(
            request,
            user
        )

        # -------------------------------------------------
        # SAFE REDIRECT
        # -------------------------------------------------

        next_url = request.POST.get(
            "next"
        )

        if next_url and next_url.startswith("/"):

            return redirect(next_url)

        return redirect("account")

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    next_url = request.GET.get(
        "next",
        ""
    )

    return render(
        request,
        "accounts/login.html",
        {
            "next": next_url,
        }
    )


# =========================================================
# LOGOUT
# =========================================================

@login_required(login_url="/account/login/")
def user_logout(request):

    # Logout should happen through POST
    if request.method != "POST":

        return redirect("account")

    logout(request)

    return redirect("home")


# EDIT PROFILE
@login_required(login_url="/account/login/")
def edit_profile(request):
    user = request.user

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()

        # Basic validation
        if not username or not email:
            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                    "error": "Username and email are required.",
                    "username": username,
                    "email": email,
                },
            )

        if len(username) < 3:
            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                    "error": "Username must contain at least 3 characters.",
                    "username": username,
                    "email": email,
                },
            )

        if "@" not in email or "." not in email:
            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                    "error": "Please enter a valid email address.",
                    "username": username,
                    "email": email,
                },
            )

        # Username duplicate check
        username_exists = User.objects.filter(
            username__iexact=username
        ).exclude(pk=user.pk).exists()

        if username_exists:
            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                    "error": "This username is already taken.",
                    "username": username,
                    "email": email,
                },
            )

        # Email duplicate check
        email_exists = User.objects.filter(
            email__iexact=email
        ).exclude(pk=user.pk).exists()

        if email_exists:
            return render(
                request,
                "accounts/edit_profile.html",
                {
                    "user": user,
                    "error": "An account with this email already exists.",
                    "username": username,
                    "email": email,
                },
            )

        # Save changes
        user.username = username
        user.email = email
        user.save(update_fields=["username", "email"])

        return redirect("account")

    return render(
        request,
        "accounts/edit_profile.html",
        {
            "user": user,
        },
    )


@login_required(login_url="/account/login/")
def change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)

        if form.is_valid():
            user = form.save()

            # Password change ke baad current session logout na ho
            update_session_auth_hash(request, user)

            return redirect("account")

    else:
        form = PasswordChangeForm(request.user)

    return render(
        request,
        "accounts/change_password.html",
        {
            "form": form,
        },
    )



@login_required(login_url="/account/login/")
def address_book(request):
    addresses = Address.objects.filter(
        user=request.user
    ).order_by("-is_default", "-created_at")

    return render(
        request,
        "accounts/address_book.html",
        {
            "addresses": addresses,
            "form_data": {},
        },
    )



@login_required(login_url="/account/login/")
def add_address(request):
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        address_line = request.POST.get("address_line", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        landmark = request.POST.get("landmark", "").strip()

        addresses = Address.objects.filter(
            user=request.user
        ).order_by("-is_default", "-created_at")

        if not all([
            full_name,
            phone,
            address_line,
            city,
            state,
            pincode,
        ]):
            return render(
                request,
                "accounts/address_book.html",
                {
                    "error": "Please fill in all required fields.",
                    "form_data": request.POST,
                    "addresses": addresses,
                },
            )

        if len(phone) < 10:
            return render(
                request,
                "accounts/address_book.html",
                {
                    "error": "Please enter a valid phone number.",
                    "form_data": request.POST,
                    "addresses": addresses,
                },
            )

        if len(pincode) != 6 or not pincode.isdigit():
            return render(
                request,
                "accounts/address_book.html",
                {
                    "error": "Please enter a valid 6-digit pincode.",
                    "form_data": request.POST,
                    "addresses": addresses,
                },
            )

        address_count = Address.objects.filter(
            user=request.user
        ).count()

        Address.objects.create(
            user=request.user,
            full_name=full_name,
            phone=phone,
            address_line=address_line,
            city=city,
            state=state,
            pincode=pincode,
            landmark=landmark,
            is_default=(address_count == 0),
        )

        return redirect("address_book")

    addresses = Address.objects.filter(
        user=request.user
    ).order_by("-is_default", "-created_at")

    return render(
        request,
        "accounts/address_book.html",
        {
            "form_data": {},
            "addresses": addresses,
        },
    )


@login_required(login_url="/account/login/")
def set_default_address(request, address_id):
    if request.method == "POST":
        address = Address.objects.filter(
            id=address_id,
            user=request.user
        ).first()

        if address:
            Address.objects.filter(
                user=request.user
            ).update(is_default=False)

            address.is_default = True
            address.save(update_fields=["is_default"])

    return redirect("address_book")


@login_required(login_url="/account/login/")
def delete_address(request, address_id):
    if request.method == "POST":
        address = Address.objects.filter(
            id=address_id,
            user=request.user
        ).first()

        if address:
            was_default = address.is_default
            address.delete()

            # If the deleted address was the default,
            # automatically make the newest remaining address default.
            if was_default:
                next_address = Address.objects.filter(
                    user=request.user
                ).order_by("-created_at").first()

                if next_address:
                    next_address.is_default = True
                    next_address.save(update_fields=["is_default"])

    return redirect("address_book")


@login_required(login_url="/account/login/")
def edit_address(request, address_id):
    address = Address.objects.filter(
        id=address_id,
        user=request.user
    ).first()

    if not address:
        return redirect("address_book")

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        address_line = request.POST.get("address_line", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        landmark = request.POST.get("landmark", "").strip()

        if not all([
            full_name,
            phone,
            address_line,
            city,
            state,
            pincode,
        ]):
            return render(
                request,
                "accounts/edit_address.html",
                {
                    "address": address,
                    "error": "Please fill in all required fields.",
                },
            )

        if len(phone) < 10:
            return render(
                request,
                "accounts/edit_address.html",
                {
                    "address": address,
                    "error": "Please enter a valid phone number.",
                },
            )

        if len(pincode) != 6 or not pincode.isdigit():
            return render(
                request,
                "accounts/edit_address.html",
                {
                    "address": address,
                    "error": "Please enter a valid 6-digit pincode.",
                },
            )

        address.full_name = full_name
        address.phone = phone
        address.address_line = address_line
        address.city = city
        address.state = state
        address.pincode = pincode
        address.landmark = landmark

        address.save()

        return redirect("address_book")

    return render(
        request,
        "accounts/edit_address.html",
        {
            "address": address,
        },
    )


def download_invoice(request, order_id):
    if not request.session.session_key:
        return redirect("home")

    order = get_object_or_404(
        Order.objects.select_related(
            "payment",
            "coupon",
        ).prefetch_related(
            "items__product",
            "items__variant",
        ),
        id=order_id,
        session_key=request.session.session_key,
    )

    return invoice_pdf_response(order)
