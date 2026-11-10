"""Pins the 0.17 lab-miss rules: prices tied to the exact item, stops as seen, counted cadence."""
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def text(name):
    return " ".join((SKILLS / name / "SKILL.md").read_text().split())


def test_restaurant_price_is_for_the_exact_course():
    assert "that exact course, plan or menu item" in text("restaurant-reservations")
    assert "a neighbouring course's price is not this one's" in text("restaurant-reservations")


def test_snack_price_and_stop_come_from_the_page():
    body = text("food-delivery-to-hotel")
    assert "Quote an item's price only where the page shows it beside that item" in body
    assert "name a stopping point (login, address, cart) only as the page you last read shows it" in body


def test_content_cadence_is_counted_per_week():
    body = text("content-admin")
    assert "count each channel's slots in every seven-day week from the window's first day" in body
    assert "state a cadence only after that count" in body
