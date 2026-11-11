"""Pins the 0.17 lab-miss rules: prices tied to the exact item, stops as seen, counted cadence."""
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def text(name):
    return " ".join((SKILLS / name / "SKILL.md").read_text().split())


def test_restaurant_price_is_for_the_exact_course():
    body = text("restaurant-reservations")
    assert "when you tie it to a course, plan or menu item, for that exact one" in body
    assert "a neighbouring course's price is not this one's" in body


def test_snack_price_and_stop_come_from_the_page():
    body = text("food-delivery-to-hotel")
    assert "Quote an item's price only where the page shows it beside that item" in body
    assert "Never present your own sum as a cart or verified subtotal" in body
    assert "without a cart read, say the subtotal was not read" in body
    assert "Name a stopping point (login, address, cart) only from a page you read" in body


def test_content_cadence_is_counted_per_week():
    body = text("content-admin")
    assert "Before recording any slot, split the window into seven-day weeks from its first day (today unless the owner names a start), folding leftover days into the last week" in body
    assert "Put each slot under the week its date falls in and count each channel's slots per week" in body
    # The reply shows the count it was built on, so a miscount is visible (0.19 wave, s38 r003).
    assert "Reply with the calendar grouped by those weeks: each week's dates, its slots in date order, and each channel's count for that week" in body
    assert "move or add slots until every week fits the cadence, and if these rules make that impossible, say so" in body
    assert "State a cadence only after that count" in body
    # A new slot at an hour that has gone is not a plan; an event today gets a question, not a move (#207 review).
    assert "a slot in quiet hours, a new slot at a time already past, or a slot past the window" in body
    assert "ask once if it is unknown, conflicts with quiet hours, or has passed on the day of an event you must cover" in body
