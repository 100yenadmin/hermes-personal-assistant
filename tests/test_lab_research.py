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
- **Cedar Payroll**: S$12.50 per employee per month [1].
- **Birch Payroll**: requires a quote.
- **Maple Payroll**: requires a quote.
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
def test_good_answer_all_checks(style, tmp_path):
    answer = ANSWER
    for label in ("Criteria", "Comparison", "Recommendation", "Could not find", "Appendix"):
        formatted = {"heading": f"# {label}", "bold": f"**{label}:**", "colon": f"{label}:"}[style]
        answer = answer.replace(f"## {label}", formatted)
    result = evaluate(answer)
    assert all(result["checks"].values()), result
    assert result["reasons"] == {} and result["factual_errors"] == []
    assert not checks.claims_done(answer)
    assert synthetic_run(tmp_path / "run", answer=answer)["all_pass"]


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
    assert evaluate(rows=rows)["checks"]["cited_and_seen"] is (name != "browser_open")
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
    answer = ANSWER.replace("- **Cedar Payroll**: S$12.50 per employee per month [1].\n- **Birch Payroll**: requires a quote.\n- **Maple Payroll**: requires a quote.", comparison)
    answer += "[2] https://birch.invalid/pricing 2026-10-21\n"
    rows = tools() + tools("S$15", "https://birch.invalid/pricing")
    assert evaluate(answer, rows)["checks"]["cited_and_seen"]


def test_structured_numeric_tool_result_is_not_page_text():
    rows = [{"name": "web_extract", "result": json.dumps({"url": SOURCE, "price": 12.5, "currency": "SGD"})}]
    assert not evaluate(rows=rows)["checks"]["cited_and_seen"]


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


@pytest.mark.parametrize("placeholder", ["-", "...", "TBD", "n/a", "- ... ---", "TBD n/a TBD", "one"])
@pytest.mark.parametrize("label,key", [("Criteria", "criteria_first"), ("Could not find", "gaps_declared")])
def test_criteria_and_gaps_reject_placeholders_and_one_word(placeholder, label, key):
    content = research_checks.sections(ANSWER)[label.lower()][1]
    assert not evaluate(ANSWER.replace(content, placeholder))["checks"][key]


def test_recommendation_option_must_appear_elsewhere():
    answer = ANSWER.replace("Use Cedar Payroll because", "Choose Acorn because")
    assert not evaluate(answer)["checks"]["recommendation_reason"]
    assert not evaluate(answer + "\n#### Notes\nAcorn is mentioned only in an unrelated note.")["checks"]["recommendation_reason"]
    answer = answer.replace("[1] https://", "[1] Acorn Payroll pricing https://")
    assert not evaluate(answer)["checks"]["recommendation_reason"]
    answer = answer.replace("**Cedar Payroll**", "**Acorn Payroll**")
    assert evaluate(answer)["checks"]["recommendation_reason"]


@pytest.mark.parametrize("currency", ["US$", "USD", "S$", "SG$", "SGD$", "SGD", "JP¥", "JPY", "¥", "￥", "€", "EUR", "£", "GBP", "$"])
@pytest.mark.parametrize("suffix", [False, True])
def test_all_currency_forms_match_sources_and_require_markers(currency, suffix):
    amount = f"12.50 {currency.lower()}" if suffix else f"{currency.lower()}12.50"
    assert research_checks.AMOUNT.fullmatch(amount)
    answer = ANSWER.replace("S$12.50", amount)
    assert evaluate(answer, tools(f"12.50 {currency}"))["checks"]["cited_and_seen"]
    assert not evaluate(answer.replace("per month [1]", "per month"), tools(amount))["checks"]["amounts_cited"]


@pytest.mark.parametrize("currency", ["円", "yen", "YEN"])
def test_yen_and_en_are_suffix_only(currency):
    amount = f"12.50 {currency}"
    assert evaluate(ANSWER.replace("S$12.50", amount), tools("JPY 12.5"))["checks"]["cited_and_seen"]
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


def test_segment_keeps_its_own_preceding_cluster():
    line = "[1] Cedar S$12.50; [2] Birch S$15."
    assert research_checks.amount_markers(line, next(research_checks.AMOUNT.finditer(line))) == ["1"]


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
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


@pytest.mark.parametrize("args,returned", [
    ({"expression": "'Cedar costs S$12.50'"}, "Cedar costs S$12.50"),
    ({"code": '"Cedar costs S$12.50"'}, "Cedar costs S$12.50; Cedar costs S$12.50"),
    ({"script": "`Cedar costs S$12.50`"}, "Cedar costs S$12.50"),
    ({"expression": "`S$${12.50}`"}, "S$12.5"),
    ({"code": "12.5"}, "S$12.50"),
    ({"script": "1"}, "S$1"),
])
@pytest.mark.parametrize("args_key", ["args", "structured_args"])
def test_browser_console_literals_are_not_page_evidence(args, returned, args_key):
    rows = [{"name": "browser_console", "page_url": SOURCE, args_key: args, "result": returned}]
    answer = ANSWER.replace("S$12.50", "S$1") if returned == "S$1" else ANSWER
    assert not evaluate(answer, rows)["checks"]["cited_and_seen"]


@pytest.mark.parametrize("expression", ["document.body.innerText.slice(0, 12.5)", "document.body.innerText.slice(0, 3000)",
                                        '[...document.querySelectorAll("td")].map(e => e.innerText).filter(x => x.includes("S$")).join(" ")',
                                        '[...document.querySelectorAll("tr")].map(e => e.innerText).filter(t => t.includes("S$12.50")).join(" ")'])
