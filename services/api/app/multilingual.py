"""Deterministic helpers for Malay, Indonesian and Arabic input.

The platform works in English and Chinese, but field notices on Malaysian,
Indonesian and Gulf projects often arrive in the local language. These helpers
let the rule layer (intake, classification, clause search) read that input
without a model call:

- ``normalize`` folds case, Eastern Arabic digits and the Arabic spelling
  variants that differ between writers (hamza seats, alef maqsura, taa
  marbuta, diacritics, tatweel), so a keyword matches however it is typed;
- ``detect_language`` tells en / zh / ms / id / ar apart with auditable word
  lists;
- ``expand_query`` adds the English equivalent of every glossary term found
  in a local-language query, so clause summaries written in English and
  Chinese can be retrieved from a Malay, Indonesian or Arabic question.

These are routing aids. They do not translate a notice and do not replace a
reviewed translation.
"""
from __future__ import annotations

import re
import unicodedata

_ARABIC_RE = re.compile(r"[؀-ۿ]")
_CJK_RE = re.compile(r"[一-鿿]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ـ": None})
_LATIN_WORD_RE = re.compile(r"[a-z]+")
_AR_WORD_RE = re.compile(r"[ء-ي]+")

# Words that mark Malay-family text (shared by Malay and Indonesian), then the
# spellings that tell the two standards apart. Each list holds common words
# from notices and site reports, not rare vocabulary.
_MALAY_FAMILY = {
    "dan", "yang", "untuk", "dengan", "pekerja", "tidak", "tanpa", "di", "ke", "dalam", "telah",
    "segera", "kerja", "keselamatan", "kontraktor", "tapak", "lokasi", "jalan", "jam", "hari",
    "pada", "atau", "ini", "itu", "perlu", "wajib", "oleh", "dari", "kepada", "bagi", "serta",
    "sebelum", "setelah", "akan", "sudah", "juga", "adalah", "pihak", "agar", "mohon", "bangunan", "kerusakan",
    "dimulai", "ditemukan", "didapati", "pemilik", "pekerjaan",
}
_MALAY_ONLY = {
    "projek", "kualiti", "kerosakan", "notis", "hendaklah", "dibaiki", "pembaikan", "jabatan",
    "majikan", "tempoh", "sebarang", "kecederaan", "pemaju", "pembetulan", "pematuhan", "lesen",
    "kelengkapan", "pelindung diri", "berpengadang", "rekahan", "ketidakpatuhan", "kakitangan",
    "selepas", "bahawa",
}
_INDONESIAN_ONLY = {
    "proyek", "kualitas", "kerusakan", "pemberitahuan", "harus", "diperbaiki", "perbaikan",
    "dinas", "kecelakaan", "apd", "pengaman", "keropos", "perizinan", "izin",
    "kepatuhan", "pengadaan", "pemasok", "segera", "tenaga", "pengawas", "gedung",
    "setelah", "bahwa",
}


def normalize(text: str) -> str:
    """Lower-case, fold Arabic spelling variants and convert Arabic digits."""
    text = (text or "").translate(_DIGITS)
    if _ARABIC_RE.search(text):
        text = "".join(ch for ch in unicodedata.normalize("NFC", text) if unicodedata.category(ch) != "Mn")
        text = text.translate(_AR_FOLD)
    return text.lower()


def _malay_scores(text: str) -> tuple[int, int, int]:
    lowered = text.lower()
    words = set(_LATIN_WORD_RE.findall(lowered))
    family = len(words & _MALAY_FAMILY)
    ms = sum(1 for w in _MALAY_ONLY if (w in words if " " not in w else w in lowered))
    idn = sum(1 for w in _INDONESIAN_ONLY - {"segera", "tenaga"} if (w in words if " " not in w else w in lowered))
    return family, ms, idn


