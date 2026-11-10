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
    assert "count each channel's slots per seven-day week from the window's first day (today unless the owner names a start), folding leftover days into the last week" in body
    assert "move or add slots until every week fits the cadence, and if these rules make that impossible, say so" in body
    assert "State a cadence only after that count" in body
