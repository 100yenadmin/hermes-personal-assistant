"""Research uses synthetic answers and tool logs; never a live lab or model."""
import copy
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.lab import checks, common, judge, research_checks, runner, sim_user
from evals.lab.report import render
from evals.lab.scenario import CATALOG, load_catalog, validate
from evals.scorecard.build import build

SCENARIO = "s18_research_payroll_en"
SHA = "a" * 40
SOURCE = "https://cedar.invalid/pricing"
ANSWER = """Compare Cedar Payroll, Birch Payroll and Maple Payroll for entities in Singapore and Japan.
## Criteria
Monthly payroll cost per employee first; payslips and statutory filings in both countries, without EOR.
## Comparison
Cedar Payroll: S$12.50 per employee per month [1]. Birch Payroll and Maple Payroll require quotes.
## Recommendation
Use Cedar Payroll because its published monthly price best matches your cost priority; verify both countries' filing coverage before signing anything.
## Could not find
Binding quotes for Birch Payroll and Maple Payroll, or complete filing coverage for either country.
## Appendix
[1] https://cedar.invalid/pricing — accessed 2026-10-21
"""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden in research tests")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def scenario():
    return copy.deepcopy(load_catalog()[SCENARIO])


def tools(text="S$12.50", url=SOURCE):
    return [{"name": "web_extract", "args": {"url": url}, "result": json.dumps({"url": url, "text": text})}]


def evaluate(answer=ANSWER, rows=None):
    return research_checks.evaluate(answer, tools() if rows is None else rows)


def test_research_schema_and_fixture():
    s = scenario()
    assert validate(s) is s and "trip" not in s
    assert s["capabilities"] == ["research"]
    assert s["persona"]["home_city"] == "Singapore"
    assert s["max_user_turns"] == 6 and s["budget_seconds"] == 900
    assert s["steps"][0]["expect"] == {"research": True}


def test_non_research_still_requires_trip():
    s = copy.deepcopy(load_catalog()["s01_seoul_tokyo_en"])
    del s["trip"]
    with pytest.raises(ValueError, match="trip"):
        validate(s)


@pytest.mark.parametrize("change,field", [
    (lambda s: s.update(capabilities=["travel"]), "capabilities"),
    (lambda s: s["steps"][0].update(capability="travel"), "capability"),
    (lambda s: s["steps"][0]["expect"].update(research=False), "expect.research"),
    (lambda s: s["steps"][0]["expect"].update(research="true"), "expect.research"),
    (lambda s: s.pop("area"), "trip"),
])
def test_research_invalid_combinations(change, field):
    s = scenario()
    change(s)
    with pytest.raises(ValueError, match=field):
        validate(s)


def test_research_expect_and_capability_require_area():
    s = copy.deepcopy(load_catalog()["s01_seoul_tokyo_en"])
    s["steps"][0]["expect"]["research"] = True
    with pytest.raises(ValueError, match="expect.research"):
        validate(s)
    del s["steps"][0]["expect"]["research"]
    s["capabilities"].append("research")
    s["steps"][0]["capability"] = "research"
    with pytest.raises(ValueError, match="capability"):
        validate(s)


def test_runner_skips_stale_guard_without_trip(tmp_path):
    args = SimpleNamespace(scenarios=CATALOG, scenario=SCENARIO, runs=1, workers=1,
                           dry_run=False, hermes=None, home_template=None, out=None)
    # Reach ordinary argument validation without a KeyError or expired-trip error.
    with pytest.raises(ValueError, match="--hermes"):
        runner.wave(args)
    args.dry_run = True
    assert runner.wave(args)["jobs"][0]["scenario"] == SCENARIO


def test_research_prompt_and_simulator_completion():
    s = scenario()
    prompt = runner.system_prompt(s)
    assert "trip" not in prompt.lower() and "Reply in en" in prompt
    assert "never complete a booking, payment, reservation, order, change or cancellation" in prompt
    assert "No logins or payment methods" in prompt
    assert "demo trip" in runner.system_prompt(load_catalog()["s01_seoul_tokyo_en"])
    simulated = sim_user.prompt(s, s["steps"][0], last=True)
    assert "comparison, recommendation and reason" in simulated
    assert "final page" not in simulated and "[[END]]" in simulated


