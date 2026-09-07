from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "rules.json"
with RULES_PATH.open(encoding="utf-8") as rules_file:
    RULES: list[dict[str, str]] = json.load(rules_file)


def _field(declarations: dict[str, Any], name: str) -> dict[str, Any]:
    value = declarations.get(name)
    return value if isinstance(value, dict) else {"value": None, "status": "not_detected"}


def _is_packaged(product_category: str) -> bool:
    return "packaged" in product_category.lower() or "commodity" in product_category.lower()


def _is_imported(declarations: dict[str, Any], context: dict[str, Any]) -> bool | None:
    explicit = context.get("is_imported")
    if isinstance(explicit, bool):
        return explicit
    origin = _field(declarations, "country_of_origin")
    if origin.get("status") == "detected":
        value = str(origin.get("value", "")).lower()
        if value and "india" not in value:
            return True
        if "india" in value:
            return False
    return None


def _best_before_applicable(product_category: str, context: dict[str, Any]) -> bool | None:
    explicit = context.get("best_before_applicable")
    if isinstance(explicit, bool):
        return explicit
    category = product_category.lower()
    if any(term in category for term in ("food", "beverage", "edible", "packaged commodities")):
        return True
    return None


def _confirmed_missing(rule: dict[str, str], context: dict[str, Any]) -> bool:
    missing = context.get("confirmed_missing_fields", [])
    if not isinstance(missing, list):
        return False
    aliases = {rule["field"]}
    if rule["field"] == "manufacturer_packer_importer":
        aliases.update({"manufacturer", "packer", "importer"})
    return any(field in aliases for field in missing)


def _country_applicability(declarations: dict[str, Any], context: dict[str, Any]) -> tuple[str, str, Any] | None:
    imported = _is_imported(declarations, context)
    if imported is False:
        return "NOT_APPLICABLE", "Country of origin is not required for a clearly domestic product.", None
    if imported is None:
        return "REVIEW_REQUIRED", "Import status cannot be established from the available inspection context and OCR.", _field(declarations, "country_of_origin").get("value")
    return None


def _best_before_rule_applicability(product_category: str, context: dict[str, Any]) -> tuple[str, str, Any] | None:
    applicable = _best_before_applicable(product_category, context)
    if applicable is False:
        return "NOT_APPLICABLE", "The available context does not establish this declaration as applicable.", None
    if applicable is None:
        return "REVIEW_REQUIRED", "Whether a best-before or use-by declaration applies cannot be established from the available context.", None
    return None


def _unit_price_applicability(declarations: dict[str, Any], context: dict[str, Any]) -> tuple[str, str, Any] | None:
    applicable = context.get("unit_sale_price_applicable")
    if not isinstance(applicable, bool):
        return "REVIEW_REQUIRED", "Applicability of unit sale price cannot be established from the available context.", _field(declarations, "unit_sale_price").get("value")
    if applicable is False:
        return "NOT_APPLICABLE", "Unit sale price was not established as applicable for this product.", None
    return None


def _applicability(rule: dict[str, str], declarations: dict[str, Any], product_category: str, context: dict[str, Any]) -> tuple[str, str, Any] | None:
    field = rule["field"]
    if not _is_packaged(product_category):
        return "NOT_APPLICABLE", "The product category is not established as a packaged commodity.", None
    if field == "country_of_origin":
        return _country_applicability(declarations, context)
    if field == "best_before_or_use_by":
        return _best_before_rule_applicability(product_category, context)
    if field == "unit_sale_price":
        return _unit_price_applicability(declarations, context)
    return None


