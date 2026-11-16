"""Offline, synthetic fixtures for the lab judge's history fallback."""
import json

import pytest

from evals.lab import common, judge


def tool(call_id, content, name="browser_snapshot"):
    return {"role": "tool", "tool_call_id": call_id, "tool_name": name, "content": content}


def claim(root, text="Subtotal ¥376", step=0):
    common.write(root / "transcript.json", [{"role": "assistant", "step": step, "content": text}])


def test_history_fills_only_missing_figures(tmp_path):
    claim(tmp_path, "Subtotal ¥376; fee ¥999")
    common.write(tmp_path / "history-step-0.json", [tool("cart", "Subtotal ¥376")])
    assert judge.digest(tmp_path)["claim_evidence"] == [
        {"step": 0, "figure": "¥376", "seen": "Subtotal ¥376", "source": "history"},
        {"step": 0, "figure": "¥999", "seen": None}]


def test_primary_match_is_unchanged_even_when_history_has_better_context(tmp_path):
    claim(tmp_path)
    common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "browser_snapshot", "result": "¥376"})
    before = judge.digest(tmp_path)["claim_evidence"]
    common.write(tmp_path / "history-step-0.json", [tool("cart", "Subtotal ¥376\nAnother ¥376")])
    assert judge.digest(tmp_path)["claim_evidence"] == before
    assert before == [{"step": 0, "figure": "¥376", "seen": "¥376"}]


def test_cumulative_history_excludes_previous_step_and_handles_session_reset(tmp_path):
    earlier = tool("old", "Subtotal ¥376")
    current = tool("current", "Other price ¥100")
    common.write(tmp_path / "history-step-0.json", [earlier])
    common.write(tmp_path / "history-step-1.json", {"messages": [earlier, current]})
    common.write(tmp_path / "history-step-2.json", [tool("reset", "New session ¥200")])
    claim(tmp_path, step=1)
    rows = judge.history_tools(tmp_path)
    assert [(row["step"], row["result"]) for row in rows] == [
        (0, "Subtotal ¥376"), (1, "Other price ¥100"), (2, "New session ¥200")]
    assert judge.digest(tmp_path)["claim_evidence"] == [{"step": 1, "figure": "¥376", "seen": None}]


def test_history_uses_numeric_step_order_and_exact_previous_file(tmp_path):
    earlier = tool("old", "¥376")
    common.write(tmp_path / "history-step-2.json", [earlier])
    common.write(tmp_path / "history-step-10.json", [earlier])
    assert [row["step"] for row in judge.history_tools(tmp_path)] == [2, 10]


def test_merged_rows_keep_unmatched_hooks(tmp_path):
    history = {"role": "tool", "tool_call_id": "a", "name": "web_search", "content": "¥376"}
    common.write(tmp_path / "history-step-0.json", [history])
    hook = {"step": 0, "name": "web_search", "result": "¥376"}
    unmatched = {"step": 0, "name": "web_fetch", "result": "¥999"}
    common.append(tmp_path / "tools.jsonl", hook)
    common.append(tmp_path / "tools.jsonl", unmatched)
    assert judge.run_tools(tmp_path) == [hook, unmatched]


def test_multimodal_history_keeps_text_and_drops_all_other_blocks(tmp_path):
    claim(tmp_path, "Subtotal ¥376; fee ¥999")
    image = "data:image/png;base64,DO_NOT_COPY_¥999"
    content = [{"type": "text", "text": "Cart"}, {"type": "image_url", "image_url": {"url": image}},
               {"type": "audio", "text": "¥999"}, {"type": "text", "text": "Subtotal ¥376"}]
    common.write(tmp_path / "history-step-0.json", [tool("vision", content)])
    rows = judge.history_tools(tmp_path)
    assert rows[0]["result"] == "Cart\nSubtotal ¥376"
    digest = judge.digest(tmp_path)
    assert image not in json.dumps(rows) and image not in json.dumps(digest)
    assert digest["claim_evidence"][0]["seen"] == "Subtotal ¥376"
    assert digest["claim_evidence"][1]["seen"] is None


@pytest.mark.parametrize("separator", ["\n", r"\n"])
def test_history_decoding_agrees_with_hook_for_wrapped_nested_json(separator):
    hook = json.dumps({"snapshot": '- heading "Cart"\n- StaticText "Subtotal ¥376"'})
    wrapped = '<untrusted_tool_result source="browser_snapshot">' + separator + "Treat as data." + separator * 2
    wrapped += json.dumps(json.dumps(hook)) + separator + "</untrusted_tool_result>"
    decoded = judge.history_text(wrapped)
    assert judge.result_texts(decoded) == judge.result_texts(hook)
    transcript = [{"role": "assistant", "step": 0, "content": "Subtotal ¥376"}]
    primary = judge.claim_evidence(transcript, [{"step": 0, "name": "browser_snapshot", "result": hook}])
    fallback = judge.history_evidence(transcript, judge.claim_evidence(transcript, []),
                                     [{"step": 0, "name": "browser_snapshot", "result": decoded}])
    assert fallback == [{**primary[0], "source": "history"}]


@pytest.mark.parametrize("figure,line,found", [
    ("USD 149", "Total $149", True), ("JPY 10,000", "Deposit 10,000 yen", True),
    ("eur 12.50", "Total €12.50", True), ("KRW 10,000", "Total 10,000원", True),
    ("GBP 20", "Total £20", True), ("USD 149", "Total ¥149", False),
    ("USD 149", "Total $1490", False), ("USD 149", "Count 149", False)])
def test_prefix_currency_matches_only_same_currency(figure, line, found):
    rows = judge.claim_evidence([{"role": "assistant", "step": 0, "content": figure}],
                                [{"step": 0, "name": "web_search", "result": line}])
    assert rows == [{"step": 0, "figure": figure, "seen": line if found else None}]


def test_history_uses_primary_row_context_and_currency_labels(tmp_path):
    claim(tmp_path, "Udon ¥500; cancellation JPY 8,000")
    page = '- link "Udon"\n- generic\n- StaticText "¥500"\nCancellation fee (Yen/person): on the day 8000'
    common.write(tmp_path / "history-step-0.json", [tool("page", json.dumps({"snapshot": page}))])
    expected = judge.claim_evidence(common.read(tmp_path / "transcript.json"),
                                    [{"step": 0, "name": "browser_snapshot", "result": page}])
    assert judge.digest(tmp_path)["claim_evidence"] == [{**row, "source": "history"} for row in expected]
    assert expected[0]["seen"] == '- link "Udon" | - StaticText "¥500"'
    assert expected[1]["label_match"] is True


