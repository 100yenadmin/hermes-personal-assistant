"""#275: a price read as innerText keeps its summary label ("Subtotal ¥570"); item names and columns never pair."""
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
    ('Total\n12,000円', 'Total 12,000円'),
    ('Subtotal:\n¥570', 'Subtotal: ¥570'),
    ('合計（税込）\n¥570', '合計（税込） ¥570'),
    ('Total (tax incl.)\n¥570', 'Total (tax incl.) ¥570'),
    ('Items subtotal\n¥570', 'Items subtotal ¥570'),
    ('Estimated tax\n¥57', 'Estimated tax ¥57'),
    ('Delivery fee\n¥150', 'Delivery fee ¥150'),
    ('배달비\n3,000원', '배달비 3,000원'),
    ('Subtotal\n\n\n¥570', '¥570'),  # more than one blank line: no label
    ('Delivery fee ¥150\n¥570', '¥570'),  # a line with its own figure is not a label
    ('- StaticText "Subtotal"\n¥570', '¥570'),  # tree rows keep their own neighbour logic
    ('Subtotal\n¥570 incl. tax', '¥570 incl. tax'),  # only a price-only line takes a label
    ('Korean Air\n8:40 PM', '8:40 PM'),  # times keep their own rows
    ('Taxi\n¥570', '¥570'),
])
def test_price_only_line_takes_the_summary_label_above_it(text, row):
    assert row in list(judge.page_rows([text]))


# Inputs from the two reviews of this change, kept verbatim.
@pytest.mark.parametrize('claim,page,seen', [
    ('Lunch special ¥20,000', '¥10,000\nLunch special\n¥20,000\nDinner\nLunch ¥20,000 unavailable', 'Lunch ¥20,000 unavailable'),
    ('Beef bowl ¥570', '¥500\nBeef bowl\n¥570\nPork bowl', '¥570'),
    ('Order total ¥570', 'Order\n¥570\nTotal savings\n¥570\nOrder history\n¥570\nTotal ¥570 due', 'Total ¥570 due'),
])
def test_item_names_never_join_a_price(claim, page, seen):
    assert evidence(claim, ('browser_console', page), step=0)[0]['seen'] == seen


@pytest.mark.parametrize('page', ['Drinks\n\n¥300\nCola\n¥150', 'Don’t replace\n¥330'])
def test_list_headings_and_options_are_not_labels(page):
    rows = list(judge.page_rows([page]))
    assert '¥300' in rows or '¥330' in rows
    assert not any(row in ('Drinks ¥300', 'Don’t replace ¥330') for row in rows)


@pytest.mark.parametrize('page', ['Subtotal\nTotal\n¥570\n¥627', 'Total\n¥570\n¥627'])
def test_stacked_labels_or_prices_do_not_pair(page):
    assert not any(row.startswith(('Total ¥', 'Subtotal ¥')) for row in judge.page_rows([page]))
