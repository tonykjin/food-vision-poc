"""Local product-barcode reading and GTIN-13 normalization (#50). Synthetic images only."""

import pytest
from tests.conftest import barcode_image, synthetic_image

from foodvision.imaging.barcode import (
    expand_upce,
    find_product_barcodes,
    gs1_check_digit_ok,
    to_gtin13,
)


@pytest.mark.parametrize(
    ("digits", "ok"),
    [
        ("4006381333931", True),  # EAN-13
        ("036000291452", True),  # UPC-A
        ("96385074", True),  # EAN-8
        ("4006381333932", False),  # wrong check digit
        ("40063813339a1", False),
        ("7", False),
    ],
)
def test_gs1_check_digit(digits, ok):
    assert gs1_check_digit_ok(digits) is ok


@pytest.mark.parametrize(
    ("upce", "upca"),
    [
        ("01234565", "012345000065"),  # last digit 5-9: manufacturer 5 digits + 0000
        ("04252614", "042100005264"),  # last digit 0-2
        ("01234531", "012300000451"),  # last digit 3
        ("01234543", "012340000053"),  # last digit 4
        ("11234502", "112000003452"),  # number system 1
    ],
)
def test_upce_expands_to_upca(upce, upca):
    assert expand_upce(upce) == upca


def test_upce_with_bad_check_or_number_system_is_rejected():
    assert expand_upce("01234566") is None  # check digit doesn't match the expansion
    assert expand_upce("21234565") is None  # number system must be 0 or 1


@pytest.mark.parametrize(
    ("text", "is_upce", "gtin"),
    [
        ("036000291452", False, "0036000291452"),  # UPC-A: left-padded
        ("4006381333931", False, "4006381333931"),
        ("96385074", False, "0000096385074"),  # EAN-8: left-padded
        ("01234565", True, "0012345000065"),  # UPC-E: expanded first
        ("0012345000065", True, "0012345000065"),  # already expanded by the decoder
        ("4006381333932", False, None),  # bad check digit: never looked up
        ("12345", False, None),
        ("ABC", False, None),
    ],
)
def test_to_gtin13(text, is_upce, gtin):
    assert to_gtin13(text, is_upce) == gtin


@pytest.mark.parametrize(
    ("code", "kind", "gtin"),
    [
        ("4006381333931", "EAN13", "4006381333931"),
        ("036000291452", "UPCA", "0036000291452"),
        ("96385074", "EAN8", "0000096385074"),
        ("01234565", "UPCE", "0012345000065"),
    ],
)
def test_reads_each_product_format_as_gtin13(code, kind, gtin):
    assert find_product_barcodes(barcode_image((code, kind))) == [gtin]


def test_reads_jpeg_and_returns_distinct_codes_in_order():
    data = barcode_image(("4006381333931", "EAN13"), ("96385074", "EAN8"), fmt="JPEG")
    assert sorted(find_product_barcodes(data)) == ["0000096385074", "4006381333931"]


def test_no_barcode_and_non_product_symbols_give_nothing():
    assert find_product_barcodes(synthetic_image(size=(640, 480))) == []
    assert find_product_barcodes(barcode_image(("https://example.invalid", "QRCode"))) == []
