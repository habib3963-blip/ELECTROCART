from django.db import models
import uuid
from django.contrib.auth.models import User


# =========================================================
# CATEGORY
# =========================================================

class Category(models.Model):

    name = models.CharField(
        max_length=100,
        unique=True
    )

    description = models.TextField(
        blank=True
    )

    def __str__(self):
        return self.name


# =========================================================
# PRODUCT
# =========================================================

class Product(models.Model):

    BADGE_CHOICES = [
        ("Best Seller", "Best Seller"),
        ("Hot Deal", "Hot Deal"),
        ("New", "New"),
        ("Futuristic", "Futuristic"),
        ("Popular", "Popular"),
    ]

    name = models.CharField(
        max_length=200
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="products"
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        default=0.0
    )

    reviews = models.PositiveIntegerField(
        default=0
    )

    image = models.URLField(
        max_length=500,
        blank=True
    )

    badge = models.CharField(
        max_length=50,
        choices=BADGE_CHOICES,
        default="New"
    )

    description = models.TextField()

    stock = models.PositiveIntegerField(
        default=0
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


# =========================================================
# PRODUCT IMAGE
# =========================================================

class ProductImage(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images"
    )

    # External image URL (optional)
    image_url = models.URLField(
        max_length=500,
        blank=True
    )

    # Local uploaded image (optional)
    image_file = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True
    )

    alt_text = models.CharField(
        max_length=255,
        blank=True
    )

    is_primary = models.BooleanField(
        default=False
    )

    sort_order = models.PositiveIntegerField(
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = (
            "sort_order",
            "id",
        )

    def clean(self):
        from django.core.exceptions import ValidationError

        if not self.image_url and not self.image_file:
            raise ValidationError(
                "Provide either an Image URL or upload an Image File."
            )

    def __str__(self):
        return f"{self.product.name} - Image {self.id}"


# =========================================================
# PRODUCT VARIANT
# =========================================================

class ProductVariant(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants"
    )

    # Unique Stock Keeping Unit
    sku = models.CharField(
        max_length=100,
        unique=True
    )

    # Common variant options
    # Example: Black, Blue, White
    color = models.CharField(
        max_length=100,
        blank=True
    )

    # Example: 128GB, 256GB, 512GB
    storage = models.CharField(
        max_length=100,
        blank=True
    )

    # Extra options for future products
    # Example:
    # {
    #     "RAM": "16GB",
    #     "Processor": "Core i7"
    # }
    attributes = models.JSONField(
        default=dict,
        blank=True
    )

    # Variant-specific price
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # Variant-specific stock
    stock = models.PositiveIntegerField(
        default=0
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):

        options = []

        if self.color:
            options.append(self.color)

        if self.storage:
            options.append(self.storage)

        if options:
            return f"{self.product.name} - {' / '.join(options)}"

        return f"{self.product.name} - {self.sku}"


# =========================================================
# WISHLIST
# =========================================================

class Wishlist(models.Model):

    session_key = models.CharField(
        max_length=100,
        unique=True
    )

    products = models.ManyToManyField(
        Product,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Wishlist - {self.session_key}"


# =========================================================
# CART
# =========================================================

class Cart(models.Model):

    session_key = models.CharField(
        max_length=100,
        unique=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Cart - {self.session_key}"


# =========================================================
# CART ITEM
# =========================================================

class CartItem(models.Model):

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items"
    )

    # Kept for backward compatibility with existing cart data
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )

    # New variant relationship
    # Nullable so existing cart items continue to work
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="cart_items",
        null=True,
        blank=True
    )

    quantity = models.PositiveIntegerField(
        default=1
    )

    added_at = models.DateTimeField(
        auto_now_add=True
    )

    @property
    def total_price(self):

        if self.variant:
            return self.variant.price * self.quantity

        return self.product.price * self.quantity

    def __str__(self):

        if self.variant:
            return f"{self.variant} x {self.quantity}"

        return f"{self.product.name} x {self.quantity}"


# =========================================================
# ORDER
# =========================================================

