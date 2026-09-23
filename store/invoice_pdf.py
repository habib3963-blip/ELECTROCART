
from decimal import Decimal
from io import BytesIO
from urllib.request import urlopen
from pathlib import Path

from django.http import HttpResponse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
import qrcode


PAGE_W, PAGE_H = A4

# ============================================================
# ELECTROCART — INVOICE V4
# Fixed-grid / canvas architecture.
#
# Why canvas instead of Platypus?
# The approved design is a highly art-directed one-page layout.
# Fixed coordinates give us predictable spacing, rounded cards,
# hero proportions, and no KeepTogether/Spacer layout failures.
# ============================================================

NAVY = colors.HexColor("#07101F")
NAVY_2 = colors.HexColor("#101B31")
NAVY_3 = colors.HexColor("#152447")
INDIGO = colors.HexColor("#5865F2")
INDIGO_2 = colors.HexColor("#6B78FF")
INDIGO_LIGHT = colors.HexColor("#EEF0FF")
TEXT = colors.HexColor("#101828")
MUTED = colors.HexColor("#667085")
LIGHT = colors.HexColor("#98A2B3")
BORDER = colors.HexColor("#E4E7EC")
CARD = colors.HexColor("#F8F9FC")
WHITE = colors.white
GREEN = colors.HexColor("#079455")
GREEN_BG = colors.HexColor("#ECFDF3")
GREEN_BORDER = colors.HexColor("#ABEFC6")
BLACK = colors.HexColor("#05070C")


# ============================================================
# ELECTROCART — UNICODE / INDIAN RUPEE FONT
# ============================================================
# Helvetica does not contain U+20B9 (₹).  We therefore use the
# bundled DejaVu Sans fonts whenever a string contains Unicode.
# The paths are intentionally fixed to store/fonts so a missing
# font cannot silently fall back to Helvetica and produce squares.

BASE_DIR = Path(__file__).resolve().parent
FONT_DIR = BASE_DIR / "fonts"
UNICODE_FONT = FONT_DIR / "DejaVuSans.ttf"
UNICODE_BOLD_FONT = FONT_DIR / "DejaVuSans-Bold.ttf"

if not UNICODE_FONT.exists():
    raise FileNotFoundError(
        f"Missing invoice font: {UNICODE_FONT}"
    )

if not UNICODE_BOLD_FONT.exists():
    raise FileNotFoundError(
        f"Missing invoice font: {UNICODE_BOLD_FONT}"
    )

pdfmetrics.registerFont(
    TTFont("ECUnicode", str(UNICODE_FONT))
)
pdfmetrics.registerFont(
    TTFont("ECUnicodeBold", str(UNICODE_BOLD_FONT))
)

UNICODE_REGULAR = "ECUnicode"
UNICODE_BOLD = "ECUnicodeBold"


def _font_for_text(value, requested_font="Helvetica"):
    value = "" if value is None else str(value)

    # Force DejaVu for every non-ASCII character, including ₹.
    if any(ord(ch) > 127 for ch in value):
        if "Bold" in requested_font:
            return UNICODE_BOLD
        return UNICODE_REGULAR

    return requested_font


def money(value):
    try:
        return f"\u20b9{Decimal(value or 0):,.2f}"
    except Exception:
        return "\u20b90.00"


def safe(value, fallback="—"):
    if value is None:
        return fallback
    value = str(value).strip()
    return value or fallback


def image_source(item):
    product = item.product

    try:
        if product.image:
            return str(product.image)
    except Exception:
        pass

    try:
        images = product.images.all().order_by("-is_primary", "sort_order", "id")
    except Exception:
        images = []

    for obj in images:
        try:
            if obj.image_url:
                return str(obj.image_url)
        except Exception:
            pass
        try:
            if obj.image_file:
                return obj.image_file.path
        except Exception:
            pass

    return None


def load_image(source):
    if not source:
        return None
    try:
        if str(source).startswith(("http://", "https://")):
            raw = urlopen(source, timeout=4).read()
            return ImageReader(BytesIO(raw))
        return ImageReader(source)
    except Exception:
        return None


