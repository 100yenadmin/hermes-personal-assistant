"""#275: a cart subtotal read as innerText keeps its label; a total for N people is not grounded on a per-person line."""
import pytest

from evals.lab import judge

MENU = 'Quick Add 牛めし（味噌汁付） ¥570 • 96% (107861)\n牛めし（味噌汁付） ¥570\nAdd 1 to order • ¥570'
CART = '牛めし（味噌汁付）\n\n牛めし: 並盛\n\nつゆ: つゆ普通\n\n¥570\n1\nSubtotal\n¥570\nAdd ¥930 to save 10% with promotions\nGo to checkout'


def evidence(claim, *pages, step=2):
    return judge.claim_evidence([{'role': 'assistant', 'step': step, 'content': claim}],
                                [{'step': step, 'name': name, 'result': text} for name, text in pages])


def test_cart_subtotal_line_beats_menu_rows_that_share_only_the_number():
    rows = evidence('| Verified cart subtotal | **JPY 570** |', ('browser_snapshot', MENU), ('browser_console', CART))
    assert rows == [{'step': 2, 'figure': 'JPY 570', 'seen': 'Subtotal ¥570'}]


@pytest.mark.parametrize('text,row', [
    ('Subtotal\n¥570', 'Subtotal ¥570'),
    ('Subtotal\n\n¥570', 'Subtotal ¥570'),
    ('Subtotal\n\n\n¥570', '¥570'),  # more than one blank line: no label
    ('Delivery fee ¥150\n¥570', '¥570'),  # a line with its own figure is not a label
    ('- StaticText "Subtotal"\n¥570', '¥570'),  # tree rows keep their own neighbour logic
    ('Subtotal\n¥570 incl. tax', '¥570 incl. tax'),  # only a figure-only line takes a label
    ('Korean Air\n8:40 PM', '8:40 PM'),  # times keep their own rows
    ('Total\n12,000円', 'Total 12,000円'),
])
def test_figure_only_line_takes_the_label_above_it(text, row):
    assert row in list(judge.page_rows([text]))


VENUE = 'A deposit of 10,000 yen per person will be required at the time of booking, but payment will not be made.'
OTHER = 'Course reservation We will keep 20,000 yen per person as a deposit. Payment must be made in full at the restaurant.'
CLAIM = '- **Required deposit:** **JPY 10,000 per person — JPY 20,000 for two.**'


def test_total_for_two_is_not_grounded_on_another_venues_per_person_line():
    rows = evidence(CLAIM, ('browser_snapshot', VENUE), ('web_search', OTHER), step=1)
    assert rows == [{'step': 1, 'figure': 'JPY 10,000', 'seen': VENUE[:160]},
                    {'step': 1, 'figure': 'JPY 20,000', 'seen': None, 'group_total': 2, 'computed_from': '2 × JPY 10,000'}]


def test_total_for_two_still_grounds_on_a_line_that_states_the_total():
    rows = evidence('¥20,000 for two', ('browser_snapshot', 'Deposit for 2 guests: ¥20,000\n' + OTHER), step=1)
    assert rows == [{'step': 1, 'figure': '¥20,000', 'seen': 'Deposit for 2 guests: ¥20,000', 'group_total': 2}]


@pytest.mark.parametrize('claim,group', [
    ('¥20,000 for two', 2), ('¥20,000 (for 2)', 2), ('¥20,000 total for three', 3), ('¥20,000（2名分）', 2),
    ('₩40,000 2인분', 2), ('¥20,000 for 2 nights', None), ('¥20,000 for one', None), ('¥20,000 per person', None),
])
def test_group_size_reads_only_a_total_for_several_people(claim, group):
    rows = evidence(claim, ('browser_snapshot', 'Price ¥20,000 ₩40,000'), step=0)
    assert rows[0].get('group_total') == group


@pytest.mark.parametrize('line,per', [
    ('We will keep 20,000 yen per person', True), ('お一人様 ¥20,000', True), ('¥20,000 / person', True),
    ('1인당 20,000원', True), ('Deposit ¥20,000 for the table', False), ('¥120,000 per person', False),
    ('¥20,000 total; ¥5,000 per person', False),
])
def test_per_person_reads_the_number_itself(line, per):
    assert judge.per_person(line, '20000') is per


