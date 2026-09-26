import pytest

from caller_app.phone import InvalidPhoneNumber, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+49 151 12345678", "+49" + "15112345678"),
        ("0151 12345678", "+49" + "15112345678"),
        ("+43-664-1234567", "+43" + "6641234567"),
    ],
)
def test_normalizes_valid_numbers_to_e164(raw: str, expected: str):
    assert normalize_phone(raw, default_region="DE") == expected


@pytest.mark.parametrize("raw", ["", "123", "+490", "not-a-phone"])
def test_rejects_invalid_phone_numbers(raw: str):
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw, default_region="DE")
