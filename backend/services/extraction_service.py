from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status


DECLARATION_FIELDS = (
    "product_name", "manufacturer", "packer", "importer", "country_of_origin",
    "net_quantity", "mrp", "month_year_of_manufacture_or_packing",
    "best_before_or_use_by", "consumer_care", "unit_sale_price", "batch_or_lot_number",
)

_ocr_results: dict[str, dict[str, Any]] = {}
_TRIM_CHARS = " \t:.-"


def store_ocr_result(inspection_id: str, result: dict[str, Any]) -> None:
    _ocr_results[inspection_id] = result


def get_ocr_result(inspection_id: str) -> dict[str, Any]:
    try:
        return _ocr_results[inspection_id]
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OCR result not found for this inspection") from error


def _not_detected() -> dict[str, Any]:
    return {"value": None, "source_text": None, "confidence": 0.0, "status": "not_detected"}


def _review(source_text: str) -> dict[str, Any]:
    return {"value": None, "source_text": source_text, "confidence": 0.0, "status": "needs_review"}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(_TRIM_CHARS)


def _detected(value: str, source_text: str, confidence: float) -> dict[str, Any]:
    value = _normalise(value)
    return _review(source_text) if not value else {"value": value, "source_text": source_text, "confidence": round(confidence, 2), "status": "detected"}


def _labelled_value(lines: list[str], labels: str, value_pattern: str) -> dict[str, Any]:
    label_pattern = re.compile(rf"\b(?:{labels})\b", re.I)
    value_regex = re.compile(value_pattern, re.I)
    saw_label = False
    for index, line in enumerate(lines):
        label = label_pattern.search(line)
        if not label:
            continue
        saw_label = True
        value = value_regex.search(line[label.end():].strip(_TRIM_CHARS))
        if value:
            return _detected(value.group("value"), line, 0.95)
        if index + 1 < len(lines):
            value = value_regex.search(lines[index + 1])
            if value:
                return _detected(value.group("value"), f"{line} | {lines[index + 1]}", 0.85)
    return _review(next(line for line in lines if label_pattern.search(line))) if saw_label else _not_detected()


def _party(lines: list[str], labels: str) -> dict[str, Any]:
    label_pattern = re.compile(rf"\b(?:{labels})\b", re.I)
    value_regex = re.compile(r"(?P<value>[A-Za-z][A-Za-z0-9&,.()' /-]{2,})")
    company_hint = re.compile(r"\b(?:pvt|private|ltd|limited|inc|company|foods?|traders?|industries|holdings?)\b", re.I)
    for index, line in enumerate(lines):
        label = label_pattern.search(line)
        if not label:
            continue
        value = value_regex.search(line[label.end():].strip(" \t:.-"))
        if value:
            return _detected(value.group("value"), line, 0.95)
        if index + 1 < len(lines) and company_hint.search(lines[index + 1]):
            return _detected(lines[index + 1], f"{line} | {lines[index + 1]}", 0.8)
        return _review(line)
    return _not_detected()


def _quantity(lines: list[str]) -> dict[str, Any]:
    return _labelled_value(lines, r"net\s*(?:quantity|qty|weight|wt)|qty", r"(?P<value>\d+(?:\.\d+)?\s*(?:kg|kgs|g|gm|mg|l|litre|liter|ml|cl|pcs?|pieces?))")


def _money(lines: list[str], labels: str) -> dict[str, Any]:
    return _labelled_value(lines, labels, r"(?:rs\.?|inr|₹)?\s*(?P<value>[\d,]+(?:\.\d{1,2})?)")


def _date_or_period(lines: list[str], labels: str) -> dict[str, Any]:
    return _labelled_value(lines, labels, r"(?P<value>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:months?|years?)\b|[A-Za-z]+\s+\d{2,4})")


def _best_before(lines: list[str]) -> dict[str, Any]:
    return _labelled_value(lines, r"best\s*before|use\s*by|exp(?:iry)?\b", r"(?P<value>(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s+(?:months?|years?)\b|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{2,4}|[A-Za-z]+\s+\d{2,4})")


def _contact_value(line: str, phone_pattern: re.Pattern[str], website_pattern: re.Pattern[str]) -> str | None:
    phone = phone_pattern.search(line)
    if phone:
        return phone.group()
    website = website_pattern.search(line)
    if website:
        return website.group()
    for token in line.split():
        candidate = token.strip(".,;:()[]")
        if "@" in candidate and "." in candidate.rsplit("@", 1)[-1]:
            return candidate
    return None