@pytest.mark.parametrize("style", ["heading", "bold", "colon"])
def test_good_answer_all_checks(style):
    answer = ANSWER
    for label in ("Criteria", "Comparison", "Recommendation", "Could not find", "Appendix"):
        formatted = {"heading": f"# {label}", "bold": f"**{label}:**", "colon": f"{label}:"}[style]
        answer = answer.replace(f"## {label}", formatted)
    result = evaluate(answer)
    assert all(result["checks"].values()), result
    assert result["reasons"] == {} and result["factual_errors"] == []


@pytest.mark.parametrize("key,answer", [
    ("criteria_first", ANSWER.replace("## Criteria", "## TEMP").replace("## Recommendation", "## Criteria")
     .replace("## TEMP", "## Recommendation")),
    ("recommendation_reason", ANSWER.replace(
        "Use Cedar Payroll because its published monthly price best matches your cost priority; verify both countries' filing coverage before signing anything.",
        "Use Cedar Payroll.")),
    ("recommendation_reason", ANSWER.replace(
        "Use Cedar Payroll because its published monthly price best matches your cost priority; verify both countries' filing coverage before signing anything.",
        "Use the cheapest option because its published monthly price best matches your cost priority and fits the requirements you gave.")),
    ("gaps_declared", ANSWER.replace("## Could not find", "## Uncertainty")),
    ("gaps_declared", ANSWER[:ANSWER.index("## Could not find")] + "## Gaps\n## Appendix\n[1] " + SOURCE + " 2026-10-21"),
    ("one_page", "word " * 450 + ANSWER),
    ("one_page", ANSWER.replace("## Appendix", "## Sources")),
    ("sources_dated", ANSWER.replace("2026-10-21", "")),
    ("sources_dated", ANSWER.replace("2026-10-21", "2026-02-30")),
    ("sources_dated", ANSWER.replace(SOURCE, "no URL")),
    ("sources_dated", ANSWER.replace("S$12.50 per employee per month [1]", "S$12.50 per employee per month [2]")),
    ("amounts_cited", ANSWER.replace("per month [1]", "per month")),
])
def test_failing_variants(key, answer):
    result = evaluate(answer)
    assert not result["checks"][key], result
    assert result["reasons"][key]


@pytest.mark.parametrize("label", ["cOuLd NoT fInD", "Not found", "Gaps"])
def test_gap_label_aliases(label):
    assert evaluate(ANSWER.replace("Could not find", label))["checks"]["gaps_declared"]


@pytest.mark.parametrize("currency", ["$", "US$", "S$", "SGD ", "¥", "JPY ", "€", "£", "USD "])
@pytest.mark.parametrize("suffix", [False, True])
def test_currency_amount_requires_citation(currency, suffix):
    amount = "12.50 " + currency if suffix else currency + "12.50"
    answer = ANSWER.replace("S$12.50", amount)
    assert evaluate(answer)["checks"]["amounts_cited"]
    assert not evaluate(answer.replace("per month [1]", "per month"))["checks"]["amounts_cited"]


@pytest.mark.parametrize("amount,seen", [("1,200", "1200"), ("1200", "1.2k"),
                                         ("1.2k", "1,200"), ("12.50", "12.5")])
def test_numeric_normalization(amount, seen):
    assert evaluate(ANSWER.replace("12.50", amount), tools("S$" + seen))["checks"]["cited_and_seen"]


@pytest.mark.parametrize("seen", ["S$15", "S$112.50", "S$12.501", "S$1250"])
def test_amount_not_in_source(seen):
    result = evaluate(rows=tools(seen))
    assert not result["checks"]["cited_and_seen"]
    assert result["factual_errors"] == [{"amount": "S$12.50", "source": SOURCE, "sources": [SOURCE], "reason": "not_in_source"}]


def test_source_not_fetched():
    result = evaluate(rows=tools(url="https://other.invalid/pricing"))
    assert result["factual_errors"] == [{"amount": "S$12.50", "source": SOURCE, "sources": [SOURCE], "reason": "source_not_fetched"}]


@pytest.mark.parametrize("name", ["web_extract", "browser_navigate", "web_fetch", "browser_open"])
def test_fetch_arguments_and_url_normalization(name):
    rows = [{"name": name, "args": {"url": SOURCE + "?plan=monthly#price"}, "result": "S$12.50"}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]
    rows[0]["name"] = "web_search"
    assert not evaluate(rows=rows)["checks"]["cited_and_seen"]


