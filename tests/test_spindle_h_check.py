"""v2.3.2 — 밀링: 프로그램 `S… M3` ↔ 툴리스트 SPINDL, T번호 ↔ `G43 … H` 일치성 확인(불일치는 붉은색)."""
import tempfile
from pathlib import Path

import pytest

import NC_Tool_List as app

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / 'test files'


def _block(tool, spindl, body, n=1):
    spindl_line = ' (SPINDL %s FEED  1000.000000)\n' % spindl if spindl is not None else ''
    return (
        'N%d(#%d: Tool Change)\n' % (n, n)
        + ' (T%d // D10 F.EM [SO 40] // T%d BT40-SK16-120 )\n' % (tool, tool)
        + ' (LCF   38.500000 FL   26.000000 GL  160.000000 F 3)\n'
        + spindl_line
        + 'M6 T%d\n' % tool
        + body
    )


def _rows(text):
    return {r['NO']: r for r in app.parse_program(text) if r['NO']}


# ---------- S값 ----------
def test_matching_s_and_h_no_alert():
    rows = _rows(_block(1, '10000.000000', 'G0 G90 G54\nS10000 M3\nG43 Z50. H01\n'))
    assert rows['T01']['SPINDL'] == '10000'
    assert rows['T01']['SPINDL_ALERT'] == '' and rows['T01']['NO_ALERT'] == ''


def test_s_mismatch_reports_program_value_and_lines():
    text = _block(11, '1500.000000', 'S300 M3\nG43 Z320. H11\nS300 M3\n')
    alert = _rows(text)['T11']['SPINDL_ALERT']
    assert alert == '프로그램 S300 (6, 8행) / SPINDL 1500'


def test_s_without_m3_and_s_in_comment_are_ignored():
    body = 'S500\n(S300 M3 NOTE)\nG0 X0 S300\nS10000 M03\n'
    assert _rows(_block(1, '10000.000000', body))['T01']['SPINDL_ALERT'] == ''


def test_m4_and_same_line_variants_are_checked():
    assert _rows(_block(1, '800', 'M4 S900\n'))['T01']['SPINDL_ALERT'].startswith('프로그램 S900')
    assert _rows(_block(1, '800', 'G97S900M3\n'))['T01']['SPINDL_ALERT'].startswith('프로그램 S900')
    assert _rows(_block(1, '800', 'S800 M30\n'))['T01']['SPINDL_ALERT'] == ''  # M30은 M3가 아님


def test_rounding_difference_below_1rpm_is_same():
    assert _rows(_block(1, '3819.700000', 'S3820 M3\n'))['T01']['SPINDL_ALERT'] == ''
    assert _rows(_block(1, '3818.900000', 'S3820 M3\n'))['T01']['SPINDL_ALERT'] != ''


def test_tool_without_spindl_comment_is_not_compared():
    assert _rows(_block(1, None, 'S300 M3\n'))['T01']['SPINDL_ALERT'] == ''


def test_each_block_compared_with_its_own_spindl_comment():
    """D-1 (a): 같은 공구를 다른 회전수로 다시 쓰면 그 블록의 SPINDL 주석과 비교한다."""
    text = (_block(2, '10000.000000', 'S10000 M3\n', n=1)
            + _block(2, '1500.000000', 'S1500 M3\n', n=2))
    assert _rows(text)['T02']['SPINDL_ALERT'] == ''
    bad = (_block(2, '10000.000000', 'S10000 M3\n', n=1)
           + _block(2, '1500.000000', 'S10000 M3\n', n=2))
    alert = _rows(bad)['T02']['SPINDL_ALERT']
    assert '프로그램 S10000' in alert and 'SPINDL 1500' in alert and '(툴리스트 SPINDL 10000)' in alert


def test_s_before_first_tool_change_is_ignored():
    text = 'O0001\nS5000 M3\nG43 H09\n' + _block(1, '10000', 'S10000 M3\nG43 H01\n')
    row = _rows(text)['T01']
    assert row['SPINDL_ALERT'] == '' and row['NO_ALERT'] == ''


# ---------- T ↔ H ----------
def test_h_mismatch_flags_no_column():
    text = _block(3, '3800', 'S3800 M3\nG43 Z62. H04\nG43 Z30. H03\n')
    assert _rows(text)['T03']['NO_ALERT'] == 'T03 블록에서 H04 사용 (7행)'


def test_g43_variants_and_other_h_words():
    body = 'G28 G91 Z0. H0.\nG43.4 Z50. H05\nG49 H0\nG430 H9\n'
    assert _rows(_block(5, None, body))['T05']['NO_ALERT'] == ''
    assert _rows(_block(5, None, 'G43.5 H06\n'))['T05']['NO_ALERT'] != ''