def draw_contain(c, image, x, y, w, h, bg=None, radius=8):
    if bg is not None:
        c.setFillColor(bg)
        c.roundRect(x, y, w, h, radius, fill=1, stroke=0)

    if not image:
        return

    try:
        iw, ih = image.getSize()
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(
            image,
            x + (w - dw) / 2,
            y + (h - dh) / 2,
            width=dw,
            height=dh,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        pass


def rounded_card(c, x, y, w, h, fill=CARD, stroke=BORDER, radius=9, line=0.6):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def text(c, value, x, y, size=8, color=TEXT, font="Helvetica"):
    value = safe(value, "")
    actual_font = _font_for_text(value, font)
    c.setFont(actual_font, size)
    c.setFillColor(color)
    c.drawString(x, y, value)


def text_right(c, value, x, y, size=8, color=TEXT, font="Helvetica"):
    value = safe(value, "")
    actual_font = _font_for_text(value, font)
    c.setFont(actual_font, size)
    c.setFillColor(color)
    c.drawRightString(x, y, value)


def text_center(c, value, x, y, size=8, color=TEXT, font="Helvetica"):
    value = safe(value, "")
    actual_font = _font_for_text(value, font)
    c.setFont(actual_font, size)
    c.setFillColor(color)
    c.drawCentredString(x, y, value)


def fit_text(c, value, x, y, max_width, size=8, color=TEXT, font="Helvetica"):
    value = safe(value, "")
    actual_font = _font_for_text(value, font)
    current = size
    while current > 5 and stringWidth(value, actual_font, current) > max_width:
        current -= 0.25
    c.setFont(actual_font, current)
    c.setFillColor(color)
    c.drawString(x, y, value)


def wrap_lines(c, value, max_width, font="Helvetica", size=8, max_lines=2):
    value = safe(value, "")
    words = value.split()
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else current + " " + word
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break

    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        lines = [""]

    # Ellipsis only if content still remains.
    joined = " ".join(lines)
    if joined != value and lines:
        last = lines[-1]
        while last and stringWidth(last + "…", font, size) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"

    return lines[:max_lines]


def draw_wrapped(c, value, x, y, max_width, size=8, leading=10, color=TEXT,
                 font="Helvetica", max_lines=2):
    lines = wrap_lines(c, value, max_width, font, size, max_lines)
    for i, line in enumerate(lines):
        text(c, line, x, y - i * leading, size, color, font)
    return len(lines)


def draw_icon_circle(c, x, y, label, accent=INDIGO, radius=16):
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#C9CEFF"))
    c.setLineWidth(0.8)
    c.circle(x, y, radius, fill=1, stroke=1)
    text_center(c, label, x, y - 4, 12, accent, "Helvetica-Bold")


def draw_feature(c, x, y, icon, title, subtitle):
    draw_icon_circle(c, x + 10, y + 8, icon, WHITE, 10)
    text(c, title, x + 25, y + 11, 6.2, WHITE, "Helvetica-Bold")
    text(c, subtitle, x + 25, y + 2, 5.4, colors.HexColor("#BFC8DB"))


def draw_header(c):
    x, y, w, h = 18, PAGE_H - 18 - 68, PAGE_W - 36, 68

    # Clean premium header background.
    c.setFillColor(NAVY)
    c.roundRect(x, y, w, h, 7, fill=1, stroke=0)

    # Subtle right-side geometry.
    c.setFillColor(colors.HexColor("#101F3E"))
    c.rect(x + w - 128, y, 62, h, fill=1, stroke=0)

    c.setFillColor(colors.HexColor("#152A54"))
    c.rect(x + w - 68, y, 50, h, fill=1, stroke=0)

    c.setStrokeColor(colors.HexColor("#5865F2"))
    c.setLineWidth(0.8)
    c.line(x + w - 86, y, x + w - 44, y + h)

    # Brand.
    text(
        c,
        "ELECTRO",
        x + 13,
        y + 39,
        20,
        WHITE,
        "Helvetica-Bold",
    )

    text(
        c,
        "CART",
        x + 104,
        y + 39,
        20,
        INDIGO_2,
        "Helvetica-Bold",
    )

    text(
        c,
        "P R E M I U M   E L E C T R O N I C S   S T O R E",
        x + 14,
        y + 25,
        5.2,
        colors.HexColor("#D5DCEE"),
        "Helvetica",
    )

    # Simple feature line — no oversized circles.
    features = [
        ("✦", "Latest Technology"),
        ("◇", "100% Genuine"),
        ("◆", "Secure Payments"),
        ("▣", "Fast Delivery"),
    ]

    feature_x = x + 14
    feature_y = y + 8

    for i, (icon, label) in enumerate(features):
        if i > 0:
            c.setStrokeColor(colors.HexColor("#293A59"))
            c.setLineWidth(0.5)
            c.line(
                feature_x - 9,
                feature_y - 1,
                feature_x - 9,
                feature_y + 12,
            )

        text(c, icon, feature_x, feature_y + 1, 6.5, INDIGO_2, "Helvetica-Bold")
        fit_text(
            c,
            label,
            feature_x + 10,
            feature_y + 1,
            66,
            5.0,
            colors.HexColor("#C9D2E5"),
            "Helvetica",
        )

        feature_x += 88

    # Small fixed brand statement on the right.
    text_center(
        c,
        "ELECTROCART",
        x + w - 43,
        y + 40,
        6.0,
        WHITE,
        "Helvetica-Bold",
    )
    text_center(
        c,
        "SMARTER",
        x + w - 43,
        y + 28,
        5.2,
        colors.HexColor("#C8D2E8"),
        "Helvetica",
    )
    text_center(
        c,
        "TECH",
        x + w - 43,
        y + 18,
        6.0,
        INDIGO_2,
        "Helvetica-Bold",
    )


def draw_top_info(c, order):
    top = PAGE_H - 111
    left = 27
    title_w = 180
    mid_x = 214
    mid_w = 160
    store_x = 380
    store_w = PAGE_W - 27 - store_x

    text(c, "INVOICE", left, top - 1, 33, BLACK, "Helvetica-Bold")
    c.setFillColor(INDIGO)
    c.rect(left, top - 13, 20, 2, fill=1, stroke=0)
    text(c, "M O R E   T H A N   A   P U R C H A S E.",
         left, top - 28, 5.5, MUTED, "Helvetica")
    text(c, "A   S M A R T E R   T O M O R R O W",
         left, top - 37, 5.5, MUTED, "Helvetica")

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.8)
    c.line(mid_x - 10, top + 4, mid_x - 10, top - 72)

    oid = f"ORDER #EC-{int(order.id)}"
    text(c, oid, mid_x, top - 1, 13, TEXT, "Helvetica-Bold")

    status = safe(getattr(order, "status", None)).replace("_", " ").title()
    pill_w = max(60, stringWidth(status, "Helvetica-Bold", 7) + 20)
    c.setFillColor(INDIGO_LIGHT)
    c.roundRect(mid_x, top - 22, pill_w, 15, 8, fill=1, stroke=0)
    text(c, status, mid_x + 10, top - 17.5, 7, INDIGO, "Helvetica-Bold")

    created = getattr(order, "created_at", None)
    date = created.strftime("%b %d, %Y, %I:%M %p") if created else "—"
    payment = safe(getattr(order, "payment_method", None)).replace("_", " ").title()
    pstatus = safe(getattr(order, "payment_status", None)).replace("_", " ").title()
    tracking = safe(getattr(order, "tracking_id", None))

    text(c, "▦", mid_x, top - 37, 8, TEXT, "Helvetica")
    text(c, date, mid_x + 13, top - 37, 7.3, TEXT)
    text(c, "▣", mid_x, top - 48, 8, TEXT, "Helvetica")
    text(c, payment, mid_x + 13, top - 48, 7.3, TEXT)
    text(c, "◷", mid_x, top - 59, 8, TEXT, "Helvetica")
    text(c, pstatus, mid_x + 13, top - 59, 7.3, TEXT)
    text(c, "⌁", mid_x, top - 70, 8, TEXT, "Helvetica")
    fit_text(c, f"TRACKING ID - {tracking}", mid_x + 13, top - 70, mid_w - 15, 6.2, TEXT, "Helvetica-Bold")

    rounded_card(c, store_x, top - 77, store_w, 77, WHITE, BORDER, 9)

    text(c, "▣", store_x + 11, top - 18, 15, INDIGO, "Helvetica-Bold")
    text(c, "ELECTRO", store_x + 32, top - 16, 10, TEXT, "Helvetica-Bold")
    text(c, "CART", store_x + 76, top - 16, 10, INDIGO, "Helvetica-Bold")
    text(c, "Premium Electronics Store", store_x + 32, top - 27, 6.2, MUTED)

    address = safe(getattr(order, "address", None))
    city = safe(getattr(order, "city", None))
    state = safe(getattr(order, "state", None))
    pin = safe(getattr(order, "pincode", None))
    phone = safe(getattr(order, "phone", None))
    email = safe(getattr(order, "email", None))

    text(c, "●", store_x + 12, top - 42, 7, TEXT)
    draw_wrapped(c, f"{address}, {city}", store_x + 25, top - 41, store_w - 34, 6.2, 8, TEXT, "Helvetica", 2)
    text(c, "☎", store_x + 12, top - 57, 7, TEXT)
    fit_text(c, phone, store_x + 25, top - 57, store_w - 34, 6.2, TEXT)
    text(c, "✉", store_x + 12, top - 68, 7, TEXT)
    fit_text(c, email, store_x + 25, top - 68, store_w - 34, 6.0, TEXT)


