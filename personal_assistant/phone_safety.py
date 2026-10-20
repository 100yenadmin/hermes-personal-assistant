"""Mapped, joined-field card inspection, not universal PII detection.

Inspection keeps only normalized decimal digits, irrespective of punctuation,
words or field boundaries. Every 13–19 digit window is checked, then mapped
back to original spans. Only a separately validated typed callback can exempt
a window wholly inside that one field; labels alone grant no exception.
"""
import re
import unicodedata

_CREDENTIAL = re.compile(
    r'api[ _-]?key|authorization|\b(?:sk-|whsec_|xi-api-key|bearer\s)|password|secret|'
    r'\b(?:card\s*(?:number|details)|passport\s*(?:number|id))', re.I)
_CALLBACK = re.compile(r'\+[1-9][0-9]{7,14}')
COMPILE_REDACTION_FIELDS = ('purpose', 'may_share', 'limits', 'to.name')


class RestrictedContent(ValueError):
    def __init__(self, fields):
        self.fields = sorted(set(fields))
        super().__init__('restricted content in ' + ', '.join(self.fields))


def display_name(value):
    """Only a short, single-line human display name may become spoken text."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 40
            or not all(ch.isalpha() or ch in " '-’" for ch in value)
            or not any(ch.isalpha() for ch in value)):
        return None
    return value.strip()


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


def valid_callback(value):
    if not isinstance(value, str) or _CALLBACK.fullmatch(value) is None:
        return False
    digits = value[1:]
    return not any(_card_checksum(digits[start:start + length])
                   for length in range(13, 20) for start in range(len(digits) - length + 1))


def phone_card_spans(texts, *, callbacks=()):
    """Return implicated original spans for one joined digit stream, in O(n).

    Two parity prefix sums give each bounded Luhn window a constant-time check.
    Difference marks union overlapping windows without retaining every match.
    Character positions survive Unicode normalization and cross-field joins.
    """
    digits, positions = [], []
    safe_callbacks = {index for index in callbacks if valid_callback(texts[index])}
    for field, text in enumerate(texts):
        for offset, char in enumerate(text):
            for normalized in unicodedata.normalize('NFKC', char):
                if normalized.isdecimal():
                    digits.append(unicodedata.decimal(normalized))
                    positions.append((field, offset))
    prefixes = ([0], [0])
    for index, digit in enumerate(digits):
        doubled = digit * 2
        doubled -= 9 if doubled > 9 else 0
        for parity in (0, 1):
            prefixes[parity].append(prefixes[parity][-1] + (doubled if index % 2 == parity else digit))
    marks = [0] * (len(digits) + 1)
    for length in range(13, 20):
        for start in range(len(digits) - length + 1):
            end = start + length
            prefix = prefixes[end % 2]
            if (prefix[end] - prefix[start]) % 10:
                continue
            first_field, last_field = positions[start][0], positions[end - 1][0]
            if first_field == last_field and first_field in safe_callbacks:
                continue
            marks[start] += 1
            marks[end] -= 1
    spans = [[] for _ in texts]
    active = 0
    for index, (field, offset) in enumerate(positions):
        active += marks[index]
        if active:
            if spans[field]:
                spans[field][-1] = (spans[field][-1][0], offset + 1)
            else:
                spans[field].append((offset, offset + 1))
    return spans


def restricted_phone_fields(texts, *, callbacks=()):
    spans = phone_card_spans(texts, callbacks=callbacks)
    return {index for index, text in enumerate(texts)
            if spans[index] or _CREDENTIAL.search(unicodedata.normalize('NFKC', text))}


def restricted_phone_text(text):
    return bool(restricted_phone_fields([text]))


def restricted_phone_value(value):
    """Inspect all leaves together, before JSON escaping or per-field filtering."""
    def leaves(item):
        if isinstance(item, dict):
            return [leaf for child in item.values() for leaf in leaves(child)]
        if isinstance(item, list):
            return [leaf for child in item for leaf in leaves(child)]
        return [str(item)]
    return bool(restricted_phone_fields(leaves(value)))