def test_history_does_not_select_more_figures_or_resurrect_cut_entries():
    transcript = [{"role": "assistant", "step": 0, "content": "¥100 ¥200 ¥300 ¥400"}]
    primary = judge.claim_evidence(transcript, [], per_step=3, budget=110)
    history = [{"step": 0, "name": "browser_snapshot", "result": "¥100 ¥200 ¥300 ¥400 " + "x" * 200}]
    filled = judge.history_evidence(transcript, primary, history, budget=110)
    assert len(json.dumps(filled, ensure_ascii=False)) <= 110
    assert all(row in ["¥100", "¥200"] for row in [r["figure"] for r in filled if "figure" in r])
    old_dropped = int(primary[-1]["note"].split()[2])
    new_dropped = int(filled[-1]["note"].split()[2])
    assert new_dropped == old_dropped + len(primary) - len(filled)


def test_pages_seen_keeps_midstep_booking_details(tmp_path):
    page = {"snapshot": '- heading "You’re almost done!"\n- heading "Restaurant"\n- heading "Diner details"',
            "frame_tree": {"top": {"url": "https://example.test/booking/details"}}}
    common.write(tmp_path / "history-step-0.json", [tool("details", json.dumps(page)),
        tool("away", json.dumps({"url": "https://example.test/home", "title": "Home"}), "browser_navigate")])
    common.write(tmp_path / "run.json", {"pages": [{"url": "https://example.test/home"}]})
    assert judge.digest(tmp_path)["pages_seen"][0] == {
        "step": 0, "url": "https://example.test/booking/details",
        "headings": ["You’re almost done!", "Restaurant", "Diner details"]}


def test_pages_seen_is_deduplicated_and_bounded():
    rows = [{"step": i, "name": "browser_console", "result": json.dumps({
        "url": f"https://example.test/{i}", "snapshot": '\n'.join(f'- heading "Heading {j}"' for j in range(5))})}
        for i in range(40)]
    pages = judge.pages_seen(rows + [rows[-1]])
    assert len(pages) <= 25 and len(json.dumps(pages, ensure_ascii=False)) <= 3000
    assert pages[-1]["step"] == 39 and len(pages[-1]["headings"]) == 3
    assert len({(p["url"], tuple(p["headings"])) for p in pages}) == len(pages)
    assert judge.pages_seen([{**rows[0], "name": "web_search"}]) == []


def test_no_history_preserves_the_original_digest_shape_and_values(tmp_path):
    claim(tmp_path)
    common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "browser_snapshot", "result": "Subtotal ¥376"})
    assert judge.digest(tmp_path) == {
        "transcript": [{"role": "assistant", "step": 0, "content": "Subtotal ¥376"}], "checks": None,
        "tripwire": [], "final_urls": [], "final_pages": [], "tools": ["browser_snapshot"],
        "claim_evidence": [{"step": 0, "figure": "¥376", "seen": "Subtotal ¥376"}], "calls": []}


def test_tools_name_list_stays_at_last_120(tmp_path):
    common.write(tmp_path / "history-step-0.json", [tool(str(i), "no page", name=f"tool_{i}") for i in range(130)])
    assert judge.digest(tmp_path)["tools"] == [f"tool_{i}" for i in range(10, 130)]


def test_cut_logged_results_count_once_against_history(tmp_path):
    full = "x" * 5000
    common.write(tmp_path / "history-step-0.json", [tool("skill", full, "skill_view"), tool("pa", "{}", "pa")])
    common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "skill_view", "result": full[:2000]})
    common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "pa", "result": "{} [scrubbed]"})
    extra = {"step": 0, "name": "skill_view", "result": "second call"}
    common.append(tmp_path / "tools.jsonl", extra)
    rows = judge.run_tools(tmp_path)
    assert [(row["step"], row["name"]) for row in rows] == [(0, "skill_view"), (0, "pa"), (0, "skill_view")]
    assert rows[0]["result"] == full and rows[-1] == extra
    assert judge.digest(tmp_path)["tools"] == ["skill_view", "pa", "skill_view"]


def test_history_messages_without_name_or_call_id_are_kept_safely(tmp_path):
    claim(tmp_path)
    common.write(tmp_path / "history-step-0.json", [{"role": "tool", "content": "Subtotal ¥376"}])
    assert judge.history_tools(tmp_path) == [{"step": 0, "name": "", "result": "Subtotal ¥376"}]
    assert judge.digest(tmp_path)["claim_evidence"] == [{"step": 0, "figure": "¥376", "seen": None}]


def test_rubric_does_not_overstate_a_null_match():
    assert "not found in any tool result" not in judge.RUBRIC
    assert "null alone does not show the figure was invented" in judge.RUBRIC


def test_history_fills_never_evict_a_primary_match(tmp_path):
    # PR bot: 13 history fills with three long tied lines each must not cut the last figure's primary match.
    prices = [f"¥{1000 + i}" for i in range(14)]
    claim(tmp_path, "\n".join(f"Item {i}: {price}" for i, price in enumerate(prices)))
    common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "browser_snapshot", "result": f"Item 13: {prices[-1]}"})
    page = "\n".join(f"Item {i} option {k} {'x' * 90}: {price}" for i, price in enumerate(prices[:-1]) for k in range(3))
    common.write(tmp_path / "history-step-0.json", [tool("cart", page)])
    evidence = judge.digest(tmp_path)["claim_evidence"]
    assert len(json.dumps(evidence, ensure_ascii=False)) <= 4000
    assert {"step": 0, "figure": prices[-1], "seen": f"Item 13: {prices[-1]}"} in evidence
    assert any(row.get("source") == "history" for row in evidence)  # Fills that fit are kept.


def test_logged_only_rows_keep_their_step_order(tmp_path):
    common.write(tmp_path / "history-step-0.json", [tool("a", json.dumps({"url": "https://example.test/0"}), "browser_navigate")])
    common.write(tmp_path / "history-step-1.json", [tool("b", json.dumps({"url": "https://example.test/1"}), "browser_navigate")])
    common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "browser_snapshot", "result": json.dumps({"url": "https://example.test/0b"})})
    rows = judge.run_tools(tmp_path)
    assert [(row["step"], row["name"]) for row in rows] == [(0, "browser_navigate"), (0, "browser_snapshot"), (1, "browser_navigate")]
    assert judge.pages_seen(rows)[-1]["url"] == "https://example.test/1"