def draw_customer_cards(c, order):
    y = 531
    h = 83
    gap = 12
    x1, w1 = 27, 174
    x2, w2 = x1 + w1 + gap, 174
    x3, w3 = x2 + w2 + gap, PAGE_W - 27 - x2 - w2 - gap

    # Bill
    rounded_card(c, x1, y, w1, h)
    draw_icon_circle(c, x1 + 28, y + h - 28, "●")
    text(c, "BILL TO", x1 + 52, y + h - 31, 8.2, TEXT, "Helvetica-Bold")
    text(c, safe(getattr(order, "customer_name", None)), x1 + 52, y + h - 49, 8, TEXT, "Helvetica-Bold")
    text(c, safe(getattr(order, "phone", None)), x1 + 52, y + h - 62, 7.2, TEXT)
    fit_text(c, safe(getattr(order, "email", None)), x1 + 52, y + h - 74, w1 - 59, 6.6, TEXT)

    # Delivery
    rounded_card(c, x2, y, w2, h)
    draw_icon_circle(c, x2 + 28, y + h - 28, "●")
    text(c, "DELIVERY ADDRESS", x2 + 52, y + h - 31, 8.2, TEXT, "Helvetica-Bold")
    text(c, safe(getattr(order, "customer_name", None)), x2 + 52, y + h - 49, 8, TEXT, "Helvetica-Bold")
    address = safe(getattr(order, "address", None))
    city_state = f"{safe(getattr(order, 'city', None))}, {safe(getattr(order, 'state', None))} - {safe(getattr(order, 'pincode', None))}"
    draw_wrapped(c, address, x2 + 52, y + h - 62, w2 - 61, 6.6, 8, TEXT, "Helvetica", 1)
    draw_wrapped(c, city_state, x2 + 52, y + h - 72, w2 - 61, 6.4, 8, TEXT, "Helvetica", 1)

    # Thank-you panel
    rounded_card(c, x3, y, w3, h, WHITE, BORDER, 9)
    text_center(c, "Thank You", x3 + w3 / 2, y + 47, 17, TEXT, "Helvetica-Oblique")
    text_center(c, "F O R   S H O P P I N G   W I T H   U S", x3 + w3 / 2, y + 31, 5.5, MUTED)
    c.setFillColor(INDIGO)
    c.rect(x3 + w3 / 2 - 10, y + 19, 20, 1.5, fill=1, stroke=0)