class Order(models.Model):

    STATUS_CHOICES = [
        ("Pending", "Order Placed"),
        ("Confirmed", "Confirmed"),
        ("Processing", "Processing"),
        ("Shipped", "Shipped"),
        ("Out for Delivery", "Out for Delivery"),
        ("Delivered", "Delivered"),
        ("Cancelled", "Cancelled"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("COD", "Cash on Delivery"),
        ("ONLINE", "Online Payment"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Paid", "Paid"),
        ("Failed", "Failed"),
        ("Refunded", "Refunded"),
    ]

    session_key = models.CharField(
        max_length=100
    )

    user = models.ForeignKey(
    User,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="orders"
)

    checkout_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    customer_name = models.CharField(
        max_length=150
    )

    email = models.EmailField()

    phone = models.CharField(
        max_length=20
    )

    address = models.TextField()

    city = models.CharField(
        max_length=100
    )

    state = models.CharField(
        max_length=100
    )

    pincode = models.CharField(
        max_length=10
    )

    tracking_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    coupon = models.ForeignKey(
        "Coupon",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )

    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default="COD"
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="Pending"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def clean(self):

        from django.core.exceptions import ValidationError

        if not self.pk:
            return

        try:
            old_order = Order.objects.get(pk=self.pk)
        except Order.DoesNotExist:
            return

        if old_order.status == self.status:
            return

        allowed_transitions = {
            "Pending": ["Confirmed", "Cancelled"],
            "Confirmed": ["Processing", "Cancelled"],
            "Processing": ["Shipped", "Cancelled"],
            "Shipped": ["Out for Delivery"],
            "Out for Delivery": ["Delivered"],
            "Delivered": [],
            "Cancelled": [],
        }

        allowed = allowed_transitions.get(
            old_order.status,
            []
        )

        if self.status not in allowed:

            raise ValidationError({
                "status": (
                    f"Invalid status change: "
                    f"{old_order.get_status_display()} → "
                    f"{self.get_status_display()}"
                )
            })

    def __str__(self):
        return f"Order #{self.id} - {self.customer_name}"


# =========================================================
# ORDER ITEM
# =========================================================

class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )

    # Original product reference
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT
    )

    # New variant reference
    # Nullable for existing orders
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name="order_items",
        null=True,
        blank=True
    )

    quantity = models.PositiveIntegerField(
        default=1
    )

    # Snapshot of price at the time of purchase
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    def __str__(self):

        if self.variant:
            return f"{self.variant} x {self.quantity}"

        return f"{self.product.name} x {self.quantity}"

    @property
    def total_price(self):
        return self.price * self.quantity



# =========================================================
# REVIEW & RATING
# =========================================================

class Review(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews_list"
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="product_reviews"
    )

    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name="review",
        null=True,
        blank=True
    )

    rating = models.PositiveSmallIntegerField()

    title = models.CharField(
        max_length=150,
        blank=True
    )

    comment = models.TextField(
        blank=True
    )

    is_approved = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "order_item"],
                name="unique_user_order_item_review"
            )
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.rating < 1 or self.rating > 5:
            raise ValidationError(
                {"rating": "Rating must be between 1 and 5."}
            )

        if self.order_item:
            if self.order_item.product_id != self.product_id:
                raise ValidationError(
                    "This order item does not belong to this product."
                )

            if self.order_item.order.user_id != self.user_id:
                raise ValidationError(
                    "You can only review your own purchased product."
                )

    def __str__(self):
        return (
            f"{self.product.name} - "
            f"{self.user.username} - "
            f"{self.rating}/5"
        )


# =========================================================
# COUPON
# =========================================================



class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ("PERCENT", "Percentage"),
        ("FIXED", "Fixed Amount"),
    ]

    code = models.CharField(
        max_length=50,
        unique=True
    )

    discount_type = models.CharField(
        max_length=10,
        choices=DISCOUNT_TYPE_CHOICES,
        default="PERCENT"
    )

    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    minimum_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    maximum_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    valid_from = models.DateTimeField()

    valid_until = models.DateTimeField()

    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    used_count = models.PositiveIntegerField(
        default=0
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.code


# =========================================================
# PAYMENT
# =========================================================

class Payment(models.Model):

    PAYMENT_METHOD_CHOICES = [
        ("COD", "Cash on Delivery"),
        ("ONLINE", "Online Payment"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("REFUNDED", "Refunded"),
    ]

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="payment"
    )

    razorpay_order_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True
    )

    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True
    )

    razorpay_signature = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="PENDING"
    )

    # Prevents stock from being released more than once
    stock_released = models.BooleanField(
        default=False
    )

    transaction_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        unique=True
    )

    paid_at = models.DateTimeField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"Payment - Order #{self.order.id}"


# =========================================================
# ADDRESS
# =========================================================

class Address(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="addresses"
    )

    full_name = models.CharField(
        max_length=150
    )

    phone = models.CharField(
        max_length=20
    )

    address_line = models.TextField()

    city = models.CharField(
        max_length=100
    )

    state = models.CharField(
        max_length=100
    )

    pincode = models.CharField(
        max_length=10
    )

    landmark = models.CharField(
        max_length=150,
        blank=True
    )

    is_default = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.full_name} - {self.city}"