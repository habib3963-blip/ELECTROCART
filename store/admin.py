from django.contrib import admin
from django import forms


from .models import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
    ProductOffer,
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


# =========================================================
# CATEGORY ADMIN
# =========================================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "name",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "name",
    )


# =========================================================
# PRODUCT VARIANT INLINE
# =========================================================

class ProductVariantInline(admin.TabularInline):

    model = ProductVariant

    extra = 1

    fields = (
        "sku",
        "color",
        "storage",
        "attributes",
        "price",
        "stock",
        "is_active",
    )

    ordering = (
        "color",
        "storage",
        "price",
    )


# =========================================================
# PRODUCT IMAGE INLINE
# =========================================================

class ProductImageInline(admin.TabularInline):

    model = ProductImage

    extra = 1

    fields = (
        "image_url",
        "image_file",
        "alt_text",
        "is_primary",
        "sort_order",
    )

    ordering = (
        "sort_order",
        "id",
    )


# =========================================================
# PRODUCT ADMIN
# =========================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "category",
        "price",
        "rating",
        "reviews",
        "stock",
        "badge",
        "is_active",
    )

    list_filter = (
        "category",
        "badge",
        "is_active",
    )

    search_fields = (
        "name",
        "description",
    )

    list_editable = (
        "price",
        "stock",
        "is_active",
    )

    ordering = (
        "-created_at",
    )

    # Product ke andar variants manage kar sakte hain
    inlines = (
        ProductVariantInline,
        ProductImageInline,
    )


# =========================================================
# PRODUCT VARIANT ADMIN
# =========================================================

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "product",
        "sku",
        "color",
        "storage",
        "price",
        "stock",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "color",
        "storage",
        "product__category",
    )

    search_fields = (
        "sku",
        "product__name",
        "color",
        "storage",
    )

    list_editable = (
        "price",
        "stock",
        "is_active",
    )

    ordering = (
        "product__name",
        "color",
        "storage",
        "price",
    )

    fieldsets = (
        (
            "Variant Information",
            {
                "fields": (
                    "product",
                    "sku",
                    "color",
                    "storage",
                    "attributes",
                )
            },
        ),

        (
            "Pricing & Inventory",
            {
                "fields": (
                    "price",
                    "stock",
                    "is_active",
                )
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


# =========================================================
# PRODUCT IMAGE ADMIN
# =========================================================

@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "product",
        "image_url",
        "image_file",
        "is_primary",
        "sort_order",
        "created_at",
    )

    list_filter = (
        "is_primary",
        "product__category",
    )

    search_fields = (
        "product__name",
        "alt_text",
        "image_url",
        "image_file",
    )

    list_editable = (
        "is_primary",
        "sort_order",
    )

    ordering = (
        "product__name",
        "sort_order",
        "id",
    )

    fieldsets = (
        (
            "Image Information",
            {
                "fields": (
                    "product",
                    "image_url",
                    "image_file",
                    "alt_text",
                    "is_primary",
                    "sort_order",
                )
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


# =========================================================
# CART ADMIN
# =========================================================

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "session_key",
        "created_at",
    )

    search_fields = (
        "session_key",
    )

    ordering = (
        "-created_at",
    )


# =========================================================
# CART ITEM ADMIN
# =========================================================

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "cart",
        "product",
        "variant",
        "quantity",
        "added_at",
    )

    list_filter = (
        "product",
        "variant",
    )

    search_fields = (
        "product__name",
        "variant__sku",
        "variant__color",
        "variant__storage",
        "cart__session_key",
    )

    ordering = (
        "-added_at",
    )


# =========================================================
# WISHLIST ADMIN
# =========================================================

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "session_key",
        "created_at",
    )

    search_fields = (
        "session_key",
    )

    ordering = (
        "-created_at",
    )


# =========================================================
# ORDER ADMIN FORM
# =========================================================

class OrderAdminForm(forms.ModelForm):

    class Meta:
        model = Order
        fields = "__all__"

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # New order
        if not self.instance or not self.instance.pk:
            return

        current_status = self.instance.status

        allowed_transitions = {
            "Pending": [
                "Confirmed",
                "Cancelled",
            ],

            "Confirmed": [
                "Processing",
                "Cancelled",
            ],

            "Processing": [
                "Shipped",
                "Cancelled",
            ],

            "Shipped": [
                "Out for Delivery",
            ],

            "Out for Delivery": [
                "Delivered",
            ],

            "Delivered": [],

            "Cancelled": [],
        }

        next_statuses = allowed_transitions.get(
            current_status,
            []
        )

        # Current status should remain selectable
        available_statuses = [
            current_status,
            *next_statuses,
        ]

        # Remove duplicates
        available_statuses = list(
            dict.fromkeys(available_statuses)
        )

        self.fields["status"].choices = [
            choice
            for choice in Order.STATUS_CHOICES
            if choice[0] in available_statuses
        ]


# =========================================================
# ORDER ADMIN
# =========================================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    # Use custom status form
    form = OrderAdminForm

    # -----------------------------------------------------
    # ORDER LIST
    # -----------------------------------------------------

    list_display = (
        "id",
        "customer_name",
        "email",
        "phone",
        "total_amount",
        "status",
        "tracking_id",
        "awb_number",
        "payment_method",
        "payment_status",
        "created_at",
    )

    # -----------------------------------------------------
    # FILTERS
    # -----------------------------------------------------

    list_filter = (
        "status",
        "payment_method",
        "payment_status",
        "created_at",
    )

    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    search_fields = (
        "customer_name",
        "email",
        "phone",
        "session_key",
        "tracking_id",
        "shiprocket_order_id",
        "shiprocket_shipment_id",
        "awb_number",
    )

    # -----------------------------------------------------
    # STATUS CAN BE CHANGED FROM ORDER LIST
    # PAYMENT STATUS REMAINS BACKEND CONTROLLED
    # -----------------------------------------------------

    list_editable = (
        "status",
    )

    # -----------------------------------------------------
    # DEFAULT ORDER
    # -----------------------------------------------------

    ordering = (
        "-created_at",
    )

    # -----------------------------------------------------
    # READ-ONLY SYSTEM / PAYMENT FIELDS
    # -----------------------------------------------------

    readonly_fields = (
        "id",
        "checkout_token",
        "session_key",
        "total_amount",
        "payment_method",
        "payment_status",
        "created_at",
    )

    # -----------------------------------------------------
    # ORDER DETAIL PAGE
    # -----------------------------------------------------

    fieldsets = (
        (
            "Order Information",
            {
                "fields": (
                    "id",
                    "user",
                    "customer_name",
                    "email",
                    "phone",
                    "status",
                    "tracking_id",
                    "shiprocket_order_id",
                    "shiprocket_shipment_id",
                    "courier_name",
                    "awb_number",
                )
            },
        ),

        (
            "Delivery Address",
            {
                "fields": (
                    "address",
                    "city",
                    "state",
                    "pincode",
                )
            },
        ),

        (
            "Payment",
            {
                "fields": (
                    "total_amount",
                    "payment_method",
                    "payment_status",
                )
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "checkout_token",
                    "session_key",
                    "created_at",
                )
            },
        ),
    )

    # -----------------------------------------------------
    # AUTO-GENERATE TRACKING ID WHEN ORDER IS SHIPPED
    # -----------------------------------------------------

    def save_model(self, request, obj, form, change):
        if obj.status == "Shipped" and not obj.tracking_id:
            obj.tracking_id = f"EC-{obj.id:06d}"

        super().save_model(request, obj, form, change)



# =========================================================
# ORDER ITEM ADMIN
# =========================================================

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "order",
        "product",
        "variant",
        "quantity",
        "price",
        "total_price",
    )

    list_filter = (
        "product",
        "variant",
    )

    search_fields = (
        "order__customer_name",
        "order__email",
        "product__name",
        "variant__sku",
        "variant__color",
        "variant__storage",
    )

    ordering = (
        "-id",
    )


