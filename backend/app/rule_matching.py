"""Pure rule-matching/rendering logic shared by rule CRUD (app.rules) and the delivery
pipeline (app.delivery) — no DB session or FastAPI routing lives here."""

import math
import re
from datetime import datetime, timezone

from fastapi import HTTPException

from app.models import MappingRule

BUILTIN_PLACEHOLDERS = {"recipient", "order_ref", "original_text", "date"}
PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ "
    "!\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM_EXTENDED = set("^{}\\[~]|€")


def validate_rule(fields: dict) -> None:
    if fields["match_type"] == "regex":
        try:
            compiled = re.compile(fields["match_value"])
        except re.error as error:
            raise HTTPException(status_code=422, detail=f"Invalid regular expression: {error}") from error
        available = BUILTIN_PLACEHOLDERS | set(compiled.groupindex)
    else:
        available = BUILTIN_PLACEHOLDERS
    unknown = sorted(set(PLACEHOLDER_PATTERN.findall(fields["outbound_template"])) - available)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Template uses unavailable placeholders: {', '.join(unknown)}")


def match_rule(rule: MappingRule | dict, text: str):
    match_type = rule.match_type if isinstance(rule, MappingRule) else rule["match_type"]
    match_value = rule.match_value if isinstance(rule, MappingRule) else rule["match_value"]
    case_sensitive = rule.case_sensitive if isinstance(rule, MappingRule) else rule["case_sensitive"]
    flags = 0 if case_sensitive else re.IGNORECASE
    if match_type == "regex":
        match = re.search(match_value, text, flags)
        return match.groupdict() if match else None
    source = text if case_sensitive else text.casefold()
    expected = match_value if case_sensitive else match_value.casefold()
    matched = {
        "contains": expected in source,
        "starts_with": source.startswith(expected),
        "exact": source == expected,
    }[match_type]
    return {} if matched else None


def render_template(template: str, values: dict[str, str]) -> str:
    return PLACEHOLDER_PATTERN.sub(lambda match: values[match.group(1)], template)


def sms_segments(text: str) -> tuple[int, str, int]:
    if all(character in GSM_BASIC or character in GSM_EXTENDED for character in text):
        units = sum(2 if character in GSM_EXTENDED else 1 for character in text)
        return (1 if units <= 160 else math.ceil(units / 153), "GSM-7", units)
    units = len(text)
    return (1 if units <= 70 else math.ceil(units / 67), "Unicode", units)


def values_for(text: str, recipient: str, order_ref: str | None, groups: dict[str, str]) -> dict[str, str]:
    return {
        "recipient": recipient,
        "order_ref": order_ref or "",
        "original_text": text,
        "date": datetime.now(timezone.utc).date().isoformat(),
        **groups,
    }