def test_missing_g43_is_not_flagged():
    assert _rows(_block(1, '1000', 'S1000 M3\nG0 Z50.\n'))['T01']['NO_ALERT'] == ''


def test_lathe_is_not_checked():
    text = 'N1\nG50 S2500 T0100 M08\n (T01 // CNMG120408 // MCLNR2525M12)\nG96S96M3\nG28 H0.\n'
    rows = app.parse_program(text, lathe=True)
    assert all(not r.get('SPINDL_ALERT') and not r.get('NO_ALERT') for r in rows)


# ---------- 실제 샘플 ----------
@pytest.mark.parametrize('name,expected', [
    ('K10M41017_3axis_PGM_O1017.NC', {'T11': '프로그램 S300 (22, 28행) / SPINDL 1500'}),
    ('5ax-A To C.nc', {'T04': '프로그램 S10000 (27863행) / SPINDL 3800'}),
    ('O3210.NC', {'T02': '프로그램 S5000 (31행) / SPINDL 4500',
                  'T03': '프로그램 S10000 (4950행) / SPINDL 4500'}),
    ('new.NC', {}),
])
def test_real_samples(name, expected):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip('sample missing')
    rows = app.parse_program(path.read_text(encoding='utf-8', errors='replace'))
    got = {r['NO']: r['SPINDL_ALERT'] for r in rows if r.get('SPINDL_ALERT')}
    assert got == expected
    assert all(not r.get('NO_ALERT') for r in rows)


# ---------- PDF ----------
def test_pdf_marks_spindl_and_no_cells():
    rows = [
        {'NO': 'T01', 'SPINDL': '1500', '_SPINDL_ALERT': 'x'},
        {'NO': 'T02', 'SPINDL': '800', '_NO_ALERT': 'y'},
        {'NO': 'T03', 'SPINDL': '900'},
    ]
    table = app.make_pdf_table(rows, app.normalized_pdf_metadata({}), 700, app.register_pdf_fonts())
    keys = [k for k, _ in app.COLUMNS]
    sp, no = keys.index('SPINDL'), keys.index('NO')
    assert table._cellStyles[2][sp].color == app.PDF_ALERT_RED
    assert table._cellStyles[2][no].color == app.PDF_FONT_BLUE
    assert table._cellStyles[3][no].color == app.PDF_ALERT_RED
    assert table._cellStyles[4][sp].color == app.PDF_FONT_BLUE


# ---------- 화면 ----------
@pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt not available')
def test_table_shows_red_cells_count_and_recheck_after_edit():
    qapp = app.QApplication.instance() or app.QApplication([])
    settings = tempfile.TemporaryDirectory()
    window = app.App(_root=settings.name)
    try:
        if window.is_lathe_program():
            index = next(i for i in range(window.machine_type_combo.count())
                         if not app.is_lathe_machine(window.machine_type_combo.itemText(i)))
            window.machine_type_combo.setCurrentIndex(index)
        text = (_block(1, '1500', 'S300 M3\nG43 Z50. H01\n', n=1)
                + _block(2, '8000', 'S8000 M3\nG43 Z50. H05\n', n=2))
        window.src.setPlainText(text)
        window.run()
        keys = [k for k, _ in window.active_columns()]
        sp, no = keys.index('SPINDL'), keys.index('NO')
        error = app.QColor(window.theme['error'])
        assert window.table.item(0, sp).foreground().color() == error
        assert 'S300' in window.table.item(0, sp).toolTip()
        assert window.table.item(0, no).data(app.Qt.UserRole) == ''
        assert window.table.item(1, no).foreground().color() == error
        assert window.table.item(1, sp).data(app.Qt.UserRole) == ''
        assert 'S값 불일치 1 · H번호 불일치 1' in window.count.text()

        rows = window.current_rows()
        assert rows[0].get('_SPINDL_ALERT') and rows[1].get('_NO_ALERT')

        # [수정]으로 SPINDL을 프로그램 값(300)으로 고치면 붉은색이 없어진다
        edited = {key: window.table_text(0, key) for key in keys}
        edited['SPINDL'] = '300'
        window.set_table_row(0, edited)
        assert window.table.item(0, sp).data(app.Qt.UserRole) == ''
        assert 'S값 불일치 0 · H번호 불일치 1' in window.count.text()
        edited['SPINDL'] = '1500'
        window.set_table_row(0, edited)
        assert window.table.item(0, sp).data(app.Qt.UserRole) != ''
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
        settings.cleanup()