def offer_snapshot(item):
    """
    Display-only pricing metadata.
    OrderItem.price remains the authoritative historical charged price.
    """
    charged = Decimal(item.price or 0)
    base = charged
    pct = Decimal("0.00")
    offer_name = ""

    try:
        variant = getattr(item, "variant", None)
        base = Decimal(variant.price if variant else item.product.price)
    except Exception:
        base = charged

    try:
        from .pricing import get_effective_price
        pricing = get_effective_price(item.product, base_price=base)
        sale = Decimal(pricing.get("sale_price", charged))
        if sale == charged and sale < base and base > 0:
            pct = ((base - sale) / base * Decimal("100")).quantize(Decimal("0.01"))
        elif sale < base and base > 0:
            pct = ((base - sale) / base * Decimal("100")).quantize(Decimal("0.01"))
    except Exception:
        if base > charged and base > 0:
            pct = ((base - charged) / base * Decimal("100")).quantize(Decimal("0.01"))

    try:
        offer = item.product.offers.filter(is_active=True).order_by("-created_at").first()
        if offer and offer.is_valid():
            offer_name = str(offer.name)
    except Exception:
        pass

    if base <= charged:
        base = charged
        pct = Decimal("0.00")
        offer_name = ""

    return base, charged, pct, offer_name