# =========================================================
# PAYMENT ADMIN
# =========================================================

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "order",
        "payment_method",
        "payment_status",
        "transaction_id",
        "paid_at",
        "created_at",
    )

    list_filter = (
        "payment_method",
        "payment_status",
        "created_at",
    )

    search_fields = (
        "order__customer_name",
        "order__email",
        "transaction_id",
    )

    readonly_fields = (
        "order",
        "payment_method",
        "payment_status",
        "transaction_id",
        "paid_at",
        "created_at",
        "updated_at",
        "stock_released",
        "razorpay_order_id",
    )

    ordering = (
        "-created_at",  
    )



# =========================================================
# REVIEW & RATING ADMIN
# =========================================================

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "product",
        "user",
        "order_item",
        "rating",
        "title",
        "is_approved",
        "created_at",
    )

    list_filter = (
        "rating",
        "is_approved",
        "created_at",
        "product__category",
    )

    search_fields = (
        "product__name",
        "user__username",
        "user__email",
        "title",
        "comment",
        "order_item__order__id",
    )

    list_editable = (
        "is_approved",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Review Information",
            {
                "fields": (
                    "product",
                    "user",
                    "order_item",
                    "rating",
                    "title",
                    "comment",
                )
            },
        ),
        (
            "Moderation",
            {
                "fields": (
                    "is_approved",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "discount_value",
        "minimum_order_amount",
        "valid_from",
        "valid_until",
        "usage_limit",
        "used_count",
        "is_active",
    )

    list_filter = (
        "discount_type",
        "is_active",
    )

    search_fields = (
        "code",
    )

    ordering = (
        "-created_at",
    )


@admin.register(ProductOffer)
class ProductOfferAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "product",
        "discount_type",
        "discount_value",
        "valid_from",
        "valid_until",
        "is_active",
    )

    list_filter = (
        "discount_type",
        "is_active",
    )

    search_fields = (
        "name",
        "product__name",
    )

    ordering = (
        "-created_at",
    )


