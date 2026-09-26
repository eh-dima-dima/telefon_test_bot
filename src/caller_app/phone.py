from __future__ import annotations

import re

import phonenumbers


class InvalidPhoneNumber(ValueError):
    pass


def normalize_phone(raw: str, *, default_region: str = "DE") -> str:
    value = raw.strip()
    if not value:
        raise InvalidPhoneNumber("phone number is empty")
    try:
        parsed = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneNumber("phone number cannot be parsed") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber("phone number is not valid")
    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", e164):
        raise InvalidPhoneNumber("phone number is not E.164")
    return e164