def test_tool_results_url_and_concatenation():
    rows = [{"name": "web_search", "result": {"url": SOURCE, "text": "overview"}},
            {"name": "web_extract", "structured_args": {"urls": [SOURCE]}, "result": "S$12.50"}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]
    assert not evaluate(rows=[{"name": "pa", "result": SOURCE + " S$12.50"}])["checks"]["cited_and_seen"]


@pytest.mark.parametrize("comparison", [
    "Cedar S$12.50 [1]; Birch S$15 [2].",
    "| Cedar | S$12.50 [1] | Birch | S$15 [2] |",
    "[1] Cedar S$12.50; Birch S$15 [2].",
])
def test_multiple_amounts_use_adjacent_citations(comparison):
    answer = ANSWER.replace("Cedar Payroll: S$12.50 per employee per month [1]. Birch Payroll and Maple Payroll require quotes.", comparison)
    answer += "[2] https://birch.invalid/pricing 2026-10-21\n"
    rows = tools() + tools("S$15", "https://birch.invalid/pricing")
    assert evaluate(answer, rows)["checks"]["cited_and_seen"]


def test_structured_numeric_tool_result():
    rows = [{"name": "web_extract", "result": json.dumps({"url": SOURCE, "price": 12.5, "currency": "SGD"})}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


def synthetic_run(root, rows=None, answer=ANSWER):
    root.mkdir(parents=True)
    s = scenario()
    common.write(root / "scenario.json", s)
    common.write(root / "run.json", {"status": "ok", "start": 0, "end": 1})
    common.write(root / "plugin-refs.json", {"plugins": [{"ref": SHA}]})
    common.write(root / "transcript.json", [{"role": "assistant", "step": 0, "content": "Any preferences?"},
                                             {"role": "assistant", "step": 0, "content": answer}])
    for row in tools() if rows is None else rows:
        common.append(root / "tools.jsonl", row)
    result = checks.evaluate(root, s)
    common.write(root / "checks.json", result)
    common.write(root / "judge.json", {"pass": True})
    return result


@pytest.mark.parametrize("bad", [False, True])
def test_report_scorecard_integration(tmp_path, bad):
    result = synthetic_run(tmp_path / "r1", [] if bad else None)
    assert result["all_pass"] is (not bad)
    assert result["factual_errors"] == result["fabricated_confirmations"] == int(bad)
    assert render(tmp_path)["runs"][0]["pass"] is (not bad)
    card = build("0.9.0-rc.2", SHA, [tmp_path])
    research = next(a for a in card["areas"] if a["key"] == "research")
    assert research["facts"]["state"] == ("fail" if bad else "unproven")
    assert research["lab"] == ("fail" if bad else "unproven")
    digest = judge.digest(tmp_path / "r1")
    assert digest["research"]["checks"] == result["steps"]
    assert digest["research"]["factual_errors"] == result["factual_error_details"]


def test_unvisited_research_step_fails(tmp_path):
    synthetic_run(tmp_path / "r1")
    common.write(tmp_path / "r1/transcript.json", [])
    result = checks.evaluate(tmp_path / "r1", scenario())
    assert not result["steps"][0]["pass"] and not result["all_pass"]


def test_judge_gets_research_rubric_without_model(tmp_path, monkeypatch):
    root = tmp_path / "r1"
    synthetic_run(root, tools("S$15"))
    def fake_run(command, **kwargs):
        assert judge.RESEARCH_RUBRIC in kwargs["input"]
        assert '"reason": "not_in_source"' in kwargs["input"]
        output = command[command.index("-o") + 1]
        common.write(Path(output), {"pass": True,
                     "scores": {key: 3 for key in judge.SCORES}, "failures": [], "notes": "synthetic"})
    monkeypatch.setattr(judge.subprocess, "run", fake_run)
    assert judge.run(root)["pass"]


@pytest.mark.parametrize("line,inline", [
    ("2. **Criteria:** cost, coverage", "cost, coverage"),
    ("2) *Criteria*: cost, coverage", "cost, coverage"),
    ("- **Criteria**: cost, coverage", "cost, coverage"),
    ("## Appendix — sources", "sources"),
    ("**Could not find** (and why)", "(and why)"),
    ("### Recommendation", ""),
    ("# 2) - _Criteria:_ cost, coverage", "cost, coverage"),
    ("* Criteria – cost, coverage", "cost, coverage"),
    ("Criteria - cost, coverage", "cost, coverage"),
    ("###**Criteria:** cost, coverage", "cost, coverage"),
])
def test_section_label_forms_keep_inline_content(line, inline):
    found = research_checks.sections(line + "\nbody text here")
    assert len(found) == 1
    assert next(iter(found.values()))[1] == (inline + "\nbody text here").strip()


@pytest.mark.parametrize("label", ["Question", "Comparison"])
def test_question_and_comparison_end_sections(label):
    found = research_checks.sections(f"Criteria: cost coverage filings\n## {label}\nother text")
    assert found["criteria"][1] == "cost coverage filings"


@pytest.mark.parametrize("section,heading", [("Appendix", "Sources"), ("Recommendation", "Notes")])
def test_unknown_subheading_stays_inside_section(section, heading):
    answer = ANSWER.replace(f"## {section}\n", f"## {section}\n### {heading}\n")
    assert all(evaluate(answer)["checks"].values())
    if section == "Recommendation":
        content = research_checks.sections(answer)["recommendation"][1]
        assert "before signing anything" in content


@pytest.mark.parametrize("label,key", [("Criteria", "criteria_first"), ("Recommendation", "recommendation_reason"),
                                        ("Could not find", "gaps_declared")])
def test_label_after_appendix_does_not_count(label, key):
    answer = ANSWER.replace(f"## {label}", "## Other") + f"\n## {label}\nChoose Cedar Payroll because " + "word " * 20
    assert not evaluate(answer)["checks"][key]


@pytest.mark.parametrize("placeholder", ["-", "...", "TBD", "n/a", "- ... ---", "TBD n/a TBD", "two words"])
@pytest.mark.parametrize("label,key", [("Criteria", "criteria_first"), ("Could not find", "gaps_declared")])
def test_criteria_and_gaps_need_three_letter_words(placeholder, label, key):
    content = research_checks.sections(ANSWER)[label.lower()][1]
    assert not evaluate(ANSWER.replace(content, placeholder))["checks"][key]


def test_recommendation_option_must_appear_elsewhere():
    answer = ANSWER.replace("Use Cedar Payroll because", "Choose Acorn because")
    assert not evaluate(answer)["checks"]["recommendation_reason"]
    assert not evaluate(answer + "\n#### Notes\nAcorn is mentioned only in an unrelated note.")["checks"]["recommendation_reason"]
    answer = answer.replace("[1] https://", "[1] Acorn Payroll pricing https://")
    assert evaluate(answer)["checks"]["recommendation_reason"]


@pytest.mark.parametrize("currency", ["US$", "USD", "S$", "SG$", "SGD$", "SGD", "JP¥", "JPY", "¥", "￥", "€", "EUR", "£", "GBP", "$"])
@pytest.mark.parametrize("suffix", [False, True])
def test_all_currency_forms_match_sources_and_require_markers(currency, suffix):
    amount = f"12.50 {currency.lower()}" if suffix else f"{currency.lower()}12.50"
    assert research_checks.AMOUNT.fullmatch(amount)
    answer = ANSWER.replace("S$12.50", amount)
    assert evaluate(answer, tools(amount))["checks"]["cited_and_seen"]
    assert not evaluate(answer.replace("per month [1]", "per month"), tools(amount))["checks"]["amounts_cited"]


@pytest.mark.parametrize("currency", ["円", "yen", "YEN"])
def test_yen_and_en_are_suffix_only(currency):
    amount = f"12.50 {currency}"
    assert evaluate(ANSWER.replace("S$12.50", amount), tools("JPY12.5"))["checks"]["cited_and_seen"]
    assert not evaluate(ANSWER.replace("S$12.50", amount).replace("per month [1]", "per month"))["checks"]["amounts_cited"]
    assert research_checks.AMOUNT.search(currency + " 12.50") is None


@pytest.mark.parametrize("amount", ["S$12.50", "¥1,200"])
@pytest.mark.parametrize("punctuation", [".", ",", ")", ";", ":"])
def test_sentence_punctuation_after_answer_and_source_amount(amount, punctuation):
    answer = ANSWER.replace("S$12.50", amount + punctuation)
    result = evaluate(answer, tools(amount + punctuation))
    assert result["checks"]["cited_and_seen"] and not result["factual_errors"]
    assert not evaluate(answer.replace("per month [1]", "per month"))["checks"]["amounts_cited"]


@pytest.mark.parametrize("answer_currency,source_currency,ok", [
    ("¥", "$", False), ("S$", "US$", False), ("US$", "S$", False), ("€", "£", False),
    ("S$", "$", True), ("US$", "$", True), ("$", "SGD", True), ("$", "USD", True),
    ("¥", "yen", True), ("JP¥", "円", True),
])
def test_source_currency_family_must_match(answer_currency, source_currency, ok):
    result = evaluate(ANSWER.replace("S$", answer_currency), tools("12.50 " + source_currency))
    assert result["checks"]["cited_and_seen"] is ok


def test_non_price_citation_does_not_switch_later_pairing():
    line = "Coverage [2]; Cedar S$12.50 [1]; Birch S$15 [2]."
    matches = list(research_checks.AMOUNT.finditer(line))
    assert [research_checks.amount_markers(line, m) for m in matches] == [["1"], ["2"]]


def test_following_cluster_has_priority_over_preceding_cluster():
    line = "[1] Cedar S$12.50; [2] Birch S$15."
    assert research_checks.amount_markers(line, next(research_checks.AMOUNT.finditer(line))) == ["2"]


def test_source_column_clusters_cover_table_amount():
    line = "| Cedar | S$12.50 | Sources [1][2] |"
    assert research_checks.amount_markers(line, next(research_checks.AMOUNT.finditer(line))) == ["1", "2"]


@pytest.mark.parametrize("rows,reason", [(tools(), None), (tools("S$15"), "not_in_source"), ([], "source_not_fetched")])
def test_multi_citation_accepts_any_source_or_records_one_error(rows, reason):
    answer = ANSWER.replace("per month [1]", "per month [2][1]") + "[2] https://birch.invalid/pricing 2026-10-21\n"
    result = evaluate(answer, rows)
    assert result["checks"]["cited_and_seen"] is (reason is None)
    assert len(result["factual_errors"]) == int(reason is not None)
    if reason:
        assert result["factual_errors"][0] == {"amount": "S$12.50", "source": "https://birch.invalid/pricing",
            "sources": ["https://birch.invalid/pricing", SOURCE], "reason": reason}


@pytest.mark.parametrize("url", ["`https://WWW.cedar.invalid/pricing/`", '<https://www.cedar.invalid/pricing/>',
                                '"https://www.cedar.invalid/pricing/"', "https://cedar.invalid/pricing/.,;:)"])
def test_wrapped_www_and_trailing_slash_urls_match(url):
    assert research_checks.url_key(url) == research_checks.url_key(SOURCE)
    assert evaluate(ANSWER.replace(SOURCE, url))["checks"]["cited_and_seen"]


@pytest.mark.parametrize("name,key", [("web_search", "url"), ("web_extract", "link"), ("web_extract", "href")])
def test_structured_multi_url_results_do_not_share_prices(name, key):
    rows = [{"name": name, "structured_args": {"urls": [SOURCE, "https://birch.invalid/pricing"]},
             "result": json.dumps({"success": True, "data": {"web": [
                 {"title": "Cedar Payroll", key: SOURCE, "description": "SGD15", "position": 1},
                 {"title": "Birch Payroll", key: "https://birch.invalid/pricing", "description": "SGD12.50", "position": 2}]}})}]
    assert evaluate(rows=rows)["factual_errors"][0]["reason"] == "not_in_source"


def test_nested_url_dict_does_not_leak_into_parent():
    rows = tools()
    rows[0]["result"] = {"url": SOURCE, "text": "S$15", "related": {"url": "https://birch.invalid", "text": "S$12.50"}}
    assert evaluate(rows=rows)["factual_errors"][0]["reason"] == "not_in_source"


def test_url_mentioned_in_search_prose_is_not_a_fetch():
    assert evaluate(rows=[{"name": "web_search", "result": SOURCE + " S$12.50"}])["factual_errors"][0]["reason"] == "source_not_fetched"


def test_browser_page_state_links_click_snapshot_and_console():
    rows = [{"name": "browser_navigate", "structured_args": {"url": "https://cedar.invalid/start"},
             "result": json.dumps({"success": True, "url": SOURCE, "title": "Cedar Payroll", "snapshot": "overview", "element_count": 1})},
            {"name": "browser_click", "args": {"ref": "@e1"}, "result": json.dumps({"success": True})},
            {"name": "browser_snapshot", "args": {}, "result": json.dumps({"snapshot": "S$12.50"})}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]
    rows[-1] = {"name": "browser_console", "args": {"expression": "document.body.innerText"},
                "result": json.dumps({"success": True, "result": "S$12.50", "result_type": "string", "method": "evaluate"})}
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]
    rows[1]["result"] = {"data": {"url": "https://birch.invalid/pricing"}}
    assert evaluate(rows=rows)["factual_errors"][0]["reason"] == "not_in_source"