def _contact(lines: list[str]) -> dict[str, Any]:
    phone_pattern = re.compile(r"\+?\d[\d ()-]{7,}\d")
    website_pattern = re.compile(r"(?:https?://|www\.)\S+")
    care_pattern = re.compile(r"consumer\s*(?:care|complaint|services?)|customer\s*care|helpline|toll[- ]?free", re.I)
    for index, line in enumerate(lines):
        if not care_pattern.search(line):
            continue
        contact = _contact_value(line, phone_pattern, website_pattern)
        if contact:
            return _detected(contact, line, 0.9)
        for following in lines[index + 1:index + 9]:
            if re.search(r"\blic\.?\b|address|p\.o\.?\s*box|village|road", following, re.I):
                continue
            contact = _contact_value(following, phone_pattern, website_pattern)
            if contact:
                return _detected(contact, f"{line} | {following}", 0.8)
        return _review(line)
    return _not_detected()


def _batch(lines: list[str]) -> dict[str, Any]:
    label_pattern = re.compile(r"\b(?:batch|lot)\b|\bb\.?\s*no\.?\b", re.I)
    for line in lines:
        label = label_pattern.search(line)
        if not label:
            continue
        value = re.sub(r"^(?:no|number|code)\.?\s*[:.-]?\s*", "", _normalise(line[label.end():]), flags=re.I)
        if value.lower() in {"", "and see below", "see below", "not available"}:
            return _review(line)
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./-]+", value):
            return _detected(value, line, 0.9)
        return _review(line)
    return _not_detected()


def _product_name(lines: list[str]) -> dict[str, Any]:
    excluded_terms = (
        "nutrition", "ingredient", "address", "fssai", "manufactur", "mfd", "mfg", "packed", "imported",
        "country", "consumer", "customer", "marketed", "registered", "proprietary", "contains", "flavour",
        "website", "email", "phone", "call", "batch", "lot", "mrp", "best before", "use by", "expiry",
        "storage", "scan", "participate", "per 100", "energy", "protein", "fat", "sodium", "carbohydrate", "sugar",
    )
    slogan = re.compile(r"\b(?:starts with|quality|directly from|cooked to|sprinkled with|add .* zest)\b", re.I)
    candidates: list[tuple[float, str]] = []
    for line in lines:
        lowered = line.lower()
        if any(term in lowered for term in excluded_terms) or slogan.search(line) or len(line) < 3 or len(line) > 50:
            continue
        words = line.split()
        if len(words) > 7 or not re.search(r"[A-Za-z]", line):
            continue
        score = 0.45
        if line.upper() == line and len(words) <= 4:
            score += 0.25
        if re.search(r"chips?|biscuit|noodle|tea|coffee|rice|soap|powder|drink|cereal", line, re.I):
            score += 0.2
        candidates.append((score, line))
    if not candidates:
        return _not_detected()
    candidates.sort(reverse=True)
    best_score, best = candidates[0]
    if len(candidates) > 1 and candidates[1][0] >= best_score - 0.05:
        return _review(" | ".join(candidate[1] for candidate in candidates[:4]))
    return _detected(best, best, min(best_score, 0.85))


def extract_declarations(ocr_result: dict[str, Any]) -> dict[str, Any]:
    raw_lines = ocr_result.get("text", [])
    lines = [_normalise(str(line)) for line in raw_lines if _normalise(str(line))]
    declarations = {field: _not_detected() for field in DECLARATION_FIELDS}
    declarations["product_name"] = _product_name(lines)
    declarations["manufacturer"] = _party(lines, r"manufactured\s*by|mfd\.?\s*by|mfg\.?\s*by|manufacturer")
    declarations["packer"] = _party(lines, r"packed\s*by|packer|marketed\s*by")
    declarations["importer"] = _party(lines, r"imported\s*by|importer")
    declarations["country_of_origin"] = _labelled_value(lines, r"country\s*of\s*origin|made\s*in|product\s*of|origin", r"(?P<value>[A-Za-z][A-Za-z ,.()-]{2,})")
    declarations["net_quantity"] = _quantity(lines)
    declarations["mrp"] = _money(lines, r"m\.?r\.?p|maximum\s+retail\s+price|max\s+retail\s+price")
    declarations["month_year_of_manufacture_or_packing"] = _date_or_period(lines, r"mfd\.?\s*(?:date)?(?!\s*by)|mfg\.?\s*(?:date)?(?!\s*by)|manufactured\s*on|packed\s*on|pkd\.?|date\s*of\s*(?:mfg|manufacture|packing)")
    declarations["best_before_or_use_by"] = _best_before(lines)
    declarations["consumer_care"] = _contact(lines)
    declarations["unit_sale_price"] = _money(lines, r"unit\s*(?:sale\s*)?price")
    declarations["batch_or_lot_number"] = _batch(lines)
    return {"inspection_id": ocr_result.get("inspection_id"), "status": "EXTRACTION_COMPLETED", "declarations": declarations}