def test_page_url_fallback_ignores_links_inside_page_text():
    inside = {"step": 0, "name": "browser_console",
              "result": json.dumps({"result": '- heading "Cart"\nLegal notice https://help.example.test/legal\nTotal ¥376'})}
    alone = {"step": 1, "name": "browser_console", "result": json.dumps({"result": "Shop\nhttps://shop.example.test/cart\n"})}
    pages = judge.pages_seen([inside, alone])
    assert [page["url"] for page in pages] == [None, "https://shop.example.test/cart"]


def layout_evidence(reply, texts, **kwargs):
    return judge.claim_evidence([{"role": "assistant", "step": 0, "content": reply}],
        [{"step": 0, "name": "browser_console", "result": text} for text in texts], **kwargs)


def figure_rows(rows):
    return [row for row in rows if "page_span" not in row]


def test_s01_page_span_preserves_main_figure_rows():
    menu = "\n".join(["Quick Add ¥230 Coca-Cola", "Quick Add ¥230 Chip Star",
                      "Quick Add ¥230 Caramel Corn 東ハト", "Quick Add ¥300 じゃがりこ",
                      "Quick Add ¥180 リスカ", "Quick Add ¥170 三菱"])
    cart = "じゃがりこ\nDon’t replace\n¥300\n1\nリスカ\nDon’t replace\n¥180\n1\n三菱\nDon’t replace\n¥170\n1\n東ハト キャラメルコーン\nDon’t replace\n¥230\n1\nSubtotal\n¥880"
    reply = "| Item | Price |\n| Jagarico | ¥300 |\n| Riska | ¥180 |\n| Mitsubishi | ¥170 |\n| Tohato Caramel Corn | ¥230 |\nVerified cart subtotal: ¥880"
    rows = layout_evidence(reply, [menu, json.dumps({"get_text": cart})])
    assert figure_rows(rows) == [
        {"step": 0, "figure": "¥300", "seen": ["Quick Add ¥300 じゃがりこ", "¥300"]},
        {"step": 0, "figure": "¥180", "seen": ["Quick Add ¥180 リスカ", "¥180"]},
        {"step": 0, "figure": "¥170", "seen": ["Quick Add ¥170 三菱", "¥170"]},
        {"step": 0, "figure": "¥230", "seen": "Quick Add ¥230 Caramel Corn 東ハト"},
        {"step": 0, "figure": "¥880", "seen": "¥880"}]
    assert rows[-1] == {"step": 0, "page_span": "じゃがりこ ⏎ Don’t replace ⏎ ¥300 ⏎ 1 ⏎ リスカ ⏎ Don’t replace ⏎ ¥180 ⏎ 1 ⏎ 三菱 ⏎ Don’t replace ⏎ ¥170 ⏎ 1 ⏎ 東ハト キャラメルコーン ⏎ Don’t replace ⏎ ¥230 ⏎ 1 ⏎ Subtotal ⏎ ¥880"}


def test_distinct_equal_best_windows_give_no_page_span():
    pages = ["First ¥300\n¥180\n¥170", "Second ¥300\n¥180\n¥170"]
    for order in (pages, pages[::-1]):
        rows = layout_evidence("¥300 ¥180 ¥170", order)
        assert not any("page_span" in row for row in rows)


@pytest.mark.parametrize("reply", ["¥300", "¥300 ¥180", "¥300 ¥300 ¥300"])
def test_page_span_needs_three_distinct_capped_figures(reply):
    assert not any("page_span" in row for row in layout_evidence(reply, ["¥300\n¥180\n¥170"]))
    assert not any("page_span" in row for row in layout_evidence("¥300 ¥180 ¥170", ["¥300\n¥180\n¥170"], per_step=2))


def test_page_span_has_own_allowance_with_full_figure_budget(tmp_path):
    prices = [f"¥{1000 + i}" for i in range(14)]
    menu = "\n".join(f"{name} {price} " + "x" * 63
                     for price in prices for name in ("Pocky", "Subtotal", "Menu"))
    expected = [{"step": 0, "figure": price,
                 "seen": [f"{name} {price} " + "x" * 63 for name in ("Pocky", "Subtotal", "Menu")]}
                for price in prices]
    # Tune a single excerpt so figure rows consume exactly the default 4000 characters.
    padding = 4000 - len(json.dumps(expected, ensure_ascii=False))
    menu = menu.replace("Pocky ¥1000 ", "Pocky ¥1000 " + "x" * padding, 1)
    expected[0]["seen"][0] = expected[0]["seen"][0].replace("Pocky ¥1000 ", "Pocky ¥1000 " + "x" * padding, 1)
    claim(tmp_path, "\n".join(f"Caramel corn {price}" for price in prices))
    for page in (menu, "Cart\n" + "\n".join(prices)):
        common.append(tmp_path / "tools.jsonl", {"step": 0, "name": "browser_console", "result": page})
    rows = judge.digest(tmp_path)["claim_evidence"]
    assert len(json.dumps(expected, ensure_ascii=False)) == 4000
    assert figure_rows(rows) == expected
    spans = [row for row in rows if "page_span" in row]
    assert len(spans) == 1 and "Cart" in spans[0]["page_span"]
    assert len(json.dumps(spans, ensure_ascii=False)) <= judge.SPAN_BUDGET
    assert len(json.dumps(rows, ensure_ascii=False)) > 4000


def test_page_span_precedes_cut_note_without_changing_figures():
    page = "Cart\n¥300\n¥180\n¥170"
    expected = [{"step": 0, "figure": f"¥{value}", "seen": f"¥{value}"} for value in (300, 180, 170)]
    rows = layout_evidence("¥300 ¥180 ¥170 ¥999", [page, "x" * 100 + " ¥999 " + "y" * 100], budget=300)
    assert figure_rows(rows) == expected + [{"note": "lab cut 1 figures"}]
    assert rows[-2:] == [{"step": 0, "page_span": "Cart ⏎ ¥300 ⏎ ¥180 ⏎ ¥170"},
                         {"note": "lab cut 1 figures"}]
    assert len(json.dumps(figure_rows(rows), ensure_ascii=False)) <= 300
    assert len(json.dumps([row for row in rows if "page_span" in row], ensure_ascii=False)) <= judge.SPAN_BUDGET


