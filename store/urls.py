from django.urls import path
from . import views


urlpatterns = [

    # =========================================================
    # HOME
    # =========================================================

    path(
        "",
        views.home,
        name="home"
    ),


    # =========================================================
    # PRODUCT
    # =========================================================

    path(
        "product/<int:pk>/",
        views.product_detail,
        name="product_detail"
    ),


    path(
        "product/<int:pk>/review/",
        views.submit_review,
        name="submit_review"
    ),


    # =========================================================
    # CART
    # =========================================================

    path(
        "add-to-cart/<int:pk>/",
        views.add_to_cart,
        name="add_to_cart"
    ),

    path(
        "cart/",
        views.cart,
        name="cart"
    ),

    path(
        "cart/update/<int:item_id>/",
        views.update_cart_quantity,
        name="update_cart_quantity"
    ),

    path(
        "cart/remove/<int:item_id>/",
        views.remove_from_cart,
        name="remove_from_cart"
    ),

    path(
        "cart/apply-coupon/",
        views.apply_coupon,
        name="apply_coupon"
    ),


    # =========================================================
    # WISHLIST
    # =========================================================

    path(
        "wishlist/toggle/<int:pk>/",
        views.toggle_wishlist,
        name="toggle_wishlist"
    ),

    path(
        "wishlist/",
        views.wishlist,
        name="wishlist"
    ),


    # =========================================================
    # CHECKOUT
    # =========================================================

    path(
        "checkout/",
        views.checkout,
        name="checkout"
    ),


    # =========================================================
    # PAYMENT
    # =========================================================

    path(
        "payment/verify/",
        views.verify_payment,
        name="verify_payment"
    ),

    path(
        "payment/failed/",
        views.mark_payment_failed,
        name="mark_payment_failed"
    ),

    path(
        "payment/webhook/",
        views.razorpay_webhook,
        name="razorpay_webhook"
    ),


    # =========================================================
    # ORDERS
    # =========================================================

    path(
        "order/<int:order_id>/retry-payment/",
        views.retry_payment,
        name="retry_payment"
    ),

    path(
        "order/<int:order_id>/cancel/",
        views.cancel_order,
        name="cancel_order"
    ),


    path(
        "order-success/<int:order_id>/",
        views.order_success,
        name="order_success"
    ),

    path(
        "my-orders/",
        views.my_orders,
        name="my_orders"
    ),

    path(
        "order/<int:order_id>/",
        views.order_detail,
        name="order_detail"
    ),


    # =========================================================
    # ACCOUNT / AUTHENTICATION
    # =========================================================

    path(
        "account/",
        views.account,
        name="account"
    ),

    path("account/edit-profile/",
        views.edit_profile,
        name="edit_profile"   
    ),

    path("account/change-password/",
        views.change_password,
        name="change_password"
    ),

    path("account/addresses/",
        views.address_book,
        name="address_book"
      ),

    path(
        "account/addresses/add/",
        views.add_address,
        name="add_address"
    ),

    path(
        "account/addresses/<int:address_id>/edit/",
        views.edit_address,
        name="edit_address",
    ),
    path(
        "account/addresses/<int:address_id>/default/",
        views.set_default_address,
        name="set_default_address",
    ),
    path(
        "account/addresses/<int:address_id>/delete/",
        views.delete_address,
        name="delete_address",
    ),

    path(
        "account/register/",
        views.register,
        name="register"
    ),

    path(
        "account/login/",
        views.user_login,
        name="user_login"
    ),

    path(
        "account/logout/",
        views.user_logout,
        name="user_logout"
    ),

]