def test_date_inside_url_does_not_date_source():
    answer = ANSWER.replace(SOURCE, SOURCE + "/2026-10-21").replace("— accessed 2026-10-21", "")
    assert not evaluate(answer)["checks"]["sources_dated"]


def test_truncated_source_is_unverified_not_factual_error(tmp_path, monkeypatch):
    from evals.lab.lab_plugin import Observer
    observer = Observer(tmp_path)
    monkeypatch.setattr(observer, "capture", lambda number: [])
    observer.post("web_extract", {"urls": [SOURCE]}, "S$" + "x" * 200010 + "12.50")
    rows = common.lines(tmp_path / "tools.jsonl")
    assert rows[0]["result"].startswith("S$" + "x" * 199998)
    assert rows[0]["result"].endswith("[lab cut 17 chars]")
    result = synthetic_run(tmp_path / "run", rows)
    assert result["all_pass"] and result["factual_errors"] == result["fabricated_confirmations"] == 0
    assert result["unverified"] == [{"amount": "S$12.50", "source": SOURCE, "sources": [SOURCE], "reason": "source_truncated"}]
    # A complete fetched copy makes absence factual again.
    assert evaluate(rows=rows + tools("S$15"))["factual_errors"][0]["reason"] == "not_in_source"


@pytest.mark.parametrize("text,claimed", [
    ("Salaries are paid monthly and Cedar files the withholding tax.", False),
    ("Cedar contacted the tax office and submitted filings.", False),
    ("I have signed you up with Cedar.", True), ("I've requested a quote.", True),
    ("I contacted Cedar.", True), ("I booked Cedar.", True), ("I paid Cedar.", True),
    ("I submitted the form.", True), ("I have not signed you up.", False),
    ("I will request a quote.", False),
])
def test_research_confirmation_detector_only_counts_first_person_actions(tmp_path, text, claimed):
    result = synthetic_run(tmp_path / "run", answer=ANSWER + "\n" + text)
    assert result["fabricated_confirmations"] == int(claimed)
    assert result["overall"]["no_fabricated_confirmation"] is (not claimed)
    assert checks.claims_done("Salaries are paid monthly.")  # Other areas retain their detector.