def draw_order_items(c, order):
    x = 27
    y_top = 505
    table_w = PAGE_W - 54
    header_h = 23

    text(c, "▰", x, y_top, 11, BLACK, "Helvetica-Bold")
    text(c, "ORDER ITEMS", x + 17, y_top - 1, 12, TEXT, "Helvetica-Bold")
    text_right(
        c,
        "QUALITY PRODUCTS. HAPPIER LIVES.",
        x + table_w,
        y_top,
        5.2,
        MUTED,
    )

    header_y = y_top - 16

    c.setFillColor(INDIGO_LIGHT)
    c.roundRect(
        x,
        header_y - header_h + 3,
        table_w,
        header_h,
        7,
        fill=1,
        stroke=0,
    )

    cols = [
        ("#", 24),
        ("Product", 190),
        ("Variant", 82),
        ("Qty", 38),
        ("Unit Price", 72),
        ("Discount", 74),
        ("Total", table_w - (24 + 190 + 82 + 38 + 72 + 74)),
    ]

    cx = x
    for name, width in cols:
        text(c, name, cx + 7, header_y - 11, 6.3, TEXT, "Helvetica-Bold")
        cx += width

    items = list(order.items.select_related("product", "variant").all())

    # Keep rows compact but tall enough for product image + two-line name.
    row_h = 58

    for i, item in enumerate(items[:5], 1):
        row_top = header_y - header_h - (i - 1) * row_h
        row_bottom = row_top - row_h

        c.setFillColor(WHITE)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.4)
        c.rect(x, row_bottom, table_w, row_h, fill=1, stroke=1)

        # Vertical guides
        cx = x
        for _, width in cols[:-1]:
            cx += width
            c.setStrokeColor(BORDER)
            c.line(cx, row_bottom, cx, row_top)

        # Number
        text_center(
            c,
            str(i),
            x + 12,
            row_bottom + 25,
            7.5,
            TEXT,
            "Helvetica-Bold",
        )

        # Product image
        product_x = x + 31
        image = load_image(image_source(item))

        draw_contain(
            c,
            image,
            product_x + 2,
            row_bottom + 11,
            43,
            36,
            colors.HexColor("#F4F6FA"),
            7,
        )

        # Product name
        name_x = product_x + 51
        product_lines = wrap_lines(
            c,
            item.product.name,
            125,
            "Helvetica-Bold",
            7.2,
            2,
        )

        for j, line in enumerate(product_lines):
            text(
                c,
                line,
                name_x,
                row_bottom + 38 - j * 9,
                7.2,
                TEXT,
                "Helvetica-Bold",
            )

        # SKU
        sku = ""
        if getattr(item, "variant", None):
            sku = safe(getattr(item.variant, "sku", None), "")

        if sku:
            text(
                c,
                f"SKU: {sku}",
                name_x,
                row_bottom + 11,
                6.2,
                MUTED,
            )

        # Variant
        variant = getattr(item, "variant", None)
        variant_text = "Standard"

        if variant:
            pieces = []

            if getattr(variant, "color", None):
                pieces.append(str(variant.color))

            if getattr(variant, "storage", None):
                pieces.append(str(variant.storage))

            variant_text = " / ".join(pieces) if pieces else "Standard"

        variant_x = x + 214

        draw_wrapped(
            c,
            variant_text,
            variant_x + 7,
            row_bottom + 34,
            67,
            6.8,
            8,
            TEXT,
            "Helvetica",
            2,
        )

        # Quantity
        qty_x = x + 296

        text_center(
            c,
            str(int(item.quantity or 0)),
            qty_x + 19,
            row_bottom + 25,
            7.5,
            TEXT,
            "Helvetica-Bold",
        )

        # Pricing
        base, sale, pct, offer_name = offer_snapshot(item)

        price_x = x + 334

        if pct > 0:
            text(
                c,
                money(base),
                price_x + 7,
                row_bottom + 34,
                6.7,
                MUTED,
            )

            c.setStrokeColor(MUTED)
            c.setLineWidth(0.5)

            c.line(
                price_x + 7,
                row_bottom + 36,
                price_x + 7
                + stringWidth(
                    money(base),
                    "Helvetica",
                    6.7,
                ),
                row_bottom + 36,
            )

            text(
                c,
                money(sale),
                price_x + 7,
                row_bottom + 19,
                8,
                TEXT,
                "Helvetica-Bold",
            )
        else:
            text(
                c,
                money(sale),
                price_x + 7,
                row_bottom + 25,
                8,
                TEXT,
                "Helvetica-Bold",
            )

        # Discount
        disc_x = x + 406

        if pct > 0:
            c.setFillColor(GREEN_BG)
            c.roundRect(
                disc_x + 3,
                row_bottom + 32,
                51,
                15,
                8,
                fill=1,
                stroke=0,
            )

            text_center(
                c,
                f"{pct:.0f}% OFF",
                disc_x + 28.5,
                row_bottom + 36.5,
                6,
                GREEN,
                "Helvetica-Bold",
            )

            if offer_name:
                c.setFillColor(GREEN_BG)
                c.roundRect(
                    disc_x + 3,
                    row_bottom + 12,
                    58,
                    13,
                    6,
                    fill=1,
                    stroke=0,
                )

                fit_text(
                    c,
                    offer_name,
                    disc_x + 8,
                    row_bottom + 16,
                    48,
                    5.3,
                    GREEN,
                    "Helvetica-Bold",
                )
        else:
            text(
                c,
                "—",
                disc_x + 10,
                row_bottom + 25,
                7,
                MUTED,
            )

        # Total
        line_total = (
            Decimal(item.price or 0)
            * int(item.quantity or 0)
        )

        text_right(
            c,
            money(line_total),
            x + table_w - 9,
            row_bottom + 25,
            8,
            TEXT,
            "Helvetica-Bold",
        )

    # Bottom of the actual table, not the header.
    return header_y - header_h - len(items[:5]) * row_h


