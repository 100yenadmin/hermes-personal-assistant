import pytest
from personal_assistant.privacy import safe_text


def test_shared_packing_survives_repeated_filtering():
    text = "Bring your laptop, charger and a passport copy. Meet at the east exit."
    assert safe_text(safe_text(text)) == text


@pytest.mark.parametrize("text", ["Passport: A12345678", "passport number A12345678",
                                 "passport # A12345678", "passport AB1234567",
                                 "Passport scan: private-document.pdf", "passport is 123456789",
                                 "passport ZX12QA345", "passport ZX12-QA345",
                                 "password: example-fixture", "Bearer synthetic-token"])
def test_private_values_still_omitted(text):
    assert safe_text(text) == "[Restricted detail omitted; consult the source dashboard.]"
