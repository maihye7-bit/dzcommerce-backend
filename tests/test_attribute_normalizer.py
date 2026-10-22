import pytest

from app.services.attribute_normalizer import (
    normalize_attributes,
    normalize_key,
    normalize_value,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("سعة", "storage"),
        ("stockage", "storage"),
        ("RAM", "ram"),
        ("الذاكرة العشوائية", "ram"),
        ("couleur", "color"),
        ("اللون", "color"),
        ("taille", "size"),
        ("matière", "material"),
        ("poids", "weight"),
        ("حجم الشاشة", "screen_size"),
    ],
)
def test_normalize_key_aliases(raw, expected):
    assert normalize_key(raw) == expected


@pytest.mark.parametrize(
    ("value", "key", "expected"),
    [
        ("256 غيغا", "storage", "256gb"),
        ("256GB", "storage", "256gb"),
        ("256 Go", "storage", "256gb"),
        ("خشب", "material", "wood"),
        ("noir", "color", "black"),
        ("٤٢", "size", "42"),
        ("65 بوصة", "screen_size", "65inch"),
        ("كيلو", "weight", "1kg"),
        ("1 litre", "volume", "1l"),
        ("1.5 giga", "storage", "1.5gb"),
    ],
)
def test_normalize_value_aliases(value: str, key: str, expected: str) -> None:
    assert normalize_value(value, key) == expected


def test_normalize_value_supports_legacy_key_value_order():
    assert normalize_value("storage", "256 غيغا") == "256gb"


def test_normalize_attributes_normalizes_keys_and_values():
    assert normalize_attributes({"اللون": "أسود"}) == {"color": "black"}


def test_unknown_attribute_key_is_preserved():
    assert normalize_key("custom_spec") is None
    assert normalize_attributes({"custom_spec": "  Value  "}) == {
        "custom_spec": "Value"
    }
