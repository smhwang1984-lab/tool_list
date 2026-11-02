"""v2.2.6 — 밀링 SO: 주석 "(SO nn ...)"이 기준, 공구명 뒤 [SO nn]과 다르면 강조."""
import re
from pathlib import Path

import pytest

import NC_Tool_List as app

ROOT = Path(__file__).resolve().parent.parent
NEW_NC = ROOT / 'test files' / 'new.NC'


def _block(name_so, comment_so, tool='T1'):
    name_part = ' [SO %s]' % name_so if name_so is not None else ''
    comment = ' (SO    %s GL   115.000000 PL )\n' % comment_so if comment_so is not None else ''
    return (
        'N1(#1: Tool Change)\n'
        ' (%s // D50 F.MIL%s // %s BT40-FMC22-90)\n' % (tool, name_part, tool)
        + comment + ' (LCF 15.000000 FL 15.000000 F 4)\nM6 %s\n' % tool
    )


def _row(text):
    return app.parse_program(text)[0]


def test_old_format_unchanged():
    row = _row(_block('40.5', None))
    assert row['SO'] == '40.5' and row['SO_ALERT'] == '' and row['SO_CMT'] == ''


def test_comment_only_when_name_has_no_so():
    row = _row(_block(None, '85.000000'))
    assert row['NAME'] == 'D50 F.MIL' and row['HOLDER'] == 'BT40-FMC22-90'
    assert row['SO'] == '85' and row['SO_ALERT'] == ''


def test_same_value_no_alert_and_decimals_equal():
    row = _row(_block('90', '90.000000'))
    assert row['SO'] == '90' and row['SO_ALERT'] == ''


def test_mismatch_shows_comment_so_and_alert():
    row = _row(_block('80', '85.000000'))
    assert row['SO'] == '85'
    assert row['SO_ALERT'] == '공구명 SO 80 / 주석 SO 85'


def test_mismatch_in_later_block_of_same_tool_flags_row():
    text = _block('80', '80.000000') + _block('80', '85.000000').replace('N1', 'N2')
    assert _row(text)['SO_ALERT'] != ''


def test_pdf_marks_only_alert_row(tmp_path):
    rows = [
        {'NO': 'T01', 'SO': '85', '_SO_ALERT': 'x'},
        {'NO': 'T02', 'SO': '40'},
    ]
    fonts = app.register_pdf_fonts()
    table = app.make_pdf_table(rows, app.normalized_pdf_metadata({}), 700, fonts)
    so_col = [k for k, _ in app.COLUMNS].index('SO')
    assert table._cellStyles[2][so_col].color == app.PDF_ALERT_RED
    assert table._cellStyles[3][so_col].color == app.PDF_FONT_BLUE
    out = app.export_tool_list_pdf(tmp_path / 'a.pdf', rows, {})
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(not NEW_NC.exists(), reason='test file missing')
def test_new_nc_all_tools_match():
    rows = app.parse_program(NEW_NC.read_text(encoding='utf-8', errors='replace'))
    assert [r['SO'] for r in rows] == ['90', '80', '50', '40', '33', '80', '45', '50']
    assert all(r['SO_ALERT'] == '' for r in rows)
    assert rows[0]['HOLDER'] == 'BT40-FMC22-90'


@pytest.mark.parametrize('name_so,comment_so,shown,alert', [
    ('90', '90.000000', '90', False),
    ('80', '85.000000', '85', True),
    (None, '85.000000', '85', False),
])
def test_holder_without_tool_number(name_so, comment_so, shown, alert):
    text = _block(name_so, comment_so).replace('// T1 BT40', '// BT40')
    row = _row(text)
    assert row['NAME'] == 'D50 F.MIL' and row['HOLDER'] == 'BT40-FMC22-90'
    assert row['SO'] == shown and bool(row['SO_ALERT']) is alert