def detect_language(text: str, country_hint: str | None = None) -> str:
    """Return ``zh``, ``ar``, ``ms``, ``id`` or ``en``.

    Chinese wins when any CJK character is present (bilingual notices are
    routed to the Chinese reader), then Arabic script. Latin text is Malay or
    Indonesian only when at least three Malay-family words occur; the
    standard-specific spellings, then the country, decide between the two.
    """
    text = text or ""
    if _CJK_RE.search(text):
        return "zh"
    if len(_ARABIC_RE.findall(text)) >= 3:
        return "ar"
    family, ms, idn = _malay_scores(text)
    if family + ms + idn < 3 or family == 0 and ms + idn < 3:
        return "en"
    if ms > idn:
        return "ms"
    if idn > ms:
        return "id"
    return "id" if country_hint == "ID" else "ms"


def contains(normalized_text: str, keyword: str) -> bool:
    """Keyword test on normalized text.

    Arabic keywords must start at a word boundary (an optional و ب ف ك ل or
    ال prefix is allowed) so that a short stem does not match inside an
    unrelated word. Latin and Chinese keywords keep the substring matching the
    English rules already use.
    """
    key = normalize(keyword)
    if not _ARABIC_RE.search(key):
        return key in normalized_text
    stem = key[2:] if key.startswith("ال") else key
    pattern = r"(?<![ء-ي])(?:[وبفكل]?(?:ال)?|لل)" + re.escape(stem)
    return re.search(pattern, normalized_text) is not None


def expand_query(query: str, glossary_rows: list[dict]) -> tuple[str, list[dict]]:
    """Append the English term for each local glossary term found in ``query``.

    Longer terms are tried first and a matched span is not reused, so
    "صاحب العمل" is not also read as "العمل". Returns the expanded query and
    the matches, which the search response reports so the expansion is
    visible to the user.
    """
    if not query or _CJK_RE.search(query):
        return query, []
    text = normalize(query)
    matches: list[dict] = []
    candidates = sorted(
        (row for row in glossary_rows if row.get("local") and row.get("local_lang") in {"ms", "id", "ar"}),
        key=lambda row: len(row["local"]), reverse=True,
    )
    for row in candidates:
        key = normalize(row["local"])
        if len(key) < 3:
            continue
        if _ARABIC_RE.search(key):
            stem = key[2:] if key.startswith("ال") else key
            found = re.search(r"(?<![ء-ي])(?:[وبفكل]?(?:ال)?|لل)" + re.escape(stem) + r"(?![ء-ي])", text)
        else:
            found = re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", text)
        if not found:
            continue
        text = text[:found.start()] + " " * (found.end() - found.start()) + text[found.end():]
        en = re.sub(r"\s*\(.*?\)", "", row["en"]).strip()
        matches.append({"local": row["local"], "en": en, "term_id": row["id"], "local_basis": row.get("local_basis", "")})
    if not matches:
        return query, []
    return query + " " + " ".join(m["en"] for m in matches), matches


def expand_chinese(query: str, glossary_rows: list[dict]) -> tuple[str, list[dict]]:
    """Append the English term for each Chinese glossary term in ``query``.

    The clause library is written in English (plus a Chinese paraphrase), so
    a Chinese question that uses another wording than the paraphrase, such
    as 外籍工人 for 外籍雇员, still reaches the clause through the English
    term. Longer terms are tried first and a matched span is not reused.
    """
    if not query or not _CJK_RE.search(query):
        return query, []
    text = query
    matches: list[dict] = []
    seen: set[str] = set()
    for row in sorted((r for r in glossary_rows if len(r.get("zh") or "") >= 2), key=lambda r: len(r["zh"]), reverse=True):
        zh = row["zh"]
        if zh not in text:
            continue
        text = text.replace(zh, " " * len(zh))
        en = re.sub(r"\s*\(.*?\)", "", row["en"]).strip()
        if en not in seen:
            seen.add(en)
            matches.append({"local": zh, "en": en, "term_id": row["id"], "local_basis": row.get("local_basis", "")})
    if not matches:
        return query, []
    return query + " " + " ".join(m["en"] for m in matches), matches