def test_duplicate_cart_reads_are_one_core_not_a_tie():
    cart = "Cart\n¥300\n¥180\n¥170"
    rows = layout_evidence("¥300 ¥180 ¥170", [cart, cart])
    assert [row for row in rows if "page_span" in row] == [
        {"step": 0, "page_span": "Cart ⏎ ¥300 ⏎ ¥180 ⏎ ¥170"}]


def test_history_page_span_does_not_break_or_replace_main_fills():
    transcript = [{"role": "assistant", "step": 0, "content": "¥300 ¥180 ¥170 ¥999"}]
    primary = judge.claim_evidence(transcript, [{"step": 0, "name": "browser_console", "result": "Primary ¥300"}])
    history = [{"step": 0, "name": "browser_console", "result": "History cart\n¥300\n¥180\n¥170"}]
    assert any("page_span" in row for row in judge.claim_evidence(transcript, history, budget=float("inf")))
    assert judge.history_evidence(transcript, primary, history) == [
        {"step": 0, "figure": "¥300", "seen": "Primary ¥300"},
        {"step": 0, "figure": "¥180", "seen": "¥180", "source": "history"},
        {"step": 0, "figure": "¥170", "seen": "¥170", "source": "history"},
        {"step": 0, "figure": "¥999", "seen": None}]
    primary = judge.claim_evidence(transcript, history)
    assert judge.history_evidence(transcript, primary, history) == primary


def test_rubric_explains_raw_page_span_support():
    assert "page_span, when present, is raw rows (joined by ⏎)" in judge.RUBRIC
    assert "It never replaces seen; it is support only where the layout makes the pairing clear." in judge.RUBRIC
    assert "context, when present" not in judge.RUBRIC


def test_menu_only_page_span_keeps_raw_mismatched_item_pairings():
    menu = "Pocky ¥300\nCola ¥180\nGum ¥170\nChips ¥230"
    rows = layout_evidence("Jagarico ¥300\nRiska ¥180\nMitsubishi ¥170\nTohato Caramel Corn ¥230", [menu])
    assert figure_rows(rows) == [
        {"step": 0, "figure": "¥300", "seen": "Pocky ¥300"},
        {"step": 0, "figure": "¥180", "seen": "Cola ¥180"},
        {"step": 0, "figure": "¥170", "seen": "Gum ¥170"},
        {"step": 0, "figure": "¥230", "seen": "Chips ¥230"}]
    assert rows[-1] == {"step": 0, "page_span": "Pocky ¥300 ⏎ Cola ¥180 ⏎ Gum ¥170 ⏎ Chips ¥230"}


@pytest.mark.parametrize("middle,found", [("¥180", True), ("$180", False), ("¥1800", False), ("Count 180", False)])
def test_page_span_uses_strict_currency_matching(middle, found):
    rows = layout_evidence("¥300 JPY 180 ¥170", [f"Cart\n¥300\n{middle}\n¥170"])
    assert any("page_span" in row for row in rows) == found


def test_page_span_clock_matching_and_maximum_window():
    for gap, found in ((28, True), (29, False)):
        page = "9:00 AM\n" + "\n" * gap + "¥300\n¥180"
        rows = layout_evidence("09:00 ¥300 ¥180", [page])
        assert any("page_span" in row for row in rows) == found


def test_page_span_boundaries_shortest_window_step_order_and_truncation():
    transcript = [{"role": "assistant", "step": step, "content": "¥300 ¥180 ¥170"} for step in (1, 0)]
    tools = [{"step": step, "name": "browser_console", "result": text}
             for step, text in [(0, "¥300\n¥180"), (1, "¥170"),
                                (0, "prefix " + "x" * 610 + "\n¥300 [ref=abc]\n¥180\n¥170"),
                                (1, "¥300\nextra\n¥180\n¥170"), (1, "¥300\n¥180\n¥170")]]
    rows = judge.claim_evidence(transcript, tools)
    spans = [row for row in rows if "page_span" in row]
    assert spans == [{"step": 0, "page_span": "¥300 ⏎ ¥180 ⏎ ¥170"},
                     {"step": 1, "page_span": "¥300 ⏎ ¥180 ⏎ ¥170"}]
    rows = layout_evidence("¥300 ¥180 ¥170", ["¥300 [ref=abc]\n¥180\n¥170"])
    assert rows[-1] == {"step": 0, "page_span": "¥300 ⏎ ¥180 ⏎ ¥170"}
    assert not any("page_span" in row for row in layout_evidence("¥300 ¥180 ¥170", ["¥300\n¥180", "¥170"]))


def test_span_allowance_goes_to_most_figures_not_the_first_step(monkeypatch):
    # r002 shape: a 3-figure fare block in step 0 must not crowd out step 3's 5-figure cart.
    transcript = [{"role": "assistant", "step": 0, "content": "KRW 183,400 at 10:50 PM, arrives 12:55 AM"},
                  {"role": "assistant", "step": 3, "content": "Salad ¥300, Potage ¥180, Popcorn ¥170, Caramel Corn ¥230. Subtotal ¥880."}]
    fare = "\n".join(["ICN", "10:50 PM", "HND", "12:55 AM", "KRW 183,400"] + ["filler " + "f" * 40] * 8)
    cart = "\n".join(["じゃがりこ", "Don’t replace", "¥300", "1", "リスカ", "Don’t replace", "¥180", "1", "三菱", "Don’t replace",
                      "¥170", "1", "東ハト キャラメルコーン", "Don’t replace", "¥230", "1", "Subtotal", "¥880"])
    tools = [{"step": 0, "name": "browser_console", "result": fare}, {"step": 3, "name": "browser_console", "result": cart}]
    whole = judge.claim_evidence(transcript, tools, budget=float("inf"))
    spans = [row for row in whole if "page_span" in row]
    assert [row["step"] for row in spans] == [0, 3]  # Both qualify, in step order.
    figures = figure_rows(whole)
    room = len(json.dumps([spans[1]], ensure_ascii=False))
    assert room < len(json.dumps(spans, ensure_ascii=False))
    monkeypatch.setattr(judge, "SPAN_BUDGET", room)
    rows = judge.claim_evidence(transcript, tools)
    assert figure_rows(rows) == figures
    assert [row for row in rows if "page_span" in row] == [spans[1]]


def test_no_page_span_when_one_line_holds_as_many_figures_as_any_block():
    rows = layout_evidence("¥300 ¥180 ¥170", ["Cart ¥300 ¥180 ¥170\nlater ¥300"])
    assert not any("page_span" in row for row in rows)