def _status_for_rule(rule: dict[str, str], declarations: dict[str, Any], product_category: str, context: dict[str, Any]) -> tuple[str, str, Any]:
    field = rule["field"]
    applicable = _applicability(rule, declarations, product_category, context)
    if applicable:
        return applicable
    if _confirmed_missing(rule, context):
        return "VIOLATION", "The inspection context explicitly confirms that this applicable declaration is missing.", None
    if field == "manufacturer_packer_importer":
        candidates = [_field(declarations, name) for name in ("manufacturer", "packer", "importer")]
        if any(item.get("status") == "detected" and item.get("value") for item in candidates):
            return "COMPLIANT", "A manufacturer, packer, or importer declaration was extracted.", next(item.get("value") for item in candidates if item.get("status") == "detected")
        if any(item.get("status") == "needs_review" for item in candidates):
            return "REVIEW_REQUIRED", "A responsible-party label was found, but its value is uncertain.", None
        return "REVIEW_REQUIRED", "No responsible-party declaration was confidently extracted; absence cannot be confirmed from OCR alone.", None
    declaration = _field(declarations, field)
    if declaration.get("status") == "detected" and declaration.get("value") not in (None, ""):
        return "COMPLIANT", "The required declaration was extracted with supporting OCR evidence.", declaration.get("value")
    if declaration.get("status") == "needs_review":
        return "REVIEW_REQUIRED", "The declaration label is present, but its value is unreadable or ambiguous.", None
    return "REVIEW_REQUIRED", "The declaration was not confidently detected; OCR failure is not treated as proof of non-compliance.", None


def _normalise_evidence_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _evidence_for(source_text: Any, confidence: Any, detections: list[dict[str, Any]]) -> dict[str, Any]:
    if not source_text:
        return {"source_text": None, "confidence": confidence, "evidence_bbox": None}
    source = _normalise_evidence_text(source_text)
    source_segments = {_normalise_evidence_text(segment) for segment in str(source_text).split("|")}
    for detection in detections:
        detected_text = _normalise_evidence_text(detection.get("text"))
        if detected_text and len(detected_text) >= 4 and (detected_text == source or detected_text in source_segments or source in detected_text):
            return {
                "source_text": source_text,
                "confidence": confidence if confidence is not None else detection.get("confidence"),
                "evidence_bbox": detection.get("bbox"),
            }
    return {"source_text": source_text, "confidence": confidence, "evidence_bbox": None}


def _declaration_evidence(field: str, declarations: dict[str, Any]) -> dict[str, Any]:
    if field == "manufacturer_packer_importer":
        for candidate in ("manufacturer", "packer", "importer"):
            declaration = _field(declarations, candidate)
            if declaration.get("status") == "detected":
                return declaration
        return _field(declarations, "manufacturer")
    return _field(declarations, field)


def check_compliance(
    declarations: dict[str, Any],
    product_category: str,
    context: dict[str, Any] | None = None,
    detections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = context or {}
    checks: list[dict[str, Any]] = []
    for rule in RULES:
        check_status, reason, value = _status_for_rule(rule, declarations, product_category, context)
        declaration = _declaration_evidence(rule["field"], declarations)
        evidence = _evidence_for(declaration.get("source_text"), declaration.get("confidence"), detections or [])
        checks.append({
            "rule_id": rule["rule_id"],
            "field": rule["field"],
            "field_name": rule["field"],
            "status": check_status,
            "value": value,
            "reason": reason,
            "severity": rule["severity"],
            "rule_version": rule["rule_version"],
            "source": rule["source"],
            **evidence,
        })

    applicable = [check for check in checks if check["status"] != "NOT_APPLICABLE"]
    violations = [check for check in applicable if check["status"] == "VIOLATION"]
    reviews = [check for check in applicable if check["status"] == "REVIEW_REQUIRED"]
    compliant = [check for check in applicable if check["status"] == "COMPLIANT"]
    score = round((len(compliant) / len(applicable)) * 100) if applicable else 0
    if violations:
        overall_status = "NON_COMPLIANT"
    elif reviews:
        overall_status = "REVIEW_REQUIRED"
    else:
        overall_status = "COMPLIANT"
    return {"overall_status": overall_status, "compliance_score": score, "checks": checks}
