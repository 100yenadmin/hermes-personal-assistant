"""Shared conservative sensitive-value checks for phone briefs and call evidence.

This is not universal PII detection. Long digit runs are card-like unless an
exact, explicitly allowed callback fact identifies a valid E.164 phone number.
The callback exception is opt-in per field, never enabled for a person's name.
"""
import re
import unicodedata

_CREDENTIAL = re.compile(
    r'api[ _-]?key|authorization|\b(?:sk-|whsec_|xi-api-key|bearer\s)|password|secret|'
    r'\b(?:card\s*(?:number|details)|passport\s*(?:number|id))', re.I)
_CARD_VALUE = re.compile(r'\d{13,}')
_INSPECTION_SEPARATORS = re.compile(r'[\s\-\u2010-\u2015\u200b\u200c\u200d\ufeff]+')
_CALLBACK_FACT = re.compile(r'Callback(?: number)?:\s*\+(?P<number>[1-9][0-9]{7,14})', re.I)


def _card_checksum(digits):
    """Fail closed on a card-length Luhn value even if labelled as a callback.

    A rare phone/card ambiguity needs owner review, not automatic disclosure.
    Ordinary shorter callback numbers and non-card-like E.164 facts still work.
    """
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def restricted_phone_text(text, *, allow_callback=False):
    """Recognize known credential/card-like text without laundering it as a name."""
    normalized = unicodedata.normalize('NFKC', text)
    if _CREDENTIAL.search(normalized):
        return True
    callback = _CALLBACK_FACT.fullmatch(text.strip()) if allow_callback else None
    if callback:
        return _card_checksum(callback['number'])
    # Inspection only: never rewrite an approved field or echo this normalization.
    # Scan original string leaves, before JSON escapes hide tabs/newlines.
    return bool(_CARD_VALUE.search(_INSPECTION_SEPARATORS.sub('', normalized)))


def restricted_phone_value(value):
    """Inspect a validated public subtree without serializing/escaping its leaves."""
    if isinstance(value, dict):
        return any(restricted_phone_value(item) for item in value.values())
    if isinstance(value, list):
        return any(restricted_phone_value(item) for item in value)
    return restricted_phone_text(str(value))