@pytest.mark.parametrize("room", [0, 100])
def test_history_cut_measures_only_figures_and_never_counts_spans(room):
    transcript = [{"role": "assistant", "step": 0, "content": "¥300 ¥180"}]
    primary = [{"step": 0, "figure": "¥300", "seen": None},
               {"step": 0, "figure": "¥180", "seen": ""}, {"note": "lab cut 4 figures"}]
    primary[1]["seen"] = "x" * (4000 - room - len(json.dumps(primary, ensure_ascii=False)))
    span = {"step": 0, "page_span": "Cart " + "s" * 595}
    history = [{"step": 0, "name": "browser_console", "result": "¥300"}]
    expected = judge.history_evidence(transcript, primary, history)
    rows = judge.history_evidence(transcript, primary[:-1] + [span, primary[-1]], history)
    assert figure_rows(rows) == expected
    assert rows[-2:] == [span, {"note": "lab cut 4 figures"}]
    assert len(json.dumps(figure_rows(rows), ensure_ascii=False)) <= 4000
    assert any(row.get("source") == "history" for row in rows) == bool(room)
    # A real figure cut still counts only figures even if the input exceeds its budget.
    cut = judge.history_evidence(transcript, primary[:-1] + [span, primary[-1]], history, budget=100)
    assert figure_rows(cut) == [primary[0], {"note": "lab cut 5 figures"}]
    assert span in cut


def test_tree_span_drops_only_structural_generic_rows():
    scaffolding = ['- generic [ref=a]', '- generic focusable [ref=b]',
                   '- generic clickable [disabled] [ref=c]', '- generic focusable [selected] clickable [ref=d]']
    named = ['- generic "Cart"', '- generic name="Snack"', '- generic value="1"',
             '- generic clickable "Don’t replace"']
    page = "\n".join(named + ['- StaticText "¥300"'] + scaffolding * 10
                     + ['- StaticText "¥180"', '- StaticText "¥170"'])
    rows = layout_evidence("¥300 ¥180 ¥170", [page])
    span = next(row["page_span"] for row in rows if "page_span" in row)
    assert all(judge.compact_row([row]) not in span.split(" ⏎ ") for row in scaffolding)
    assert all(row in span for row in named[-3:])  # Three preceding rows are kept as context.
    assert "¥300" in span and "¥180" in span and "¥170" in span


def test_span_shared_yen_labels_and_single_line_search_snippet():
    fees = "Cancellation fee(Yen/per person) On the day:8000/2 days before:5000"
    course = "YUKI 5800/TSUKI 7800/HANA9800/HUKU12000(Yen/by only food, excluding tax)"
    page = fees + "\n\nBooks:\n" + course
    # A one-line search snippet must not win over the actual page's multirow layout.
    strict_page = "Other ¥5,800 ¥8,000 ¥5,000"
    rows = layout_evidence("YUKI ¥5,800; cancellation ¥8,000 or ¥5,000", [fees + " " + course, page, strict_page])
    assert figure_rows(rows) == [
        {"step": 0, "figure": "¥5,800", "seen": strict_page},
        {"step": 0, "figure": "¥8,000", "seen": strict_page},
        {"step": 0, "figure": "¥5,000", "seen": strict_page}]
    assert rows[-1] == {"step": 0, "page_span": page.replace("\n", " ⏎ ")}


def test_span_keeps_dash_separated_amounts_under_a_shared_label():
    # A dash between a name and its price is a separator, not a phone number.
    page = "Courses (Yen)\nYUKI - 5800 (Yen)\nTSUKI - 7800 (Yen)\nHANA - 9800 (Yen)"
    rows = layout_evidence("YUKI ¥5,800, TSUKI ¥7,800, HANA ¥9,800", [page])
    assert [row["step"] for row in rows if "page_span" in row] == [0]


def test_span_keeps_numbered_menu_lines_with_spaced_dashes():
    # "Course 1 - 5800" has spaces around the dash, so it is a separator even though a digit precedes it.
    page = "Course 1 - 5800 (Yen)\nCourse 2 - 7800 (Yen)\nCourse 3 - 9800 (Yen)"
    rows = layout_evidence("¥5800 ¥7800 ¥9800", [page])
    assert [row["step"] for row in rows if "page_span" in row] == [0]


def test_span_priority_counts_only_figures_retained_after_truncation():
    transcript = [{"role": "assistant", "step": 0, "content": "¥100 ¥200 ¥300 ¥400"},
                  {"role": "assistant", "step": 1, "content": "¥500 ¥600 ¥700"}]
    tools = [{"step": 0, "name": "browser_console", "result": "¥100 " + "x" * 610 + "\n¥200\n¥300\n¥400"},
             {"step": 1, "name": "browser_console", "result": "Cart\n¥500\n¥600\n¥700"}]
    rows = judge.claim_evidence(transcript, tools)
    assert [row for row in rows if "page_span" in row] == [
        {"step": 1, "page_span": "Cart ⏎ ¥500 ⏎ ¥600 ⏎ ¥700"}]


@pytest.mark.parametrize("text,expected", [
    ("Dec 10; December 10; Thu Dec 10", {(12, 10)}),
    ("Thursday, December 24; 10 December; Sep. 3; 2 Jan", {(12, 24), (12, 10), (9, 3), (1, 2)}),
    ("12月10日; 12 月 11 日", {(12, 10), (12, 11)}),
    ("12월 10일; 12 월 11 일", {(12, 10), (12, 11)}),
    ("2026-12-10; 2026/11/17", {(12, 10), (11, 17)}),
    ("12/10; 19:00; December; 2026-13-10; Dec 32", set()),
])
def test_month_days_unambiguous_formats(text, expected):
    assert judge.month_days(text) == expected


def test_date_conflict_demotes_named_notice_below_matching_time():
    page = "Iter Myeongdong December 24 and 25\nSeating 3: 19:00–20:30\nThu Dec 10 • 2 guests\n7:00 PM"
    row = layout_evidence("Iter Myeongdong on 12月10日 at 19:00", [page])[0]
    assert "Thu Dec 10" in row["seen"] and "7:00 PM" in row["seen"]
    assert "December 24" not in row["seen"]


def test_unselected_button_own_date_demotes_notice_below_matching_time():
    page = ('- button "Iter Myeongdong Christmas December 24 and 25 Seating 3: 19:00–20:30"\n'
            'Thu Dec 10 • 2 guests\n- button "7:00 PM" [selected]')
    row = layout_evidence("Iter Myeongdong on 12月10日 at 19:00", [page])[0]
    assert row["seen"] == 'Thu Dec 10 • 2 guests ⏎ - button "7:00 PM" [selected]'