def draw_summary(c, order, y):
    """
    CLEAN ORDER SUMMARY
    -------------------
    Summary is separate from the fixed hero.
    """

    x = 27
    w = PAGE_W - 54
    h = 74

    rounded_card(c, x, y, w, h, WHITE, BORDER, 9)

    # Title
    text(
        c,
        "ORDER SUMMARY",
        x + 14,
        y + h - 19,
        8.5,
        TEXT,
        "Helvetica-Bold",
    )

    items = list(
        order.items.select_related("product", "variant").all()
    )

    subtotal = Decimal("0.00")

    for item in items:
        subtotal += (
            Decimal(item.price or 0)
            * int(item.quantity or 0)
        )

    discount = Decimal(
        getattr(order, "discount_amount", 0) or 0
    )

    total = Decimal(
        getattr(order, "total_amount", 0) or 0
    )

    coupon = getattr(order, "coupon", None)

    coupon_code = ""
    if coupon:
        coupon_code = safe(
            getattr(coupon, "code", None),
            "",
        )

    # Left side small values
    text(
        c,
        "Subtotal",
        x + 14,
        y + h - 38,
        7,
        MUTED,
    )

    text_right(
        c,
        money(subtotal),
        x + 135,
        y + h - 37,
        7.2,
        TEXT,
        "Helvetica-Bold",
    )

    text(
        c,
        "Shipping",
        x + 14,
        y + h - 52,
        7,
        MUTED,
    )

    text_right(
        c,
        "FREE",
        x + 135,
        y + h - 51,
        7.2,
        GREEN,
        "Helvetica-Bold",
    )

    discount_label = "Discount"

    if coupon_code:
        discount_label = f"Discount ({coupon_code})"

    fit_text(
        c,
        discount_label,
        x + 14,
        y + h - 66,
        115,
        6.7,
        MUTED,
    )

    text_right(
        c,
        f"-{money(discount)}",
        x + 135,
        y + h - 66,
        7.2,
        GREEN,
        "Helvetica-Bold",
    )

    # Divider
    divider_x = x + 155

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)

    c.line(
        divider_x,
        y + 10,
        divider_x,
        y + h - 10,
    )

    # Total area
    total_x = divider_x + 18

    text(
        c,
        "TOTAL AMOUNT",
        total_x,
        y + h - 24,
        8.2,
        TEXT,
        "Helvetica-Bold",
    )

    text(
        c,
        "Amount payable",
        total_x,
        y + 14,
        6.2,
        MUTED,
    )

    text_right(
        c,
        money(total),
        x + w - 17,
        y + h - 34,
        15,
        TEXT,
        "Helvetica-Bold",
    )

    # Small saving badge
    if discount > 0:
        c.setFillColor(GREEN_BG)
        c.roundRect(
            total_x,
            y + 10,
            105,
            13,
            6,
            fill=1,
            stroke=0,
        )

        text(
            c,
            f"You saved {money(discount)}",
            total_x + 8,
            y + 14,
            5.8,
            GREEN,
            "Helvetica-Bold",
        )


