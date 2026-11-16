from functools import lru_cache
from pathlib import Path
import re
from typing import Dict, Iterable, List


TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "assets"
    / "templates"
    / "multilingual_captain_announcement_master.txt"
)

LANGUAGE_HEADING_MAP = {
    "English": "English",
    "Deutsch": "German",
    "العربية": "Arabic",
    "Italiano": "Italian",
    "Español": "Spanish",
    "فارسی": "Farsi",
}

LANGUAGE_DISPLAY_LABELS = {
    "English": "English",
    "German": "Deutsch",
    "Arabic": "العربية",
    "Italian": "Italiano",
    "Spanish": "Español",
    "Farsi": "فارسی",
}

AIRLINE_NATIVE_LANGUAGES = {
    "Air France": "French",
    "Emirates": "Arabic",
    "Etihad Airways": "Arabic",
    "Iran Air": "Farsi",
    "ITA Airways": "Italian",
    "Lufthansa": "German",
    "Mahan Air": "Farsi",
    "Qatar Airways": "Arabic",
}

PLACEHOLDER_PATTERN = re.compile(r"\[([A-Z][A-Z0-9 /]+)\]")
RTL_ANNOUNCEMENT_LANGUAGES = frozenset(("Farsi", "Arabic"))
LOCAL_DIGITS = {
    "Farsi": str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"),
    "Arabic": str.maketrans("0123456789,", "٠١٢٣٤٥٦٧٨٩٬"),
}
WEATHER_TRANSLATIONS = {
    "clear": ("صاف", "صحو"),
    "partly cloudy": ("نیمه‌ابری", "غائم جزئيًا"),
    "cloudy": ("ابری", "غائم"),
    "overcast": ("کاملاً ابری", "ملبّد بالغيوم"),
    "thunderstorms": ("رعدوبرق", "عواصف رعدية"),
    "snow": ("بارش برف", "تساقط الثلوج"),
    "freezing precipitation": ("بارش یخ‌زن", "هطول متجمّد"),
    "rain": ("بارش باران", "هطول الأمطار"),
    "drizzle": ("بارش نم‌نم باران", "رذاذ"),
    "fog": ("مه", "ضباب"),
    "mist": ("مه رقیق", "ضباب خفيف"),
    "haze": ("غبار", "غبار"),
}


def arabic_duration_part(count: int, singular: str, dual: str, plural: str) -> str:
    if count == 1:
        return singular + " واحدة"
    if count == 2:
        return dual
    return f"{count} {plural if 3 <= count <= 10 else singular}"


def localize_rtl_value(language: str, key: str, value: str) -> str:
    if key.endswith("WEATHER CONDITION"):
        translation = WEATHER_TRANSLATIONS.get(value.casefold())
        if translation:
            value = translation[0 if language == "Farsi" else 1]
    elif key in ("FLIGHT TIME", "TIME TO ARRIVAL"):
        match = re.fullmatch(r"(\d+)h\s+(\d+)m", value)
        if match:
            hours, minutes = map(int, match.groups())
            if language == "Farsi":
                parts = [f"{hours} ساعت"] if hours else []
                if minutes or not hours:
                    parts.append(f"{minutes} دقیقه")
                value = " و ".join(parts)
            else:
                parts = []
                if hours:
                    parts.append(arabic_duration_part(hours, "ساعة", "ساعتين", "ساعات"))
                if minutes or not hours:
                    parts.append(arabic_duration_part(minutes, "دقيقة", "دقيقتين", "دقائق"))
                value = " و".join(parts)
            value = value.translate(LOCAL_DIGITS[language])
    elif key.endswith(("ALTITUDE", "TEMPERATURE")):
        value = value.translate(LOCAL_DIGITS[language])
    # Let each value establish its own direction, including mixed airport names and codes.
    return f"\u2068{value}\u2069" if value else ""


@lru_cache(maxsize=1)
def load_announcement_templates() -> Dict[str, Dict[str, str]]:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    templates: Dict[str, Dict[str, str]] = {"departure": {}, "descent": {}}
    phase = ""
    language = ""
    body: List[str] = []

    def flush() -> None:
        nonlocal body
        if phase and language:
            templates[phase][language] = "\n".join(body).strip()
        body = []

    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if stripped == "# TAKEOFF / DEPARTURE ANNOUNCEMENT":
            flush()
            phase = "departure"
            language = ""
            continue
        if stripped == "# DESCENT / LANDING ANNOUNCEMENT":
            flush()
            phase = "descent"
            language = ""
            continue
        if phase and stripped.startswith("## "):
            flush()
            heading = stripped[3:].strip()
            language = LANGUAGE_HEADING_MAP.get(heading, "")
            continue
        if phase and language:
            body.append(raw_line.rstrip())

    flush()
    return templates


def supported_languages() -> List[str]:
    templates = load_announcement_templates()
    return list(templates["departure"].keys())


def primary_languages_for_airline(airline: str) -> List[str]:
    languages = ["English"]
    native_language = AIRLINE_NATIVE_LANGUAGES.get((airline or "").strip())
    if native_language in supported_languages() and native_language not in languages:
        languages.append(native_language)
    return languages


def missing_native_language_for_airline(airline: str) -> str:
    native_language = AIRLINE_NATIVE_LANGUAGES.get((airline or "").strip(), "")
    if native_language and native_language not in supported_languages():
        return native_language
    return ""


def template_placeholders(language: str, phase: str) -> List[str]:
    template = load_announcement_templates().get(phase, {}).get(language, "")
    return list(dict.fromkeys(PLACEHOLDER_PATTERN.findall(template)))


def render_announcement(
    language: str,
    phase: str,
    values: Dict[str, object],
    *,
    allow_partial: bool = False,
) -> str:
    template = load_announcement_templates().get(phase, {}).get(language)
    if not template:
        raise ValueError(f"No {phase} template is available for {language}.")

    clean_values = {
        str(key): str(value).strip()
        for key, value in values.items()
        if value is not None
    }
    required = template_placeholders(language, phase)
    missing = [placeholder for placeholder in required if not clean_values.get(placeholder)]
    if missing and not allow_partial:
        raise ValueError("Missing announcement information: " + ", ".join(missing))

    rendered = template
    if missing:
        paragraphs = []
        for paragraph in template.split("\n\n"):
            sentences = re.split(r"(?<=[.!?؟。])\s+", paragraph.strip())
            available = [
                sentence for sentence in sentences
                if all(clean_values.get(key) for key in PLACEHOLDER_PATTERN.findall(sentence))
            ]
            if available:
                paragraphs.append(" ".join(available))
        rendered = "\n\n".join(paragraphs)
    def insert_value(match: re.Match) -> str:
        key = match[1]
        value = clean_values.get(key, "")
        return localize_rtl_value(language, key, value) if language in RTL_ANNOUNCEMENT_LANGUAGES else value

    return PLACEHOLDER_PATTERN.sub(insert_value, rendered)


def validate_template_library(phases: Iterable[str] = ("departure", "descent")) -> List[str]:
    issues: List[str] = []
    templates = load_announcement_templates()
    languages = supported_languages()
    for phase in phases:
        for language in languages:
            template = templates.get(phase, {}).get(language, "")
            if not template:
                issues.append(f"Missing {phase} template for {language}")
            elif not template_placeholders(language, phase):
                issues.append(f"No placeholders in {phase} template for {language}")
    return issues
