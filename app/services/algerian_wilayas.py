"""Canonical Algerian wilayas and matching helpers."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Wilaya:
    code: str
    name_ar: str
    name_fr: str
    aliases: tuple[str, ...] = ()


WILAYAS = (
    Wilaya("01", "أدرار", "Adrar", ("ادرار",)),
    Wilaya("02", "الشلف", "Chlef", ("الشليف",)),
    Wilaya("03", "الأغواط", "Laghouat", ("الاغواط", "لغواط")),
    Wilaya("04", "أم البواقي", "Oum El Bouaghi", ("ام البواقي", "Oum Bouaghi")),
    Wilaya("05", "باتنة", "Batna"),
    Wilaya("06", "بجاية", "Béjaïa", ("بجايا", "Bejaia")),
    Wilaya("07", "بسكرة", "Biskra"),
    Wilaya("08", "بشار", "Béchar", ("Bechar",)),
    Wilaya("09", "البليدة", "Blida"),
    Wilaya("10", "البويرة", "Bouira"),
    Wilaya("11", "تمنراست", "Tamanrasset", ("تمونراست",)),
    Wilaya("12", "تبسة", "Tébessa", ("Tebessa",)),
    Wilaya("13", "تلمسان", "Tlemcen"),
    Wilaya("14", "تيارت", "Tiaret"),
    Wilaya("15", "تيزي وزو", "Tizi Ouzou", ("تيزي وزو", "Tizi-Ouzou")),
    Wilaya("16", "الجزائر", "Alger", ("الجزائر العاصمة", "Algiers")),
    Wilaya("17", "الجلفة", "Djelfa"),
    Wilaya("18", "جيجل", "Jijel"),
    Wilaya("19", "سطيف", "Sétif", ("Setif",)),
    Wilaya("20", "سعيدة", "Saïda", ("Saida",)),
    Wilaya("21", "سكيكدة", "Skikda"),
    Wilaya("22", "سيدي بلعباس", "Sidi Bel Abbès", ("سيدي بلعباس", "Sidi Bel Abbes")),
    Wilaya("23", "عنابة", "Annaba"),
    Wilaya("24", "قالمة", "Guelma", ("قلمة",)),
    Wilaya("25", "قسنطينة", "Constantine", ("قسطنطينة",)),
    Wilaya("26", "المدية", "Médéa", ("المديه", "Medea")),
    Wilaya("27", "مستغانم", "Mostaganem"),
    Wilaya("28", "المسيلة", "M'Sila", ("المسيله", "Msila", "M'Sila")),
    Wilaya("29", "معسكر", "Mascara"),
    Wilaya("30", "ورقلة", "Ouargla"),
    Wilaya("31", "وهران", "Oran"),
    Wilaya("32", "البيض", "El Bayadh", ("البيّض", "El-Bayadh")),
    Wilaya("33", "إليزي", "Illizi", ("اليزي",)),
    Wilaya("34", "برج بوعريريج", "Bordj Bou Arréridj", ("Bordj Bou Arreridj",)),
    Wilaya("35", "بومرداس", "Boumerdès", ("Boumerdes",)),
    Wilaya("36", "الطارف", "El Tarf", ("الطرف", "El-Tarf")),
    Wilaya("37", "تندوف", "Tindouf"),
    Wilaya("38", "تيسمسيلت", "Tissemsilt"),
    Wilaya("39", "الوادي", "El Oued", ("واد سوف", "El-Oued")),
    Wilaya("40", "خنشلة", "Khenchela"),
    Wilaya("41", "سوق أهراس", "Souk Ahras", ("سوق اهراس",)),
    Wilaya("42", "تيبازة", "Tipaza", ("تيبازا",)),
    Wilaya("43", "ميلة", "Mila"),
    Wilaya("44", "عين الدفلى", "Aïn Defla", ("عين دڤلة", "Ain Defla")),
    Wilaya("45", "النعامة", "Naâma", ("النعامه", "Naama")),
    Wilaya("46", "عين تموشنت", "Aïn Témouchent", ("عين تموشان", "Ain Temouchent")),
    Wilaya("47", "غرداية", "Ghardaïa", ("غردايه", "Ghardaia")),
    Wilaya("48", "غليزان", "Relizane", ("غليزان", "Relizane")),
    Wilaya("49", "تيميمون", "Timimoun"),
    Wilaya("50", "برج باجي مختار", "Bordj Badji Mokhtar"),
    Wilaya("51", "أولاد جلال", "Ouled Djellal", ("اولاد جلال",)),
    Wilaya("52", "بني عباس", "Béni Abbès", ("بني عباس", "Beni Abbes")),
    Wilaya("53", "عين صالح", "In Salah", ("عين الصالح", "Ain Salah")),
    Wilaya("54", "عين قزام", "In Guezzam", ("عين ڨزام", "Ain Guezzam")),
    Wilaya("55", "تقرت", "Touggourt", ("توقرت",)),
    Wilaya("56", "جانت", "Djanet"),
    Wilaya("57", "المغير", "El M'Ghair", ("المغير", "El Meghaier", "El Mghair")),
    Wilaya("58", "المنيعة", "El Meniaa", ("المنيعة", "El Menia")),
)

_ARABIC_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "ڨ": "ق",
        "گ": "ك",
        "ـ": "",
    }
)


def normalize_wilaya_text(value: str) -> str:
    """Normalize Arabic and French wilaya spellings without product rules."""
    normalized = unicodedata.normalize("NFKD", (value or "").casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).translate(_ARABIC_TRANSLATION)
    normalized = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _wilaya_names(wilaya: Wilaya) -> tuple[str, ...]:
    return (wilaya.name_ar, wilaya.name_fr, *wilaya.aliases)


def find_wilaya(text: str | None) -> Wilaya | None:
    """Find a canonical wilaya by a bounded match against its official name or aliases."""
    normalized_text = normalize_wilaya_text(text or "")
    candidates = sorted(
        (
            (normalize_wilaya_text(name), wilaya)
            for wilaya in WILAYAS
            for name in _wilaya_names(wilaya)
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for normalized_name, wilaya in candidates:
        if normalized_name and re.search(
            rf"(?<!\w){re.escape(normalized_name)}(?!\w)",
            normalized_text,
        ):
            return wilaya
    return None


def _served_codes(served_wilayas: str) -> set[str]:
    wilayas_by_code = {wilaya.code: wilaya for wilaya in WILAYAS}
    codes = set()
    for name in re.split(r"[,،;؛|/\n]+", served_wilayas):
        normalized_name = normalize_wilaya_text(name)
        code = normalized_name.zfill(2) if normalized_name.isdigit() else None
        wilaya = wilayas_by_code.get(code) if code else find_wilaya(name)
        if wilaya:
            codes.add(wilaya.code)
    return codes


def resolve_delivery_wilaya(
    message: str,
    served_wilayas: str | None,
) -> Wilaya | None:
    """Resolve a customer wilaya, then apply the store's separate service policy."""
    wilaya = find_wilaya(message)
    if wilaya is None:
        return None
    if served_wilayas and wilaya.code not in _served_codes(served_wilayas):
        return None
    return wilaya