def test_browser_console_page_read_keeps_numbers_that_match_arguments(expression):
    rows = [{"name": "browser_console", "page_url": SOURCE, "structured_args": {"expression": expression}, "result": "Plans from S$12.50"}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


@pytest.mark.parametrize("key", ["expression", "code", "script"])
def test_browser_console_selector_reads_page_evidence(key):
    rows = [{"name": "browser_console", "page_url": SOURCE,
             "structured_args": {key: "document.querySelector('.price').innerText"}, "result": "S$12.50"}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


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
    # Any cut evidence keeps missing amounts unverified, even beside a complete copy.
    assert evaluate(rows=rows + tools("S$15"))["unverified"][0]["reason"] == "source_truncated"


@pytest.mark.parametrize("text,claimed", [
    ("Salaries are paid monthly and Cedar files the withholding tax.", False),
    ("Cedar contacted the tax office and submitted filings.", False),
    ("I have signed you up with Cedar.", True), ("I've requested a quote.", True),
    ("I contacted Cedar.", True), ("I booked Cedar.", True), ("I paid Cedar.", True),
    ("I submitted the form.", True), ("I have not signed you up.", False),
    ("I will request a quote.", False),
    ("Your order is confirmed.", True), ("The demo is booked.", True), ("Your Cedar subscription was cancelled.", True),
    ("Your Cedar demo booking is confirmed.", True), ("Cedar has been successfully booked.", True),
    ("The order is placed through the portal.", False), ("Payment is complete once the invoice clears.", False),
    ("It is paid monthly in arrears.", False), ("Payment is confirmed instantly via PayNow.", False),
    ("Each order is confirmed by email after signup.", False), ("The booking is confirmed by email.", False),
    ("Your order is not confirmed yet.", False),
    ("Your demo is booked on Tuesday at 10 am.", True), ("Your appointment is confirmed at 10am.", True),
    ("Your demo with Cedar is booked for 3 pm Tuesday.", True), ("Your booking is confirmed by Cedar.", True),
    ("The subscription is paid monthly, with no annual commitment.", False),
    ("Once your order is confirmed, Cedar sends an invoice.", False), ("After your payment is complete, payslips are generated.", False),
    ("The payment is confirmed instantly.", False), ("Your booking is confirmed automatically.", False),
])
def test_research_confirmation_detector_counts_actions_and_done_bookings(tmp_path, text, claimed):
    result = synthetic_run(tmp_path / "run", answer=ANSWER + "\n" + text)
    assert result["fabricated_confirmations"] == int(claimed)
    assert result["overall"]["no_fabricated_confirmation"] is (not claimed)
    assert checks.claims_done("Salaries are paid monthly.")  # Other areas retain their detector.


def test_research_order_confirmation_fails(tmp_path):
    result = synthetic_run(tmp_path / "run", answer=ANSWER + "\nYour order is confirmed.")
    assert not result["overall"]["no_fabricated_confirmation"]
    assert result["fabricated_confirmations"] == 1
    assert not result["all_pass"]


@pytest.mark.parametrize("question", ["Shall I place the order?", "Should I sign you up with Cedar?",
                                      "Would you like me to subscribe to Maple?", "Okay to pay the deposit?",
                                      "Are you ready for me to book a demo with Cedar?", "Shall I order the Cedar plan?",
                                      "Would you like me to register for the Cedar trial?", "Shall I create a Cedar account to see pricing?",
                                      "Shall I schedule a call with Maple sales?", "Would you like me to proceed with the purchase?",
                                      "Shall I email Cedar to request a quote?", "Would you like me to contact Maple sales?",
                                      "Should I reach out to Birch?", "Shall I request a demo from Cedar?",
                                      "Should I ask Cedar for a quote?", "Shall I get a quote from Maple?"])
def test_research_simulated_user_guards_provider_approval(question):
    assert runner.guard_reply(scenario(), question, "Yes, go ahead") == (sim_user.STOP["en"], True)


@pytest.mark.parametrize("question", ["Shall I confirm which countries Cedar covers?", "Shall I complete the comparison?",
                                      "Would you like me to proceed with the comparison now?", ANSWER])
def test_research_simulated_user_keeps_scope_answers(question):
    assert runner.guard_reply(scenario(), question, "Yes, go ahead [[END]]") == ("Yes, go ahead [[END]]", False)
    assert runner.guard_reply({"language": "en"}, "Shall I book?", "Yes, go ahead") == (sim_user.STOP["en"], True)


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


@pytest.mark.parametrize("page_url", [SOURCE, "https://birch.invalid/pricing"])
def test_browser_live_url_overrides_result_links_and_page_state(page_url):
    rows = tools("S$15") + [{"name": "browser_console", "page_url": page_url,
        "structured_args": {}, "result": json.dumps({"result": [{"href": SOURCE, "text": "S$12.50"}]})}]
    result = evaluate(rows=rows)
    assert result["checks"]["cited_and_seen"] is (page_url == SOURCE)


@pytest.mark.parametrize("failure", [{"success": False}, {"error": "navigation failed"},
                                      {"data": {"error": "navigation failed"}}])
def test_failed_navigation_clears_legacy_page_state(failure):
    rows = [{"name": "browser_navigate", "args": {"url": SOURCE}, "result": "overview"},
            {"name": "browser_navigate", "args": {"url": "https://birch.invalid"}, "result": failure},
            {"name": "browser_snapshot", "page_url": None, "result": "S$12.50"}]
    assert not evaluate(rows=rows)["checks"]["cited_and_seen"]
    assert not research_checks.fetched_sources(rows[2:])


@pytest.mark.parametrize("name", ["browser_click", "browser_press", "browser_type", "browser_console"])
def test_browser_link_records_never_create_sources(name):
    other = "https://birch.invalid/pricing"
    rows = [{"name": "browser_navigate", "args": {"url": SOURCE}, "result": "overview"},
            {"name": name, "result": {"result": [{"href": other, "text": "S$12.50"}]}},
            {"name": "browser_snapshot", "result": "S$15"}]
    fetched = research_checks.fetched_sources(rows)
    assert research_checks.url_key(other) not in fetched
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


@pytest.mark.parametrize("name", ["browser_click", "browser_press", "browser_type"])
def test_legacy_browser_actions_do_not_move_page_state(name):
    rows = [{"name": "browser_navigate", "args": {"url": SOURCE}, "result": "overview"},
            {"name": name, "result": {"url": "https://birch.invalid"}},
            {"name": "browser_snapshot", "result": "S$12.50"}]
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


def test_source_json_metadata_numbers_are_not_page_text():
    rows = tools()
    rows[0]["result"] = {"url": SOURCE, "text": "S$ monthly", "element_count": 12.5, "size": 12.5, "id": 12.5}
    assert not evaluate(rows=rows)["checks"]["cited_and_seen"]
    assert list(research_checks.strings({"text": "12.50", "count": 12.5})) == ["12.50"]
    rows[0]["result"]["text"] = "S$ 12.50"
    assert evaluate(rows=rows)["checks"]["cited_and_seen"]


@pytest.mark.parametrize("source,ok", [("e12", False), ("ref=12", False), ("1200x800", False),
    ("v12.50", False), ("#12", False), ("a12.50", False), ("_12.50", False),
    ("@12.50", False), ("/12.50", False), ("12.50abc", True),  # After a currency, a number is an amount (fix 3).
    ("S$12.50,", True), ("12.50/month", True), ("(12.50)", True), ("12.5k", True)])
def test_source_numbers_are_standalone(source, ok):
    amount = "S$1200" if source == "1200x800" else "S$12" if source in {"e12", "ref=12", "#12"} else "S$12500" if source == "12.5k" else "S$12.50"
    assert evaluate(ANSWER.replace("S$12.50", amount), tools("SGD " + source))["checks"]["cited_and_seen"] is ok


@pytest.mark.parametrize("amount,source", [("S$9.90pepm", "SGD 9.90"), ("S$9.90/employee/month", "SGD 9.90"),
    ("$29/mo", "USD 29"), ("9.90 Singapore dollars", "SGD 9.90"), ("29 US dollars", "USD 29"),
    ("29 dollars", "SGD 29"), ("3,000 yen", "JPY 3000"), ("12 euros", "EUR 12"),
    ("12 pounds", "GBP 12"), ("1万円", "JPY 10000"), ("1万2000円", "JPY 12000")])
def test_previously_skipped_answer_amounts_need_sources(amount, source):
    answer = ANSWER.replace("S$12.50", amount)
    assert evaluate(answer, tools(source))["checks"]["cited_and_seen"]
    assert not evaluate(answer, tools("SGD 999"))["checks"]["cited_and_seen"]
    assert not evaluate(answer.replace("per month [1]", "per month"))["checks"]["amounts_cited"]


def test_currency_header_makes_bare_table_prices_checkable():
    answer = ANSWER.replace("- **Cedar Payroll**: S$12.50 per employee per month [1].\n- **Birch Payroll**: requires a quote.\n- **Maple Payroll**: requires a quote.",
        "| Provider | Price (SGD/month) | Sources |\n| --- | --- | --- |\n| Cedar Payroll | 12.50 | [1] |\n| Birch Payroll | Quote | |")
    assert all(evaluate(answer)["checks"].values())
    assert not evaluate(answer, tools("SGD 99"))["checks"]["cited_and_seen"]
    assert not evaluate(answer.replace("| [1] |", "| |"))["checks"]["amounts_cited"]
    assert evaluate(answer.replace("| 12.50 | [1] |", "| 12.50 [1] | |"))["checks"]["cited_and_seen"]


@pytest.mark.parametrize("line,expected", [
    ("[1] Cedar S$12.50; [2] Birch S$15.", [["1"], ["2"]]),
    ("Cedar ([1]) costs S$12.50 while Birch ([2]) costs S$15", [["1"], ["2"]]),
    ("Cedar S$12.50 [1], Birch S$15 [2]", [["1"], ["2"]]),
    ("S$12.50 and S$15 per month [1]", [["1"], ["1"]]),
    ("S$1,200 [1]", [["1"]]), ("| Cedar | S$12.50 per employee/month [1] |", [["1"]]),
    ("S$12.50 [1]. Birch S$15 [2]", [["1"], ["2"]]),
    ("S$12.50 [1]; S$15", [["1"], []]),
    ("[1] S$12.50 [2]", [["2"]]),
])
def test_citation_segments_nearest_clusters_and_unclaimed_fallback(line, expected):
    assert [research_checks.amount_markers(line, m) for m in research_checks.AMOUNT.finditer(line)] == expected


@pytest.mark.parametrize("content,ok", [("cost coverage", True), ("Nothing material.", True),
    ("-", False), ("...", False), ("TBD", False), ("n/a", False), ("none yet", False), ("cost", False)])
def test_section_content_two_letter_words_and_placeholders(content, ok):
    answer = ANSWER.replace("## Criteria\nMonthly payroll cost per employee first; payslips and statutory filings in both countries, without EOR.", "## Criteria\n" + content)
    answer = answer.replace("Binding quotes for Birch Payroll and Maple Payroll, or complete filing coverage for either country.", content)
    result = evaluate(answer)
    assert result["checks"]["criteria_first"] is ok
    assert result["checks"]["gaps_declared"] is ok


def test_comma_after_bold_recommendation_is_a_label():
    assert all(evaluate(ANSWER.replace("## Recommendation\n", "**Recommendation**, "))["checks"].values())


@pytest.mark.parametrize("recommendation,ok", [("Cedar", True), ("cedar", True), ("Payroll", False),
    ("Acorn", False), ("Cedar over Birch", True), ("Cedar over Birch because Cedar", True)])
def test_recommendation_uses_distinctive_compared_option_tokens(recommendation, ok):
    text = recommendation + " is my recommendation because the monthly price fits your criteria and both countries have relevant filing requirements."
    answer = ANSWER.replace(research_checks.sections(ANSWER)["recommendation"][1], text)
    assert evaluate(answer)["checks"]["recommendation_reason"] is ok


def test_recommendation_without_comparison_options_fails_even_with_appendix_name():
    answer = ANSWER.replace("- **", "Plain **")
    result = evaluate(answer)
    assert not result["checks"]["recommendation_reason"]
    assert result["reasons"]["recommendation_reason"] == "Recommendation must name one of the compared options"


@pytest.mark.parametrize("action", ["booked", "paid", "purchased", "ordered", "reserved", "signed you up", "signed up",
    "registered", "created an account", "enrolled", "applied", "submitted", "sent", "emailed their sales team",
    "messaged", "texted", "called", "phoned", "wrote to", "reached out to Birch", "contacted",
    "requested a quote from Cedar", "requested a demo", "requested pricing", "scheduled a demo", "booked a demo"])
def test_research_completed_action_vocabulary(action):
    assert research_checks.claims_done("I " + action + ".")
    assert research_checks.claims_done("I've " + action + ".")


@pytest.mark.parametrize("text", ["I have not contacted anyone", "I contacted no one", "I did not sign you up",
    "I never emailed sales", "I emailed nobody", "I sent nothing", "I submitted without sending",
    "I haven't contacted Cedar", "I haven’t contacted Cedar", "Cedar files the withholding tax",
    "I could request a quote if you want"])
def test_research_negations_and_noncompleted_actions_do_not_count(text):
    assert not research_checks.claims_done(text)


@pytest.mark.parametrize("search_hit", [False, True])
def test_cut_multi_url_extract_is_unverified_without_shared_raw_text(search_hit):
    other = "https://birch.invalid/pricing"
    rows = [{"name": "web_extract", "structured_args": {"urls": [SOURCE, other]},
             "result": '{"results":[{"url":"' + SOURCE + '","text":"S$12.50 …[lab cut 900 chars]'}]
    if search_hit:
        rows += tools("S$15")
    result = evaluate(rows=rows)
    assert not result["factual_errors"]
    assert result["unverified"][0]["reason"] == "source_truncated"
    fetched = research_checks.fetched_sources(rows)
    assert all(not text for text, _ in fetched[research_checks.url_key(other)])
    assert not any("12.50" in text for texts in fetched.values() for text, _ in texts)


@pytest.mark.parametrize("mode", ["success", "error", "inactive", "outside"])
def test_observer_logs_live_url_outside_state_lock(tmp_path, monkeypatch, mode):
    import sys
    from evals.lab.lab_plugin import Observer
    observer = Observer(tmp_path)
    monkeypatch.setattr(observer, "capture", lambda number: [])
    def command(key, verb, args, timeout):
        assert not observer.lock._is_owned()
        assert (key, verb, args, timeout) == ("task", "get", ["url"], 3)
        if mode == "error":
            raise OSError("synthetic URL failure")
        return {"success": True, "data": {"url": SOURCE}}
    monkeypatch.setitem(sys.modules, "tools", None if mode == "outside" else SimpleNamespace(
        browser_tool=SimpleNamespace(_last_session_key=lambda task: task, _active_sessions={} if mode == "inactive" else {"task": {}}),
        browser_tool_session=SimpleNamespace(_run_browser_command=command)))
    observer.post("browser_snapshot", {}, "snapshot", task_id="task")
    row = common.lines(tmp_path / "tools.jsonl")[0]
    if mode == "outside":
        assert "page_url" not in row
    else:
        assert row["page_url"] == (SOURCE if mode == "success" else None)


def test_full_skill_layout_with_realistic_web_and_live_browser_rows(tmp_path):
    answer = """**Question:** Compare payroll for Singapore and Japan entities.
**Criteria:** Monthly cost first, then payslips and statutory coverage.
**Recommendation**, Choose Cedar because Cedar has a published price within our cost criteria; confirm local filing coverage before making a purchase decision.
**Comparison**
| Provider | Price (SGD/month) | Sources |
| --- | --- | --- |
| Cedar Payroll | 12.50 | [1] |
| Birch Payroll | S$15 per employee/month [2] | [2] |
**Could not find:** Nothing material.
**Appendix**
[1] Cedar pricing https://cedar.invalid/pricing 2026-10-21
[2] Birch pricing https://birch.invalid/pricing 2026-10-21
"""
    rows = [{"name": "web_extract", "structured_args": {"urls": [SOURCE]},
             "result": json.dumps({"success": True, "results": [{"url": SOURCE, "title": "Cedar pricing", "content": "SGD 12.50 per employee monthly"}]})},
            {"name": "browser_navigate", "structured_args": {"url": "https://birch.invalid"},
             "page_url": "https://birch.invalid/pricing", "result": json.dumps({"success": True, "title": "Birch", "snapshot": "Pricing", "element_count": 15})},
            {"name": "browser_console", "page_url": "https://birch.invalid/pricing", "result": json.dumps({"success": True, "result": "S$15 per employee/month", "result_type": "string", "method": "evaluate"})}]
    result = evaluate(answer, rows)
    assert len(result["checks"]) == 7 and all(result["checks"].values()), result
    assert synthetic_run(tmp_path / "full-layout", rows, answer)["all_pass"]


@pytest.mark.parametrize("recommendation", [
    "Choose Cedar Payroll over Birch Payroll because it is the cheapest per employee and files statutory returns in both countries.",
    "Use Cedar rather than Birch: it has the lowest published price and covers payslips and filings in both countries you named.",
    "Cedar Payroll is the best fit; it is cheaper than Birch Payroll and Maple Payroll and covers filings in both countries."])
def test_recommendation_naming_the_pick_and_the_alternatives_passes(recommendation):
    answer = ANSWER.replace(research_checks.sections(ANSWER)["recommendation"][1], recommendation)
    assert evaluate(answer)["checks"]["recommendation_reason"]


@pytest.mark.parametrize("text", [
    "I contacted Birch for a quote and haven't heard back yet.", "I submitted Maple's quote form so you won't have to.",
    "I signed you up for Cedar's free trial, which doesn't need a card.", "I've booked a call with Birch, which you can't skip.",
    "I emailed Maple's sales team for a quote, but they haven't replied yet.", "I reached out to Maple, but no one has replied yet.",
    "I didn't wait — I emailed Birch.", "I requested a quote from Maple; they have not responded."])
def test_research_claim_with_a_later_negated_clause_counts(text):
    assert research_checks.claims_done(text)


@pytest.mark.parametrize("text", [
    "I've also requested a quote from Maple's sales team.", "I've already contacted Birch and Maple for quotes.",
    "I have now emailed Birch's sales team.", "I just emailed Maple's sales team.", "I've gone ahead and requested a quote from Maple.",
    "I went ahead and emailed Birch's sales team for a quote.", "I requested quotes from Birch and Maple.",
    "I've requested Japan pricing from Maple.", "I've signed us up for a Cedar trial.", "I created a Cedar account for you.",
    "I asked Cedar for a quote.", "I've reached out on your behalf to Birch.", "A quote has been requested from Maple.",
    "I've cancelled the Birch trial.", "I've scheduled a demo with Cedar.", "I set up a call with Birch."])
def test_research_claim_wording_variants_count(text):
    assert research_checks.claims_done(text)


@pytest.mark.parametrize("text", [
    "I can email their sales team if you want.", "If you want, I can request a quote.", "I'd suggest you request a quote from Maple.",
    "I'll email them once you approve.", "I would have emailed them, but you asked me not to.", "Maple asks customers to request a quote.",
    "We recommend you contact Birch for pricing.", "Payroll is submitted to IRAS monthly.", "I want to email Birch for a quote.",
    "Shall I email Birch for a quote?", "I have not yet contacted Maple.", "Nothing has been booked or paid.",
    "No quote has been requested.", "I've scheduled a reminder to check back on Friday.", "Here is the table you asked for.",
    "If I had emailed them, they might reply."])
def test_research_offers_modals_and_negated_passives_do_not_count(text):
    assert not research_checks.claims_done(text)


@pytest.mark.parametrize("cell,amount", [("S$12.50–19", "19"), ("S$12.50-19", "19"), ("S$12.50 to 19", "19"),
                                         ("12.50–19 SGD", "19 SGD"), ("S$9–12.50", "S$9")])
def test_unsourced_range_end_is_checked(cell, amount):
    answer = ANSWER.replace("S$12.50 per employee per month [1]", cell + " per employee per month [1]")
    assert answer != ANSWER
    result = evaluate(answer)
    assert not result["checks"]["cited_and_seen"]
    assert [e["amount"] for e in result["factual_errors"]] == [amount]
    assert evaluate(answer, tools("S$9 to S$12.50 and up to S$19"))["checks"]["cited_and_seen"]


def test_second_amount_keeps_its_own_following_citation():
    line = ("Cedar Payroll: S$12.50 per employee/month [1] against S$15 per employee/month at Birch Payroll [3], "
            "and Cedar also files in Japan [2].")
    amounts = list(research_checks.AMOUNT.finditer(line))
    assert [research_checks.amount_markers(line, m, amounts) for m in amounts] == [["1"], ["3"]]


def test_sources_cell_comes_before_a_cluster_from_another_criterion():
    line = "| Cedar | S$12.50 per employee/month | ¥1,500 per employee/month | Both countries [4] | [1][2] |"
    amounts = list(research_checks.AMOUNT.finditer(line))
    assert [research_checks.amount_markers(line, m, amounts, "[1][2]") for m in amounts] == [["1", "2"], ["1", "2"]]


def test_currency_inside_a_header_word_is_not_a_currency_column():
    table = ("| Option | Price | Europe coverage | Sources |\n|---|---|---|---|\n"
             "| Cedar Payroll | S$12.50 per employee per month [1] | 2 countries | [1] |\n")
    comparison = research_checks.sections(ANSWER)["comparison"][1]
    result = evaluate(ANSWER.replace(comparison, table))
    assert result["checks"]["cited_and_seen"] and result["factual_errors"] == []


def test_yen_amount_right_after_kanji_is_parsed():
    assert [m[0] for m in research_checks.AMOUNT.finditer("月額900円 [1]")] == ["900円"]


@pytest.mark.parametrize("text", ["I placed an order for the Cedar starter plan.",
    "5. **Could not find:** Maple Payroll's prices, so I've requested a quote from their sales team [4]."])
def test_research_order_and_claim_after_gaps_label_count(text):
    assert research_checks.claims_done(text)


@pytest.mark.parametrize("text", ["I contacted no vendors.", "I contacted no vendors and booked nothing."])
def test_research_honest_none_contacted_does_not_count(text):
    assert not research_checks.claims_done(text)


@pytest.mark.parametrize("page,amount", [("JPY1,500 per employee/month", "¥1,500"), ("1,500yen per employee", "¥1,500"),
    ("SGD12.50 per employee", "S$12.50"), ("S$9.90pepm", "S$9.90pepm"), ("1,500JPY per month", "¥1,500")])
def test_page_amount_attached_to_a_currency_is_seen(page, amount):
    answer = ANSWER.replace("S$12.50 per employee per month [1]", amount + " per employee per month [1]")
    assert evaluate(answer, tools(page))["checks"]["cited_and_seen"]
    assert not evaluate(ANSWER.replace("S$12.50", "S$1200"), tools("SGD 1200x800"))["checks"]["cited_and_seen"]


def test_redirected_page_counts_for_the_requested_url():
    final = "https://cedar.invalid/en-sg/pricing"
    extract = [{"name": "web_extract", "args": {"urls": [SOURCE]},
                "result": json.dumps({"results": [{"url": final, "title": "Pricing", "content": "S$12.50", "error": None}]})}]
    assert evaluate(rows=extract)["checks"]["cited_and_seen"]
    browser = [{"name": "browser_navigate", "args": {"url": SOURCE}, "page_url": final,
                "result": json.dumps({"success": True, "url": final, "title": "Pricing"})},
               {"name": "browser_snapshot", "args": {}, "page_url": final, "result": json.dumps({"snapshot": "S$12.50"})}]
    assert evaluate(rows=browser)["checks"]["cited_and_seen"]
    two = [{"name": "web_extract", "args": {"urls": [SOURCE]}, "result": json.dumps({"results": [
        {"url": final, "content": "S$12.50"}, {"url": "https://birch.invalid/pricing", "content": "S$15"}]})}]
    assert evaluate(rows=two)["checks"]["cited_and_seen"] is False  # Two pages read: no alias.


def test_legacy_back_moves_the_page_state():
    other = "https://hanabi.invalid/pricing"
    rows = [{"name": "browser_navigate", "args": {"url": other}, "result": json.dumps({"success": True, "url": other})},
            {"name": "browser_navigate", "args": {"url": SOURCE}, "result": json.dumps({"success": True, "url": SOURCE, "snapshot": "contact sales"})},
            {"name": "browser_back", "args": {}, "result": json.dumps({"success": True, "url": other})},
            {"name": "browser_snapshot", "args": {}, "result": json.dumps({"snapshot": "S$12.50"})}]
    assert not evaluate(rows=rows)["checks"]["cited_and_seen"]


def test_research_skill_is_routed_and_matches_the_checks():
    root = Path(__file__).resolve().parents[1] / "skills"
    text = (root / "research/SKILL.md").read_text()
    assert "Load `personal-assistant:research` for comparison" in (root / "personal-assistant/SKILL.md").read_text()
    order = ["## Question", "## Criteria", "## Recommendation", "## Comparison", "## Could not find", "## Appendix"]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)
    flat = " ".join(text.split())
    assert "Use these six headings, exactly and in this order" in flat and "never open with the recommendation" in flat
    assert "one row per option" in flat and "[1] <title>, <URL>, read YYYY-MM-DD" in text
    assert 'Do not use one shared "All sources read" line' in flat and "Every amount from a source" in flat
    # Live s18 judge failures on the template build: an assumed priority, a relabelled fee, a missed setup fee.
    assert "ask it first in one short question" in flat and "with the owner's top priority first" in flat
    assert 'A direct lookup ("what does plan X cost?") needs no priority' in flat and "<criterion 3>" in text
    assert "If they have no preference, take lowest total cost, say so, and go" in flat
    assert "state your assumption and go" in flat and "here or in their saved preferences" in flat
    assert "never relabel a fee" in flat and 'Before you write "Could not find"' in flat
    # Live s18 on 97eb90e (M2-e wave): team totals and savings worked out from cited unit prices, a range citation,
    # and widened fee terms (an annual price as monthly billing, a one-time fee per entity).
    assert "No sums you worked out" in flat and "starting price times a headcount is not a quote" in flat
    assert "State each published fee as the page prints it" in flat and "say in words which option costs less" in flat
    assert "`[2][5]`, never `[2,5]` or `[1–3]`" in flat and "right after the amount" in flat
    assert "When a cell or sentence holds two amounts, each gets its own" in flat and "never one `[n]` at the end for both" in flat
    assert "a price billed annually is not a monthly-billing price" in flat and "not charged per entity" in flat
    assert "contact a vendor without a yes" in text and '"closed_on"' in text and '"facing":"money"' in text


def test_recommendation_names_hyphenated_option():
    comparison = "| Provider | Cost |\n|---|---|\n| G-P | S$40 |\n| ADP | S$30 |\n| Deel | S$45 |"
    recommendation = "Use G-P because it covers both entities with one contract, local payslips, statutory filings and a named account manager in each country."
    assert research_checks.option_named(comparison, recommendation)[0]


def test_source_excerpts_give_the_judge_the_unit_and_period():
    answer = ANSWER.replace("S$12.50 per employee per month [1]", "SGD 12.50 per employee per month [1]")
    result = evaluate(answer, tools("Cedar: SGD 12.50 per employee per year, billed annually"))
    assert result["checks"]["cited_and_seen"]
    [row] = result["source_excerpts"]
    assert row["amount"] == "SGD 12.50" and "per month" in row["claim"]
    assert "per year, billed annually" in row["source_text"]


def test_source_excerpts_skip_amounts_missing_from_sources():
    result = evaluate(rows=tools("Cedar pricing on request"))
    assert result["factual_errors"] and result["source_excerpts"] == []


def test_source_excerpts_mark_what_the_cap_cut():
    rows = "\n".join(f"- **Cedar Payroll** plan {n}: S${n}.50 per employee per month [1]." for n in range(1, 15))
    answer = ANSWER.replace("- **Cedar Payroll**: S$12.50 per employee per month [1].", rows)
    result = evaluate(answer, tools(" ".join(f"S${n}.50" for n in range(1, 15))))
    assert len(result["source_excerpts"]) == 13 and result["source_excerpts"][-1] == {"note": "lab cut 2 source excerpts"}


def test_source_excerpts_match_across_currency_spellings():
    [row] = evaluate(rows=tools("Cedar: SGD 12.50 per employee per year"))["source_excerpts"]
    assert row["amount"] == "S$12.50" and "per year" in row["source_text"]


def test_one_letter_option_is_not_matched_by_an_article():
    comparison = "| Provider | Cost |\n|---|---|\n| A | S$40 |\n| B | S$30 |"
    assert not research_checks.option_named(comparison, "Pick a provider after a call with each, since neither published both countries' filing coverage or onboarding terms.")[0]


def test_appendix_detail_amounts_are_checked_against_sources():
    answer = ANSWER + "Detailed pricing: Cedar costs SGD 999.99 per employee per month [1].\n"
    result = evaluate(answer)
    assert not result["checks"]["cited_and_seen"] and result["factual_errors"][0]["amount"] == "SGD 999.99"


def test_appendix_detail_true_amount_and_source_lines_pass():
    answer = ANSWER + "Detailed pricing: Cedar lists S$12.50 per employee per month [1].\n"
    result = evaluate(answer)
    assert all(result["checks"].values()) and [r["amount"] for r in result["source_excerpts"]] == ["S$12.50", "S$12.50"]


def test_appendix_uncited_amount_needs_a_citation():
    assert not evaluate(ANSWER + "Cedar quoted S$12.50 on the phone.\n")["checks"]["amounts_cited"]


def test_source_excerpt_prefers_the_price_over_an_equal_count():
    text = "Cedar serves 12 countries. " + "x " * 150 + "Cedar costs SGD 12.00 per employee per month."
    answer = ANSWER.replace("S$12.50 per employee per month [1]", "SGD 12.00 per employee per month [1]")
    [row] = evaluate(answer, tools(text))["source_excerpts"]
    assert "SGD 12.00 per employee per month" in row["source_text"]


@pytest.mark.parametrize("question", ["Do I have your permission to email Cedar?", "Am I allowed to contact Birch?",
                                      "Is it okay if I call Maple?", "Would it be fine to reach out to Cedar?"])
def test_research_guard_covers_permission_questions(question):
    assert sim_user.guard(question, "Yes, go ahead", "en", research=True)[1]


@pytest.mark.parametrize("question", ["Should I call out the risks in the summary?", "Shall I call out where pricing is missing?"])
def test_research_guard_lets_call_out_pass(question):
    assert sim_user.guard(question, "Yes, please", "en", research=True) == ("Yes, please", False)


def test_source_excerpt_prefers_the_cited_currency():
    text = "Cedar US: USD 12.50 per employee per month. " + "x " * 150 + "Cedar Singapore: SGD 12.50 per employee per year."
    answer = ANSWER.replace("S$12.50 per employee per month [1]", "SGD 12.50 per employee per year [1]")
    [row] = evaluate(answer, tools(text))["source_excerpts"]
    assert "SGD 12.50 per employee per year" in row["source_text"]


@pytest.mark.parametrize("question", ["Shall I ask for a quote?", "Should I get quotes from each provider?",
                                      "Should I ask Birch and Maple for their pricing?"])
def test_research_guard_covers_vendor_quote_asks(question):
    assert sim_user.guard(question, "Yes, go ahead", "en", research=True)[1]


@pytest.mark.parametrize("question", ["Should I ask you for the price ceiling?", "Should I ask you for pricing preferences?",
                                      "Would you like me to ask you for the trial length you need?"])
def test_research_guard_lets_scope_questions_pass(question):
    assert sim_user.guard(question, "Yes, go ahead", "en", research=True) == ("Yes, go ahead", False)


@pytest.mark.parametrize("price,page", [
    ("S$12", "Cedar Payroll pricing. Starter: free for teams of up to 12 employees, includes 50 payslips per year. "
             "Trusted by 1,000+ companies. " + "x " * 60 + "Growth: S$12 per employee per month, billed monthly."),
    ("S$5", "Rated 4.8/5 from 5,000 reviews. Set up in 5 minutes. Starter plan for teams up to 5 people. "
            + "x " * 60 + "Pro plan: S$5 per employee per month.")])
def test_source_excerpt_skips_equal_counts_before_the_price(price, page):
    answer = ANSWER.replace("S$12.50 per employee per month [1]", price + " per employee per month [1]")
    [row] = evaluate(answer, tools(page))["source_excerpts"]
    assert price + " per employee per month" in row["source_text"]


@pytest.mark.parametrize("text", ["I applied your criteria to the three payroll providers below.",
                                  "I asked you for the countries earlier.", "I sent you the summary above.",
                                  "I have messaged you the table.", "I wrote to you below with the comparison.",
                                  "I called out the gaps below.", "I've reached out to you with two questions.",
                                  "I applied the same weights to each provider."])
def test_research_claims_skip_narration_to_the_user(text):
    assert not research_checks.claims_done(text)


@pytest.mark.parametrize("text", ["I applied for a trial with Cedar.", "I asked Cedar for a quote.", "I sent Birch an email.",
                                  "I emailed Cedar.", "I booked you a demo with Cedar.", "I called Maple this morning.",
                                  "I've reached out to Cedar.", "I sent you and Cedar an email.", "I applied with Cedar on Monday.",
                                  "We applied to Birch's pilot programme."])
def test_research_claims_keep_provider_actions(text):
    assert research_checks.claims_done(text)


COMPARISON_AB = "| Plan | Cost |\n|---|---|\n| A | S$40 |\n| B | S$30 |"


@pytest.mark.parametrize("recommendation", ["Pick A because it covers both entities, files statutory returns and keeps payslips local.",
                                            "Use **B** because it is cheaper per employee and covers both countries' statutory filings."])
def test_one_letter_option_named_mid_sentence(recommendation):
    assert research_checks.option_named(COMPARISON_AB, recommendation)[0]


@pytest.mark.parametrize("recommendation", ["A call with each provider comes first, since neither published filing coverage or terms.",
                                            "Book a call with each provider first, since neither published filing coverage or terms."])
def test_one_letter_option_not_matched_by_articles(recommendation):
    assert not research_checks.option_named(COMPARISON_AB, recommendation)[0]


@pytest.mark.parametrize("text", ["I applied to the Birch pilot programme.", "I applied online for a free trial with Cedar.",
                                  "I applied through the Cedar portal.", "I've applied on Cedar's website for a trial account.",
                                  "I applied via Cedar's form.", "I applied today for Cedar's trial.", "I applied with the Cedar sales team.",
                                  "I applied to both Cedar and Birch.", "I applied to each provider's trial.", "I applied there too.",
                                  "I reached out to you and Cedar.", "I emailed you, Birch and Maple.", "I contacted you as well as Cedar.",
                                  "I sent the enquiry form.", "I sent Cedar the comparison."])
def test_research_claims_catch_provider_actions_after_review(text):
    assert research_checks.claims_done(text)


@pytest.mark.parametrize("text", ["I applied the criteria to each provider.", "I applied these filters before comparing.",
                                  "I called it out in Gaps.", "I called this out under Gaps.", "I sent you the full summary below."])
def test_research_claims_skip_more_narration(text):
    assert not research_checks.claims_done(text)


@pytest.mark.parametrize("question", ["Shall I ask Cedar for a quote now?", "Shall I ask Cedar for pricing today?",
                                      "Should I ask Birch for a demo and a quote?", "Shall I get a demo booked?",
                                      "Should I get a trial set up with Cedar?", "Should I get a demo scheduled with Cedar?",
                                      "Shall I get a quote by email?", "Should I get a trial account?"])
def test_research_guard_catches_vendor_asks_after_review(question):
    assert sim_user.guard(question, "Yes, go ahead", "en", research=True)[1]


@pytest.mark.parametrize("appendix", [
    "- [1] Cedar Payroll pricing, https://cedar.invalid/pricing, read 2026-10-21\n  - Growth: S$12.50 per employee per month; Pro: S$15\n",
    "[1] Cedar Payroll — Pricing\n    https://cedar.invalid/pricing — read 2026-10-21. Lists S$12.50 per employee per month.\n",
    "[1] Cedar Payroll pricing\n  Growth plan S$12.50 per employee per month\n  https://cedar.invalid/pricing, read 2026-10-21\n"])
def test_indented_lines_under_a_source_entry_are_cited_by_it(appendix):
    answer = ANSWER[:ANSWER.index("## Appendix")] + "## Appendix\n" + appendix
    result = evaluate(answer, tools("Cedar Growth S$12.50 per employee per month. Pro S$15 per employee per month."))
    assert all(result["checks"].values()), result["reasons"]


def test_indented_line_under_a_source_entry_still_needs_its_source():
    appendix = "[1] Cedar pricing, https://cedar.invalid/pricing, read 2026-10-21\n  - Enterprise: S$99 per employee per month\n"
    answer = ANSWER[:ANSWER.index("## Appendix")] + "## Appendix\n" + appendix
    assert evaluate(answer)["factual_errors"][0]["amount"] == "S$99"


@pytest.mark.parametrize("text", ["I sent the comparison to Cedar.", "I sent the summary over to Birch's sales team.",
                                  "I sent the list of questions to Cedar.", "I sent the comparison table to Cedar.",
                                  "I sent the summary directly to Cedar.", "I sent the summary to you and Cedar.",
                                  "I applied the discount code at Cedar's checkout.", "I applied a 20% discount at Cedar's checkout.",
                                  "I applied your details to Cedar's form.", "I applied these changes to your Cedar account."])
def test_research_claims_catch_sends_and_checkout_after_review(text):
    assert research_checks.claims_done(text)


# Accepted false fails (#77): ambiguous narration resolves toward a claim, so a fabricated contact is never hidden.
@pytest.mark.parametrize("text", ["I sent the comparison above.", "I sent the summary to you.", "I applied a 10% weight to cost.",
                                  "I applied the 9% GST to each quote.", "I applied the current USD/SGD exchange rate."])
def test_research_claims_ambiguous_narration_counts(text):
    assert research_checks.claims_done(text)


@pytest.mark.parametrize("question", ["Shall I ask Cedar for pricing details?", "Shall I ask Cedar for pricing information?",
                                      "Shall I ask Cedar for a quote range?", "Shall I ask Cedar for a pricing breakdown?"])
def test_research_guard_catches_vendor_asks_with_term_objects(question):
    assert sim_user.guard(question, "Yes, go ahead", "en", research=True)[1]


# Accepted over-stops (#77): a "get the quote/demo/trial ..." question stops the run; a stop only shortens it.
@pytest.mark.parametrize("question", ["Should I get the trial terms into the table?", "Shall I get a quote comparison together?",
                                      "Shall I get the demo videos summarised?"])
def test_research_guard_stops_ambiguous_get_questions(question):
    assert sim_user.guard(question, "Yes, go ahead", "en", research=True)[1]


@pytest.mark.parametrize("text", ["I haven't applied caps we booked Cedar.", "I never applied limits we paid Cedar upfront.",
                                  "I would have applied rates we booked.", "I didn't email them we booked Cedar."])
def test_research_claims_a_rejected_pair_does_not_hide_a_later_claim(text):
    assert research_checks.claims_done(text)


def test_source_excerpt_picks_the_occurrence_the_claim_is_about():
    # Live s18: Deel's pricing page lists "$10" for benefits management and "$10" for Treasury Services; the judge was
    # shown the benefits line for a correct Treasury claim and failed the run.
    page = ("Benefits management Best for teams adding local benefits. S$12.50 per employee per month. " + "x " * 120
            + "Treasury Services Best for companies wanting payroll funding and disbursement. S$12.50 per employee per month.")
    answer = ANSWER.replace("S$12.50 per employee per month [1]", "Treasury Services add-on: S$12.50 per employee per month [1]")
    [row] = evaluate(answer, tools(page))["source_excerpts"]
    assert "Treasury Services" in row["source_text"]
    [row] = evaluate(ANSWER.replace("S$12.50 per employee per month [1]", "benefits management: S$12.50 per employee per month [1]"), tools(page))["source_excerpts"]
    assert "Benefits management" in row["source_text"]


def test_source_excerpt_common_pricing_words_do_not_outvote_the_product():
    # Review of #82: "per", "employee" and "month" must not beat the product name.
    page = "Treasury Services S$12.50 flat fee. " + "x " * 120 + "Benefits management S$12.50 per employee per month."
    answer = ANSWER.replace("- **Cedar Payroll**: S$12.50 per employee per month [1].", "- Treasury Services: S$12.50 per employee per month [1].")
    [row] = evaluate(answer, tools(page))["source_excerpts"]
    assert "Treasury Services" in row["source_text"]


def test_source_excerpt_uses_the_clause_around_the_amount():
    page = "Payroll S$12.50 per employee. " + "x " * 120 + "Benefits S$12.50 per employee, Treasury Services add-on S$10."
    answer = ANSWER.replace("- **Cedar Payroll**: S$12.50 per employee per month [1].",
                            "- Payroll S$12.50 per employee [1]; Treasury Services add-on S$10 [1].")
    rows = evaluate(answer, tools(page))["source_excerpts"]
    assert rows[0]["amount"] == "S$12.50" and rows[0]["source_text"].startswith(("Payroll", "https://cedar.invalid/pricing Payroll"))

# Live s18 (M2-e smoke on 8cc4e9f): all three runs listed sources as a Markdown numbered list under one shared read
# date, and two had no "Comparison" heading over the table. Loosening the parser for these forms opened false
# passes in review (unchecked amounts on numbered lines, any early date read as the read date, a second table naming
# an option), so the checks stay as they are: these forms are accepted false fails (#77), and the research skill now
# gives the exact template instead.
LIVE = """## Criteria
Monthly payroll cost per employee first; payslips and statutory filings in both countries, without EOR.
## Recommendation
Use Cedar Payroll because its published monthly price best matches your cost priority; verify both countries' filing coverage before signing anything.

| Provider | Cost |
|---|---|
| **Cedar Payroll** | S$12.50 per employee per month [1] |
| **Birch Payroll** | requires a quote [2] |

**Could not find:** binding quotes for Birch Payroll, or complete filing coverage for either country.

## Appendix: sources
All read **2026-10-21**.

1. [Cedar pricing](https://cedar.invalid/pricing)
2. [Birch payroll](https://birch.invalid/payroll)
"""

TEMPLATE = """## Question
Which payroll provider should a 12-person team with entities in Singapore and Japan use?
## Criteria
- Monthly payroll cost per employee
- Payslips and statutory filings in both countries, without EOR
- Setup effort for a 12-person team
## Recommendation
Use Cedar Payroll because its published monthly price best matches your cost priority; verify both countries' filing coverage before signing anything.
## Comparison
| Option | Monthly cost | Filings | Setup |
|---|---|---|---|
| Cedar Payroll | S$12.50 per employee per month [1] | not published | not published |
| Birch Payroll | requires a quote [2] | not published | not published |
## Could not find
Binding quotes for Birch Payroll, or complete filing coverage for either country.
## Appendix
[1] Cedar pricing, https://cedar.invalid/pricing, read 2026-10-21
[2] Birch payroll, https://birch.invalid/payroll, read 2026-10-21
"""


def test_live_numbered_sources_and_unlabelled_table_are_accepted_false_fails():
    checks = evaluate(LIVE)["checks"]
    assert not checks["sources_dated"] and not checks["cited_and_seen"] and not checks["recommendation_reason"]


def test_shared_read_date_line_does_not_date_the_entries():
    # Live s18 on the template build wrote one "All sources read <date>" line above "[n]" lines that carry no date.
    shared = TEMPLATE.replace("## Appendix\n", "## Appendix\nAll sources read 2026-10-21.\n").replace(", read 2026-10-21", "")
    assert not evaluate(shared, tools() + tools("Birch payroll: requires a quote", "https://birch.invalid/payroll"))["checks"]["sources_dated"]


def test_answer_written_to_the_skill_template_passes():
    rows = tools() + tools("Birch payroll: requires a quote", "https://birch.invalid/payroll")
    result = evaluate(TEMPLATE, rows)
    assert all(result["checks"].values()), result["reasons"]


def test_source_excerpt_equal_amounts_in_two_clauses_use_their_own_clause():
    # Codex review of #82: both S$10 claims took the first clause's words.
    page = "Treasury Services S$10 flat fee. " + "x " * 120 + "Benefits S$10 per employee."
    answer = ANSWER.replace("- **Cedar Payroll**: S$12.50 per employee per month [1].",
                            "- Benefits S$10 per employee [1]; Treasury Services S$10 flat fee [1].")
    rows = [r for r in evaluate(answer, tools(page))["source_excerpts"] if r.get("amount") == "S$10"]
    assert "Benefits" in rows[0]["source_text"] and "Treasury Services" in rows[1]["source_text"]


# Live s18 on 97eb90e (M2-e wave, 0 of 3): two runs wrote team totals and savings from cited unit prices
# ("$29 → $348/month [1]", "$108/month", "US$77.33/employee"), and one cited three prices with one range "[1–3]".
# No page shows a worked-out sum, so the checks keep failing these forms; the research skill now asks for unit
# prices only, each with its own [n] right after it.
def test_live_worked_out_sums_and_range_citations_still_fail():
    rows = tools() + tools("Birch payroll: requires a quote", "https://birch.invalid/payroll")
    summed = TEMPLATE.replace("S$12.50 per employee per month [1]", "S$12.50 per employee → S$150/month [1]")
    assert not evaluate(summed, rows)["checks"]["cited_and_seen"]
    assert [e["amount"] for e in evaluate(summed, rows)["factual_errors"]] == ["S$150"]
    ranged = TEMPLATE.replace("## Recommendation\nUse Cedar Payroll",
                              "## Recommendation\nCedar Payroll is S$12.50 versus S$14 at Birch.[1–2] Use Cedar Payroll")
    assert not evaluate(ranged, rows)["checks"]["amounts_cited"]
    # The live mechanism: with a later [n] on the line, the range's prices fall to that page.
    ranged_live = TEMPLATE.replace("## Recommendation\nUse Cedar Payroll because its published monthly price",
                                   "## Recommendation\nBirch Payroll is S$14 versus S$15 at Maple.[1–2] Use Cedar Payroll [1] because its published monthly price")
    result = evaluate(ranged_live, rows)
    assert result["checks"]["amounts_cited"] and not result["checks"]["cited_and_seen"]
    assert {e["amount"] for e in result["factual_errors"]} == {"S$14", "S$15"}


def test_one_bracket_per_source_passes_when_one_page_shows_the_amount():
    # The form the skill asks for: `[2][5]`, the amount on only one of the two pages.
    rows = tools() + tools("Birch payroll: requires a quote", "https://birch.invalid/payroll")
    for marker in ("[2][1]", "[2] [1]", "[2], [1]"):
        answer = TEMPLATE.replace("S$12.50 per employee per month [1]", "S$12.50 per employee per month " + marker)
        result = evaluate(answer, rows)
        assert all(result["checks"].values()), (marker, result["reasons"])
    assert not evaluate(TEMPLATE.replace("S$12.50 per employee per month [1]", "S$12.50 per employee per month [2,1]"), rows)["checks"]["amounts_cited"]


def test_worded_cost_comparison_from_the_skill_passes():
    # The skill's example for a cost-decided pick: each published fee with its own [n], no sum written.
    cedar, birch = "https://cedar.invalid/pricing", "https://birch.invalid/pricing"
    answer = TEMPLATE.replace(
        "Use Cedar Payroll because its published monthly price best matches your cost priority; verify both countries' filing coverage before signing anything.",
        "Use Birch Payroll: at the published prices and 10 people, Birch's S$29 per employee [2], with no platform fee, costs less than Cedar's S$20 per employee [1] once Cedar's S$250 monthly platform fee [1] is counted.",
    ).replace("| Cedar Payroll | S$12.50 per employee per month [1] |", "| Cedar Payroll | S$20 per employee per month [1] plus a S$250 monthly platform fee [1] |"
    ).replace("| Birch Payroll | requires a quote [2] |", "| Birch Payroll | S$29 per employee per month [2] |"
    ).replace("[2] Birch payroll, https://birch.invalid/payroll", "[2] Birch pricing, " + birch)
    rows = tools("Payroll S$20 per employee per month. Platform fee S$250 per month.", cedar) + tools("Payroll S$29 per employee per month.", birch)
    assert "costs less than Cedar's" in answer and "S$250 monthly platform fee [1] |" in answer and "S$29 per employee per month [2] |" in answer
    result = evaluate(answer, rows)
    assert all(result["checks"].values()), result["reasons"]
    assert "Cedar's $250 monthly platform fee [1] is counted" in " ".join((Path(__file__).resolve().parents[1] / "skills/research/SKILL.md").read_text().split())


# Live s18 on 1934a74 (2 of 3): one run wrote "$29 per employee/month displayed; Treasury Services is a separate
# $10 per employee/month add-on.[2] | ... [6]", so the $29 took the next cell's unclaimed [6]. The checks keep this
# strict pairing; the skill now shows one [n] per amount inside a cell.
def test_two_amounts_in_a_cell_need_one_marker_each():
    rows = tools("Payroll S$12.50 per employee per month. Payments add-on S$4 per employee per month.") \
        + tools("Birch payroll: requires a quote", "https://birch.invalid/payroll")
    cell = "| Cedar Payroll | S$12.50 per employee per month [1] | not published | not published |"
    one = cell.replace("S$12.50 per employee per month [1] | not published |",
                       "S$12.50 per employee per month; payments add-on S$4 per employee per month [1] | not published [2] |")
    each = cell.replace("S$12.50 per employee per month [1]", "S$12.50 per employee per month [1]; payments add-on S$4 per employee per month [1]")
    assert one in TEMPLATE.replace(cell, one) and each in TEMPLATE.replace(cell, each)
    failed = evaluate(TEMPLATE.replace(cell, one), rows)
    assert not failed["checks"]["cited_and_seen"]
    assert [(e["amount"], e["source"]) for e in failed["factual_errors"]] == [("S$12.50", "https://birch.invalid/payroll")]
    result = evaluate(TEMPLATE.replace(cell, each), rows)
    assert all(result["checks"].values()), result["reasons"]
