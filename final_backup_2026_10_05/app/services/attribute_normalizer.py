"""Normalize customer-facing attribute names and values using fixed aliases."""
from __future__ import annotations

import re
import unicodedata


ATTRIBUTE_SYNONYMS: dict[str, dict[str, list[str]]] = {
    "apparel": {
        "color": ["color", "couleur", "لون", "اللون", "ألوان", "rouge", "أحمر", "احمر"],
        "size": ["size", "taille", "مقاس", "المقاس", "قياس", "度量"],
    },
    "electronics": {
        "storage": [
            "storage", "mémoire de stockage", "memoire de stockage", "stockage",
            "capacite", "capacité", "سعة", "التخزين", "تخزين", "容量",
        ],
        "ram": ["ram", "mémoire vive", "memoire vive", "رام", "الذاكرة العشوائية"],
        "screen_size": [
            "screen size", "taille d'écran", "taille ecran", "حجم الشاشة",
            "قياس الشاشة", "بوصة", "pouces", "inch",
        ],
        "battery": ["battery", "batterie", "بطارية", "البطارية", "سعة البطارية"],
    },
    "home": {
        "material": ["material", "matière", "matiere", "مادة", "المادة", "خام", "الخشب", "خشب", "bois", "wood", "metal"],
        "dimensions": ["dimensions", "dimension", "أبعاد", "ابعاد", "قياسات", "مقاسات"],
    },
    "grocery": {
        "weight": ["weight", "poids", "وزن", "الوزن", "ثقل", "كيلو", "kg"],
        "volume": ["volume", "litre", "liter", "لتر", "حجم السائل", "سعة السائل"],
        "flavor": ["flavor", "flavour", "saveur", "نكهة", "النكهة", "طعم"],
    },
}

VALUE_SYNONYMS: dict[str, dict[str, str]] = {
    "color": {
        "black": "black", "noir": "black", "أسود": "black", "اسود": "black",
        "white": "white", "blanc": "white", "أبيض": "white", "ابيض": "white",
        "red": "red", "rouge": "red", "أحمر": "red", "احمر": "red",
        "blue": "blue", "bleu": "blue", "أزرق": "blue", "ازرق": "blue",
        "green": "green", "vert": "green", "أخضر": "green", "اخضر": "green",
    },
    "material": {
        "wood": "wood", "bois": "wood", "خشب": "wood", "الخشب": "wood",
        "metal": "metal", "métal": "metal", "معدن": "metal", "حديد": "metal",
        "plastic": "plastic", "plastique": "plastic", "بلاستيك": "plastic",
        "glass": "glass", "verre": "glass", "زجاج": "glass",
    },
}

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CANONICAL_KEYS = {
    canonical
    for group in ATTRIBUTE_SYNONYMS.values()
    for canonical in group
}


def _clean_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).translate(_ARABIC_DIGITS)
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _lookup_text(raw: str) -> str:
    return _clean_text(raw).casefold()


def normalize_key(raw: str) -> str | None:
    """Return a canonical key for a known attribute name, or None."""
    if not isinstance(raw, str):
        return None

    candidate = _lookup_text(raw)
    for attributes in ATTRIBUTE_SYNONYMS.values():
        for canonical, synonyms in attributes.items():
            if candidate == _lookup_text(canonical) or any(
                candidate == _lookup_text(synonym) for synonym in synonyms
            ):
                return canonical
    return None


def normalize_value(value: str, key: str | None = None) -> str:
    """Normalize known values; also accept legacy ``(key, value)`` calls."""
    if not isinstance(value, str):
        value = str(value)
    if key is not None and value.casefold() in _CANONICAL_KEYS and key.casefold() not in _CANONICAL_KEYS:
        value, key = key, value

    cleaned = _clean_text(value)
    canonical_key = normalize_key(key) if key is not None else None
    canonical_key = canonical_key or (key if key in _CANONICAL_KEYS else None)
    lookup_value = _lookup_text(cleaned)

    if canonical_key:
        aliases = VALUE_SYNONYMS.get(canonical_key, {})
        for synonym, canonical in aliases.items():
            if lookup_value == _lookup_text(synonym):
                return canonical

    if canonical_key == "storage":
        match = re.fullmatch(
            r"(\d+(?:[.,]\d+)?)\s*(?:gb|go|g|giga|gigabyte(?:s)?|غيغا|جيغا|جيجابايت)",
            lookup_value,
        )
        if match:
            return f"{match.group(1).replace(',', '.')}gb"

    if canonical_key == "screen_size":
        match = re.fullmatch(
            r"(\d+(?:[.,]\d+)?)\s*(?:inches?|inch|pouces?|بوصة|بوصات)",
            lookup_value,
        )
        if match:
            return f"{match.group(1).replace(',', '.')}inch"

    if canonical_key == "weight":
        if lookup_value in {"كيلو", "كيلوغرام", "كيلوجرام", "kg", "kilo", "kilogramme", "kilogrammes"}:
            return "1kg"
        match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(kg|kgs|كغ|كلغ|g|gr|grammes?|غرام|غرامات)", lookup_value)
        if match:
            unit = "kg" if match.group(2) in {"kg", "kgs", "كغ", "كلغ"} else "g"
            return f"{match.group(1).replace(',', '.')}{unit}"

    if canonical_key == "volume":
        match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:l|litres?|liters?|لتر|لترات)", lookup_value)
        if match:
            return f"{match.group(1).replace(',', '.')}l"

    return cleaned


def normalize_attributes(attrs: dict) -> dict:
    """Normalize known keys/values while preserving unknown keys safely."""
    normalized: dict = {}
    for raw_key, raw_value in attrs.items():
        key_text = str(raw_key)
        canonical_key = normalize_key(key_text)
        output_key = canonical_key or key_text
        normalized[output_key] = normalize_value(
            str(raw_value),
            canonical_key,
        )
    return normalized