@pytest.mark.parametrize('claim,source', [
    ('JPY 10,000 per person — JPY 20,000 for two.', '2 × JPY 10,000'),
    ('JPY 10.25 per person; ¥20.50 for two', '2 × JPY 10.25'),  # JPY and ¥ are one currency
    ('JPY 20,000 for two (JPY 10,000 per person)', '2 × JPY 10,000'),
    ('¥10,000 per person, ¥30,000 for two', None),  # wrong product
    ('$10 per person, ¥20 for two', None),  # different currency
    ('$33.333 per person, $100 for three', None),  # exact product only
    ('Deposit ¥10,000 per person; dinner ¥20,000 for two', None),  # another item's per-person figure
])
def test_computed_from_needs_the_same_item_unit_and_product(claim, source):
    rows = evidence(claim, ('browser_snapshot', 'x'), step=0)
    assert next(r for r in rows if r.get('group_total')).get('computed_from') == source


# Round-1 review inputs (Codex sol-high and a fresh Claude reviewer), kept verbatim.
@pytest.mark.parametrize('claim,page,seen', [
    ('Lunch special ¥20,000', '¥10,000\nLunch special\n¥20,000\nDinner\nLunch ¥20,000 unavailable', 'Lunch ¥20,000 unavailable'),
    ('Beef bowl ¥570', '¥500\nBeef bowl\n¥570\nPork bowl', '¥570'),
    ('Order total ¥570', 'Order\n¥570\nTotal savings\n¥570\nOrder history\n¥570\nTotal ¥570 due', 'Total ¥570 due'),
])
def test_item_names_never_join_a_price(claim, page, seen):
    assert evidence(claim, ('browser_console', page), step=0)[0]['seen'] == seen


@pytest.mark.parametrize('page', ['Drinks\n\n¥300\nCola\n¥150', 'Don’t replace\n¥330'])
def test_list_headings_and_options_are_not_labels(page):
    assert not any(row.endswith(('¥300', '¥330')) and ' ' in row for row in judge.page_rows([page]))


@pytest.mark.parametrize('claim,page,seen', [
    ('Deposit ¥20,000 for two', 'Deposit ¥20,000 total; per person ¥10,000', 'Deposit ¥20,000 total; per person ¥10,000'),
    ('Deposit ¥20,000 for two', 'Deposit ¥20,000 total; USD 20,000 per person', 'Deposit ¥20,000 total; USD 20,000 per person'),
    ('¥20,000 for two', 'Set menu ¥10,000 per person ¥20,000 total for 2', 'Set menu ¥10,000 per person ¥20,000 total for 2'),
    ('¥20,000 for two', 'Plan A ¥20,000 per person; Plan B ¥20,000 for two', 'Plan A ¥20,000 per person; Plan B ¥20,000 for two'),
])
def test_a_line_that_also_states_the_total_is_kept(claim, page, seen):
    assert evidence(claim, ('browser_snapshot', page), step=0)[0]['seen'] == seen


@pytest.mark.parametrize('claim,page', [
    ('Deposit ¥20,000 for two', 'Deposit (Yen): total for two 20000\nOther venue ¥20,000 per person'),
    ('¥20,000 for two', 'Course ¥20,000 per person\nDeposit (yen) for 2 guests: 20000'),
])
def test_skipped_per_person_line_leaves_the_label_match(claim, page):
    row = evidence(claim, ('browser_snapshot', page), step=0)[0]
    assert row['seen'] == page.splitlines()[0 if page.startswith('Deposit') else 1] and row['label_match'] is True


@pytest.mark.parametrize('claim,page', [
    ('Hotel ¥20,000 for two weeks per person', 'Hotel ¥20,000 per person for two weeks'),
    ('¥20,000 for two weeks', 'Weekly pass ¥20,000 per person'),
])
def test_durations_are_not_group_totals(claim, page):
    row = evidence(claim, ('browser_snapshot', page), step=0)[0]
    assert row['seen'] == page and 'group_total' not in row


@pytest.mark.parametrize('suffix', [' for 2 weeks', ' for 2 hrs', ' for 2 minutes', ' for 2 rooms', ' for 2 tickets',
                                    ' for 2-night stay', ' for two-night', ' for two courses per person', ' for 2026', ' for 30 min'])
def test_group_size_ignores_units_that_are_not_people(suffix):
    assert judge.group_size(suffix) is None


@pytest.mark.parametrize('line', ['20,000円／人', '一人あたり20,000円', 'お一人様 ￥20,000', '¥20,000 each', '¥20,000 per adult',
                                  '¥20,000（1人あたり）', 'お一人様 ２０，０００円'])
def test_common_per_person_forms(line):
    assert judge.per_person(line, '20000') is True


def test_eleven_people_is_not_one_person():
    assert judge.per_person('11名 ¥20,000', '20000') is False