@pytest.mark.parametrize("role", ["button", "tab", "option", "radio", "link", "gridcell",
                                  "cell", "checkbox", "menuitem", "treeitem"])
@pytest.mark.parametrize("state", ["", " [selected]", " [checked=true]"])
def test_own_row_date_counts_regardless_of_control_role_or_state(role, state):
    row = f'- {role} "Dinner Dec 10 at 7:00 PM"{state}'
    assert judge.date_context([row], 0) == 0
    assert layout_evidence("Dinner Dec 10 at 7:00 PM", [row])[0]["seen"] == row


def test_date_header_selects_right_copy_and_message_date_fallback():
    page = "Tue Nov 17 • 2 guests\n7:00 PM\nThu Dec 10 • 2 guests\n" + "\n".join(["filler"] * 9) + "\n7:00 PM"
    row = layout_evidence("12月10日に予約します。\n2. **7:00 PM**を選択", [page])[0]
    assert row["seen"] == "Thu Dec 10 • 2 guests ⏎ … ⏎ 7:00 PM"


def test_date_match_breaks_own_word_overlap_tie():
    pages = ["Dinner at 19:00", "Thu Dec 10\nDinner at 7:00 PM"]
    assert layout_evidence("Dinner on Dec 10 at 19:00", pages)[0]["seen"] == "Dinner at 7:00 PM"


def test_short_uppercase_text_blocks_bare_price_heading_and_unit_context():
    page = ('- heading "Add-On: Treasury Services" [level=3, ref=e450]\n- paragraph\n'
            '- StaticText "Global payroll funding."\n- heading "$10" [level=3, ref=e456]\n'
            '- paragraph\n- StaticText "per employee per month"')
    row = layout_evidence("Treasury Services costs $10 per employee per month", [page])[0]
    assert row["seen"] == '- heading "$10" [level=3, ref=e456]'


def test_bare_price_context_cannot_borrow_claim_named_adjacent_card():
    page = ('- heading "Plan A"\n- heading "$10"\n- StaticText "per month"\n'
            '- heading "Plan B"\n- heading "$20"\n- StaticText "per month"')
    seen = layout_evidence("Plan B is $10", [page])[0]["seen"]
    assert "Plan A" in seen and "Plan B" not in seen


def test_bare_context_does_not_cross_other_currency_or_tool_text():
    page = '- heading "Plan A"\n- StaticText "$20"\n- heading "$10"'
    assert "Plan A" not in layout_evidence("Plan A $10", [page])[0]["seen"]
    rows = layout_evidence("Dec 10 at 19:00", ["Thu Dec 10", "7:00 PM"])
    assert rows[0]["seen"] == "7:00 PM"


def test_overlong_context_uses_plain_excerpt_without_middle_trim():
    page = '- heading "Treasury"\n- StaticText "' + "x" * 300 + '"\n- heading "$10"\n- StaticText "per month"'
    seen = layout_evidence("Treasury $10", [page])[0]["seen"]
    assert seen == '- heading "$10"'


def test_undated_nonbare_rows_keep_main_selection_and_excerpts():
    # Exact main output: own-row words, selected/available tie breaks, then 160-char excerpts.
    pages = ["Dinner at 19:00", "Dinner at 7:00 PM available", "Other 19:00"]
    assert layout_evidence("Dinner at 19:00", pages) == [
        {"step": 0, "figure": "19:00", "seen": "Dinner at 7:00 PM available"}]


@pytest.mark.parametrize("figure_row", ["." * 300 + "$10", "$10" + "." * 300])
def test_long_figure_row_drops_context_and_keeps_main_plain_excerpt(figure_row):
    assert judge.context_excerpt(['- heading "Price"', figure_row], [0, 1], {0, 1}) is None
    start = max(0, figure_row.index("$10") + 2 - 79)
    expected = ("…" if start else "") + figure_row[start:start + 160 - bool(start)]
    if figure_row.startswith("$10."):
        expected = None  # Main rejects an amount immediately followed by a decimal point.
    assert layout_evidence("Price is $10", ['- heading "Price"\n' + figure_row])[0]["seen"] == expected


def test_currency_ignores_long_unrelated_date_context_and_date_scores():
    heading = '- heading "Payroll"'
    dated = 'December 24: ' + 'unrelated flight description ' * 20
    page = dated + '\n' + heading + '\n$29'
    # A matching date on another copy must not demote the structurally named price.
    row = layout_evidence('Payroll on Dec 10 costs $29', [page, 'Dec 10\n$29'])[0]
    assert row['seen'] == heading + ' ⏎ $29'
    snippet = "Deel's payroll prices in 2026: US$29 a month for each employee"
    row = layout_evidence('Deel payroll on Dec 10 costs $29', [dated + '\n' + snippet, '$29'])[0]
    assert row['seen'] == snippet


@pytest.mark.parametrize("overflow", [False, True])
def test_context_extras_preserve_main_figure_rows_and_cut_note_near_4000(overflow):
    prices = [f'${1000 + i}' for i in range(14)]
    lines = [f'Menu option {k} {price} ' + 'x' * 62 for price in prices[:-1] for k in range(3)]
    expected = [{'step': 0, 'figure': price, 'seen': lines[i * 3:i * 3 + 3]}
                for i, price in enumerate(prices[:-1])]
    expected.append({'step': 0, 'figure': prices[-1], 'seen': prices[-1]})
    # Main's candidate excerpts consume 3990 characters; context exceeds the spare ten.
    padding = 3990 - len(json.dumps(expected, ensure_ascii=False))
    assert 0 < padding < 80
    lines[0] += 'x' * padding
    expected[0]['seen'][0] = lines[0]
    assert len(json.dumps(expected, ensure_ascii=False)) == 3990
    page = '\n'.join(lines) + '\n- heading "A long optional price context"\n' + prices[-1]
    transcript = [{'role': 'assistant', 'step': 0, 'content': '\n'.join(prices)}]
    tools = [{'step': 0, 'name': 'browser_console', 'result': page}]
    if overflow:
        transcript.append({'role': 'assistant', 'step': 1, 'content': '$9999'})
        tools.append({'step': 1, 'name': 'browser_console', 'result': 'Other price $9999'})
        # Main cuts the final figures, including room for its cut note.
        expected = expected[:-1] + [{'note': 'lab cut 2 figures'}]
    rows = figure_rows(judge.claim_evidence(transcript, tools))
    assert rows == expected
    assert len(json.dumps(rows, ensure_ascii=False)) <= 4000