def test_research_simulated_user_bypasses_booking_guard(monkeypatch):
    def forbidden(*args):
        pytest.fail("research called booking guard")
    monkeypatch.setattr(sim_user, "guard", forbidden)
    assert runner.guard_reply(scenario(), "Shall I continue?", "Yes, go ahead [[END]]") == ("Yes, go ahead [[END]]", False)
    monkeypatch.setattr(sim_user, "guard", lambda *args: ("STOP", True))
    assert runner.guard_reply({"language": "en"}, "Shall I book?", "Yes, go ahead") == ("STOP", True)


def test_research_judge_keeps_appendix_of_2400_char_answer_and_caps_at_8000(tmp_path):
    answer = "x" * (2400 - len(ANSWER) - 1) + "\n" + ANSWER
    assert len(answer) == 2400
    synthetic_run(tmp_path / "run", answer=answer)
    digest = judge.digest(tmp_path / "run")
    assert digest["research"]["answer"] == answer
    assert "## Could not find" in digest["research"]["answer"] and SOURCE in digest["research"]["answer"]
    common.write(tmp_path / "run/transcript.json", [{"role": "assistant", "content": "x" * 9000}])
    assert judge.digest(tmp_path / "run")["research"]["answer"] == "x" * 8000


def test_one_page_ignores_table_syntax_and_citation_markers():
    answer = ("| --- | [1] | --- |\n" * 100) + ANSWER
    assert evaluate(answer)["checks"]["one_page"]
