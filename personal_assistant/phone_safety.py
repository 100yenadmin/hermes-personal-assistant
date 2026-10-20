"""Mapped, joined-field card inspection, not universal PII detection.

Inspection chains normalized decimal digits across letter-free gaps, including
field boundaries. A Unicode letter ends a chain. Every 13–19 digit window in
each chain is checked, then mapped back to original spans. Validated numeric
facts remain in the digit stream,
so typed data cannot hide a mixed free-text/card window. Numeric-only typed
choices are interpreted by their validated semantics, not as payment values.
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


def phone_card_spans(texts, *, callbacks=(), typed_numeric=()):
    """Return implicated original spans for letter-bounded digit chains, in O(n).

    Two parity prefix sums give each bounded Luhn window a constant-time check.
    Difference marks union overlapping windows without retaining every match.
    Character positions survive Unicode normalization and cross-field joins.
    """
    digits, positions, chain_starts = [], [], []
    chain_start = 0
    safe_callbacks = {index for index in callbacks if valid_callback(texts[index])}
    numeric_fields = set(typed_numeric) | safe_callbacks
    for field, text in enumerate(texts):
        for offset, char in enumerate(text):
            for normalized in unicodedata.normalize('NFKC', char):
                if normalized.isdecimal():
                    digits.append(unicodedata.decimal(normalized))
                    positions.append((field, offset))
                    chain_starts.append(chain_start)
                elif unicodedata.category(normalized).startswith('L'):
                    chain_start = len(digits)
    prefixes = ([0], [0])
    free_digits = [0]
    for index, digit in enumerate(digits):
        free_digits.append(free_digits[-1] + (positions[index][0] not in numeric_fields))
        doubled = digit * 2
        doubled -= 9 if doubled > 9 else 0
        for parity in (0, 1):
            prefixes[parity].append(prefixes[parity][-1] + (doubled if index % 2 == parity else digit))
    marks = [0] * (len(digits) + 1)
    for length in range(13, 20):
        for start in range(len(digits) - length + 1):
            end = start + length
            if start < chain_starts[end - 1]:
                continue  # Words, not punctuation/whitespace/field joins, break chains.
            prefix = prefixes[end % 2]
            if (prefix[end] - prefix[start]) % 10:
                continue
            # The caller validates typed dates/times/counts; callbacks also get
            # their own intrinsic Luhn-window check. Never REMOVE their digits:
            # a window touching ANY free-text digit must still be inspected.
            if free_digits[end] == free_digits[start]:
                continue
            marks[start] += 1
            marks[end] -= 1
    spans = [[] for _ in texts]
    active, previous = 0, None
    for index, (field, offset) in enumerate(positions):
        active += marks[index]
        if active:
            if previous == (field, chain_starts[index]):
                spans[field][-1] = (spans[field][-1][0], offset + 1)
            else:
                spans[field].append((offset, offset + 1))
            previous = (field, chain_starts[index])
        else:
            previous = None
    return spans


def restricted_phone_spans(texts, *, callbacks=(), typed_numeric=()):
    """Card spans plus conservative credential tails, with original offsets.

    Unstructured credentials have no trustworthy value terminator: preserve the
    preceding speech, but omit the matched label and everything after it.
    """
    spans = phone_card_spans(texts, callbacks=callbacks, typed_numeric=typed_numeric)
    for index, text in enumerate(texts):
        normalized, offsets = [], []
        for offset, char in enumerate(text):
            part = unicodedata.normalize('NFKC', char)
            normalized.extend(part)
            offsets.extend([offset] * len(part))
        match = _CREDENTIAL.search(''.join(normalized))
        if match:
            spans[index].append((offsets[match.start()], len(text)))
    return spans


def restricted_phone_fields(texts, *, callbacks=(), typed_numeric=()):
    spans = restricted_phone_spans(texts, callbacks=callbacks, typed_numeric=typed_numeric)
    return {index for index, part in enumerate(spans) if part}


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