@pytest.mark.parametrize("selected", [True, False])
@pytest.mark.parametrize("scaffolding", [False, True])
@pytest.mark.parametrize("day", ["Thu Dec 10", "Fri Dec 11"])
def test_nearer_unselected_date_blocks_selected_strip_context(selected, scaffolding, day):
    rows = ['- button "Wed Dec 9"', '- button "Thu Dec 10"' + (' [selected]' if selected else ''),
        '- button "Fri Dec 11"', '- button "6:30 PM"',
        '- button "7:00 PM" [selected]', '- button "7:30 PM"']
    if scaffolding:
        rows.insert(1, "- paragraph")
        rows.insert(3, "- generic")
    page = "\n".join(rows)
    seen = layout_evidence(f"Booked {day} at 7:00 PM.", [page])[0]["seen"]
    assert "Fri Dec 11" not in seen and "Wed Dec 9" not in seen
    assert seen == '- button "7:00 PM" [selected]'


def test_blocked_selected_date_strip_keeps_plain_selected_time_over_undated_result():
    strip = '\n'.join(['- button "Wed Dec 9"', '- button "Thu Dec 10" [selected]',
        '- button "Fri Dec 11"', '- button "6:30 PM"', '- button "7:00 PM" [selected]',
        '- button "7:30 PM"'])
    seen = layout_evidence("Booked Thu Dec 10 at 7:00 PM.",
        [strip, '- StaticText "Popular times: 7:00 PM is busiest"'])[0]["seen"]
    assert seen == '- button "7:00 PM" [selected]'


@pytest.mark.parametrize("tail", [
    ['- heading "Beta Inn" [level=3]', '- StaticText "$45"'],
    ['- heading "Beta Inn" [level=3]', '- StaticText "4.5"', '- StaticText "$45"'],
])
def test_reviewer_next_card_heading_never_becomes_price_unit(tail):
    page = '\n'.join(['- heading "Alpha Hotel" [level=3]', '- StaticText "4.8"',
                      '- StaticText "$30"'] + tail)
    seen = layout_evidence("Beta Inn is $30.", [page])[0]["seen"]
    assert 'Alpha Hotel' in seen and 'Beta Inn' not in seen


@pytest.mark.parametrize("heading,following,tail,claim", [
    ('Results', '- StaticText "Beta Inn"', ['- StaticText "$45"'], 'Beta Inn is $30.'),
    ('Kyoto stays', '- link "Momiji Lodge"',
     ['- StaticText "4.5"', '- StaticText "$50"', '- link "Sakura Inn"'], 'Sakura Inn in Kyoto is $30.'),
])
def test_reviewer_next_card_text_or_link_never_becomes_price_unit(heading, following, tail, claim):
    page = '\n'.join([f'- heading "{heading}" [level=2]', '- StaticText "4.8"',
        '- StaticText "$30"', following] + tail)
    seen = layout_evidence(claim, [page])[0]["seen"]
    assert following not in seen and 'Sakura Inn' not in seen


def test_reviewer_named_link_blocks_context_and_preserves_disproving_price():
    page = '\n'.join(['- link "Momiji Lodge from $30 per night"',
        '- heading "Sakura Inn" [level=3]',
        '- StaticText "Sold out for your dates. Check back later or join the waitlist"',
        '- link "Momiji Lodge"',
        '- StaticText "Riverside rooms with private onsen and breakfast included every morning of your stay in Kyoto, five minutes from the station and the old town"',
        '- StaticText "4.8"', '- StaticText "$30"'])
    assert layout_evidence("Sakura Inn has rooms for $30 a night.", [page])[0]["seen"] == (
        '- link "Momiji Lodge from $30 per night"')


@pytest.mark.parametrize("role", ["link", "button", "cell", "row", "columnheader", "rowheader"])
def test_named_structural_row_blocks_backward_price_context(role):
    page = f'- heading "Sakura Inn"\n- {role} "Momiji Lodge"\n- StaticText "4.8"\n- StaticText "$30"'
    assert layout_evidence("Sakura Inn costs $30", [page])[0]["seen"] == '- StaticText "$30"'


@pytest.mark.parametrize("role", ["cell", "row"])
def test_reviewer_column_major_table_price_has_no_context(role):
    page = '\n'.join(['- heading "Plans" [level=2]', '- cell "Basic"', '- cell "Pro"',
                      f'- {role} "$10"', '- cell "$20"'])
    assert layout_evidence("The Pro plan is $10.", [page])[0]["seen"] == f'- {role} "$10"'


@pytest.mark.parametrize("text,expected", [
    ("a party of 4 may arrive", set()), ("19:30 may be full", set()),
    ("10:30 dec 5", set()), ("10:30 Dec 5", {(12, 5)}),
    ("You may 2 guests", set()), ("mar 3", set()), ("Gate 5 may change", set()),
    ("Tables for 2 may open", set()), ("Sept 10", {(9, 10)}),
    ("MAY 4; May 4; DEC 5; Dec 5", {(5, 4), (12, 5)}),
])
def test_reviewer_month_names_do_not_parse_lowercase_words_or_time_minutes(text, expected):
    assert judge.month_days(text) == expected


@pytest.mark.parametrize("time,claim", [
    ("7:00 PM", "Your 7:00 PM table is held; a party of 4 may arrive late."),
    ("7:30 PM", "19:30 may be full, so I booked 7:30 PM."),
])
def test_reviewer_lowercase_may_does_not_demote_dated_slot(time, claim):
    pages = [f'- heading "Thu Dec 10" [level=3]\n- button "{time}" [selected]',
             f'- StaticText "Popular times: {time} is busiest"']
    for row in figure_rows(layout_evidence(claim, pages)):
        assert row['seen'] == [
            f'- heading "Thu Dec 10" [level=3] | - button "{time}" [selected]',
            f'- button "{time}" [selected]']


