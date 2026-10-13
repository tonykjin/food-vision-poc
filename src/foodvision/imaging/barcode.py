"""Local product-barcode reading (no external call) for App A's barcode lookup (#50).

Decodes UPC-A, UPC-E, EAN-13 and EAN-8 with zxing-cpp and normalizes each to the GTIN-13
that fatsecret `food.find_id_for_barcode.v2` expects (docs checked 2026-10-13: 13 digits,
zero-padded on the left; UPC-E converted to UPC-A first). Every code's GS1 check digit is
verified, so a misread is dropped rather than looked up.

Call only on bytes that `prepare_image` has already accepted (format and pixel limits).
"""

import io

import zxingcpp
from PIL import Image, ImageOps

PRODUCT_FORMATS = (
    zxingcpp.BarcodeFormat.EAN13,
    zxingcpp.BarcodeFormat.EAN8,
    zxingcpp.BarcodeFormat.UPCA,
    zxingcpp.BarcodeFormat.UPCE,
)
MAX_DECODE_LONG_EDGE_PX = 2000  # bounds decode time; barcodes stay legible at this size


def gs1_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check: weights 3,1,3,... from the rightmost data digit."""
    if not digits.isdigit() or len(digits) < 2:
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def expand_upce(code: str) -> str | None:
    """8-digit UPC-E (number system, 6 digits, check) -> 12-digit UPC-A, or None."""
    if len(code) != 8 or not code.isdigit() or code[0] not in "01":
        return None
    ns, d, check = code[0], code[1:7], code[7]
    last = d[5]
    if last in "012":
        body = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + last
    upca = ns + body + check
    return upca if gs1_check_digit_ok(upca) else None


def to_gtin13(text: str, is_upce: bool = False) -> str | None:
    """Normalize a decoded product code to a check-digit-valid GTIN-13, or None."""
    digits = text.strip()
    if not digits.isdigit():
        return None
    if is_upce and len(digits) == 8:
        digits = expand_upce(digits) or ""
    if len(digits) not in (8, 12, 13):
        return None
    gtin = digits.zfill(13)
    return gtin if gs1_check_digit_ok(gtin) else None


def find_product_barcodes(data: bytes) -> list[str]:
    """Distinct GTIN-13s of the product barcodes visible in an image, in reading order."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
    if max(image.size) > MAX_DECODE_LONG_EDGE_PX:
        image.thumbnail((MAX_DECODE_LONG_EDGE_PX, MAX_DECODE_LONG_EDGE_PX))
    found: list[str] = []
    for barcode in zxingcpp.read_barcodes(image, formats=PRODUCT_FORMATS):
        if not barcode.valid:
            continue
        gtin = to_gtin13(barcode.text, barcode.format == zxingcpp.BarcodeFormat.UPCE)
        if gtin is not None and gtin not in found:
            found.append(gtin)
    return found
