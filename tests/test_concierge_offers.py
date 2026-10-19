import pytest
from jsonschema import validate

from personal_assistant.concierge import OUTCOMES
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.state import Ledger


def offer(root, **changes):
    args = {"operation": "trip_offer", "data": {"trip_id": "synthetic", "offer_type": "arrival_logistics", **changes}}
    validate(args, SCHEMA["parameters"])
    return dispatch(root, args)


@pytest.mark.parametrize("outcome", sorted(OUTCOMES))
def test_outcome_matrix(tmp_path, outcome):
    assert offer(tmp_path)["allowed"]
    result = offer(tmp_path, action="record", outcome=outcome)
    assert result["action_type"] == "offer" and result["fields"]["history"][-1]["outcome"] == outcome
    assert "next" not in result and "next_note" not in result
    if outcome != "accepted":
        weather = offer(tmp_path, action="record", outcome=outcome,
                        offer_type="weather_leave_early", occurrence="n_1234abcd")
        assert "next" not in weather and "next_note" not in weather
    assert not offer(tmp_path)["allowed"]
    assert offer(tmp_path, trip_id="other")["allowed"] == (outcome != "opted_out")
    assert offer(tmp_path, offer_type="pickup")["allowed"]


@pytest.mark.parametrize("changes", [{"offer_type": "X"}, {"offer_type": "a"}, {"offer_type": "a1"},
    {"offer_type": "a" * 41}, {"outcome": "bad", "action": "record"}, {"action": "bad"}])
def test_invalid(tmp_path, changes):
    with pytest.raises(ValueError):
        dispatch(tmp_path, {"operation": "trip_offer", "data": {"trip_id": "synthetic", "offer_type": "food", **changes}})


def test_history_is_short(tmp_path):
    for i in range(23):
        offer(tmp_path, action="record", outcome="offered" if i == 0 else "declined")
    assert len(Ledger(tmp_path).get("action", "pa:offer:synthetic:arrival_logistics")["fields"]["history"]) == 20