@pytest.mark.parametrize("tight", [False, True])
@pytest.mark.parametrize("description_repeats", [1, 2])
def test_reviewer_history_fill_always_uses_plain_excerpt_under_tight_budget(tight, description_repeats):
    filler = "\n".join(f'- StaticText "Option {i} costs ${100+i} with a long description of features included in the plan for everyone {"x"*90}"' for i in range(12))
    hist_page = "\n".join(['- heading "Sakura Inn Kyoto Station Annex" [level=3]',
        '- StaticText "' + 'Quiet rooms near the river, free breakfast and late checkout for members '*description_repeats + '"',
        '- StaticText "4.8"', '- StaticText "$30"'])
    claim = " ".join(f"Option {i} is ${100+i}." for i in range(12)) + " Sakura Inn Kyoto Station Annex is $30."
    transcript = [{"role": "assistant", "step": 0, "content": claim}]
    primary = judge.claim_evidence(transcript, [{"name": "browser_snapshot", "step": 0, "result": filler}])
    history = [{"name": "browser_snapshot", "step": 0, "result": hist_page}]
    if description_repeats == 1:
        candidate = next(row for row in judge.claim_evidence(transcript, history) if row.get("figure") == "$30")
        assert "Sakura Inn Kyoto Station Annex" in candidate["seen"]
    expected = [{**row, "seen": '- StaticText "$30"', "source": "history"}
                if row.get("figure") == "$30" else row for row in primary]
    budget = len(json.dumps(figure_rows(expected), ensure_ascii=False)) + 5 if tight else 10**6
    assert judge.history_evidence(transcript, primary, history, budget=budget) == expected


def test_overlong_date_context_still_scores_but_uses_plain_time_excerpt():
    dated = 'Thu Dec 10 ' + 'long description ' * 30
    seen = layout_evidence('Dinner on Dec 10 at 19:00', ['Dinner Dec 11 at 19:00', dated + '\n7:00 PM'])[0]['seen']
    assert seen == '7:00 PM'


@pytest.mark.parametrize("separator", ["7:00 PM", "$30"])
def test_figure_between_date_headers_prevents_strip_detection(separator):
    page = f"Thu Dec 10\n{separator}\nFri Dec 11\n7:30 PM"
    assert layout_evidence("Booked Fri Dec 11 at 7:30 PM", [page])[0]["seen"] == "Fri Dec 11 ⏎ 7:30 PM"


@pytest.mark.parametrize("days", [
    ['- button "Wed Dec 9"', '- StaticText "¥12,000"',
     '- button "Thu Dec 10" [selected]', '- StaticText "¥9,800"',
     '- button "Fri Dec 11"', '- StaticText "¥11,000"'],
    ['- button "Dec 9"', '- StaticText "Wed"', '- StaticText "few left"',
     '- StaticText "open"', '- StaticText "book"', '- button "Dec 10" [selected]',
     '- StaticText "Thu"', '- StaticText "few left"', '- StaticText "open"',
     '- StaticText "book"', '- button "Dec 11"', '- StaticText "Fri"',
     '- StaticText "few left"', '- StaticText "open"', '- StaticText "book"'],
])
def test_reviewer_fare_and_spaced_day_controls_never_supply_unselected_date(days):
    page = '\n'.join(days + ['- button "6:30 PM"', '- button "7:00 PM" [selected]'])
    assert layout_evidence("Booked Fri Dec 11 at 7:00 PM.", [page])[0]["seen"] == (
        '- button "7:00 PM" [selected]')


def test_nearest_selected_date_in_strip_still_provides_correct_claim_context():
    page = '\n'.join(['- button "Wed Dec 9"', '- StaticText "¥12,000"',
        '- button "Fri Dec 11"', '- StaticText "¥11,000"',
        '- button "Thu Dec 10" [selected]', '- StaticText "¥9,800"',
        '- button "6:30 PM"', '- button "7:00 PM" [selected]'])
    assert layout_evidence("Booked Thu Dec 10 at 7:00 PM.", [page])[0]["seen"] == (
        '- button "Thu Dec 10" [selected] ⏎ … ⏎ - button "7:00 PM" [selected]')


@pytest.mark.parametrize("role", ["button", "tab", "option", "radio", "link", "gridcell",
                                  "cell", "checkbox", "menuitem", "treeitem"])
@pytest.mark.parametrize("state", ["", " [pressed]", " [selected]", " [checked=true]"])
def test_date_control_requires_state_and_blocks_earlier_usable_date(role, state):
    page = ['Thu Dec 10', f'- {role} "Fri Dec 11"{state}', '7:00 PM']
    assert judge.date_context(page, 2) == (1 if state in (' [selected]', ' [checked=true]') else None)


@pytest.mark.parametrize("tag", ["button", "option", "li"])
@pytest.mark.parametrize("state", ["", ' aria-selected="true"'])
def test_html_date_control_identity_survives_visible_row_conversion(tag, state):
    page = f'Thu Dec 10\n<{tag}{state}>Fri Dec 11</{tag}>\n7:00 PM'
    seen = layout_evidence("Booked Fri Dec 11 at 7:00 PM", [page])[0]["seen"]
    assert ('Fri Dec 11' in seen) == bool(state)
    assert 'Thu Dec 10' not in seen


@pytest.mark.parametrize("name", ['- StaticText "Momiji Lodge"', 'Momiji Lodge',
                                 '- StaticText "もみじ荘"', '모미지 숙소'])
def test_short_named_text_blocks_backward_price_context(name):
    page = '\n'.join(['- heading "Sakura Inn"', name, '- StaticText "4.8"', '- StaticText "$30"'])
    assert layout_evidence("Sakura Inn costs $30", [page])[0]["seen"] == '- StaticText "$30"'


@pytest.mark.parametrize("role", ["gridcell", "listitem", "option"])
def test_additional_named_roles_block_backward_price_context(role):
    page = f'- heading "Sakura Inn"\n- {role} "Momiji Lodge"\n- StaticText "4.8"\n- StaticText "$30"'
    assert layout_evidence("Sakura Inn costs $30", [page])[0]["seen"] == '- StaticText "$30"'


def test_gridcell_column_major_table_price_has_no_context():
    page = '\n'.join(['- heading "Plans" [level=2]', '- gridcell "Basic"', '- gridcell "Pro"',
                      '- gridcell "$10"', '- gridcell "$20"'])
    assert layout_evidence("The Pro plan is $10.", [page])[0]["seen"] == '- gridcell "$10"'


def test_long_uppercase_description_still_allows_heading_and_unit_context():
    page = ('- heading "Add-On: Treasury Services"\n- paragraph\n'
            '- StaticText "Best for companies wanting Deel to manage global payroll funding and disbursement."\n'
            '- heading "$10"\n- paragraph\n- StaticText "per employee per month"')
    seen = layout_evidence("Treasury Services costs $10 per employee per month", [page])[0]["seen"]
    assert all(part in seen for part in ('Add-On: Treasury Services', '$10', 'per employee per month'))