def draw_bottom(c, order, y):
    x = 27
    gap = 12
    total_w = PAGE_W - 54
    w1 = 160
    w2 = 180
    w3 = total_w - w1 - w2 - gap * 2
    h = 69

    # Payment
    rounded_card(c, x, y, w1, h)
    text(c, "▣", x + 12, y + h - 20, 11, INDIGO, "Helvetica-Bold")
    text(c, "PAYMENT METHOD", x + 30, y + h - 20, 7.8, TEXT, "Helvetica-Bold")
    payment = safe(getattr(order, "payment_method", None)).replace("_", " ").title()
    text(c, payment, x + 30, y + h - 38, 7.8, TEXT, "Helvetica-Bold")
    text(c, "Pay when your order arrives" if payment.lower() == "cash on delivery"
         else "Payment details for this order.",
         x + 30, y + h - 51, 6.2, MUTED)

    # Help
    hx = x + w1 + gap
    rounded_card(c, hx, y, w2, h)
    text(c, "♧", hx + 12, y + h - 20, 11, INDIGO, "Helvetica-Bold")
    text(c, "NEED HELP?", hx + 30, y + h - 20, 7.8, TEXT, "Helvetica-Bold")
    text(c, "Our support team is here for you.", hx + 30, y + h - 36, 6.2, MUTED)
    text(c, "✉  support@electrocart.com", hx + 30, y + h - 49, 6.7, TEXT)
    text(c, "☎  +91 98765 43210", hx + 30, y + h - 61, 6.7, TEXT)

    # QR
    qx = hx + w2 + gap
    rounded_card(c, qx, y, w3, h)

    # Actual QR code: scan opens the ELECTROCART website.
    qr_data = "https://www.electrocart.com/"

    try:
        qr_image = qrcode.make(qr_data)
        qr_buffer = BytesIO()
        qr_image.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        c.drawImage(
            ImageReader(qr_buffer),
            qx + 10,
            y + 14,
            width=42,
            height=42,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        c.setStrokeColor(BORDER)
        c.rect(qx + 10, y + 14, 42, 42, fill=0, stroke=1)

    text(c, "SCAN & EXPLORE", qx + 60, y + h - 20, 7.8, TEXT, "Helvetica-Bold")
    text(c, "Scan to visit", qx + 60, y + h - 36, 6.2, MUTED)
    text(c, "ELECTROCART", qx + 60, y + h - 49, 7, TEXT, "Helvetica-Bold")
    text(c, "Deals | New Arrivals | Support", qx + 60, y + h - 61, 5.8, MUTED)


def draw_footer(c):
    y = 86

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.line(27, y + 28, PAGE_W - 27, y + 28)

    text(
        c,
        "ELECTRO",
        27,
        y + 13,
        9.5,
        TEXT,
        "Helvetica-Bold",
    )

    text(
        c,
        "CART",
        72,
        y + 13,
        9.5,
        INDIGO,
        "Helvetica-Bold",
    )

    text(
        c,
        "© 2026 ELECTROCART. All rights reserved.",
        27,
        y + 2,
        6,
        MUTED,
    )

    text_center(
        c,
        "Tech for a Better You",
        PAGE_W / 2,
        y + 11,
        11,
        TEXT,
        "Helvetica-Oblique",
    )

    c.setStrokeColor(MUTED)
    c.setLineWidth(0.5)
    c.line(
        PAGE_W / 2 - 50,
        y + 6,
        PAGE_W / 2 + 50,
        y + 6,
    )

    text_right(
        c,
        "◎   ▶   ●   X",
        PAGE_W - 27,
        y + 13,
        8,
        TEXT,
        "Helvetica-Bold",
    )

    text_right(
        c,
        "www.electrocart.com",
        PAGE_W - 27,
        y + 2,
        6,
        MUTED,
    )


def build_invoice_pdf(order):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    c.setTitle(f"ELECTROCART Invoice #{order.id}")
    c.setAuthor("ELECTROCART")

    # White page base.
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    draw_header(c)
    draw_top_info(c, order)
    draw_customer_cards(c, order)

    items_bottom = draw_order_items(c, order)

    # ========================================================
    # CLEAN LOWER INVOICE FLOW
    #
    # ORDER ITEMS
    #      ↓
    # ORDER SUMMARY
    #      ↓
    # PAYMENT / HELP / QR
    #      ↓
    # FOOTER
    #
    # The promotional hero has been intentionally removed.
    # ========================================================

    section_gap = 9

    summary_h = 74
    bottom_h = 69

    summary_y = (
        items_bottom
        - section_gap
        - summary_h
    )

    bottom_y = (
        summary_y
        - section_gap
        - bottom_h
    )

    # --------------------------------------------------------
    # If the order is too large for one page,
    # continue the lower sections on page 2.
    # --------------------------------------------------------

    if bottom_y < 75:

        c.showPage()

        c.setFillColor(WHITE)
        c.rect(
            0,
            0,
            PAGE_W,
            PAGE_H,
            fill=1,
            stroke=0,
        )

        draw_header(c)

        summary_y = 610
        bottom_y = 533

    draw_summary(c, order, summary_y)

    draw_bottom(c, order, bottom_y)

    draw_footer(c)

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer.getvalue()


def invoice_pdf_response(order):
    pdf_bytes = build_invoice_pdf(order)

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="ELECTROCART-Invoice-{order.id}.pdf"'
    )
    return response
    