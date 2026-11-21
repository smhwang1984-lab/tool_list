"""v2.6.9: 공구명 D ↔ 주석 DC 불일치 점검, TAP 타입."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NC_Tool_List as app  # noqa: E402


def _tool(n, name, dc):
    return (
        "N%d(#%d: Tool Change)\n (T%d // %s // T%d BT40-SK10-90 )\n (LCF 20.0 FL 10.0 GL 100.0 F 2)\n"
        " (DC %s RE 0.0 SIG PL )\n (SPINDL 10000.0 FEED 3000.0)\nM6 T%d\n" % (n, n, n, name, n, dc, n)
    )


def _rows(*tools):
    text = "O0001\n" + "".join(_tool(i + 1, name, dc) for i, (name, dc) in enumerate(tools)) + "M30\n"
    _meta, rows = app.parse_program_with_metadata(text) if hasattr(app, 'parse_program_with_metadata') else (None, app.parse_program(text))
    return {r['NO']: r for r in rows if r['NO']}


def test_d_mismatch_alert_and_number_compare():
    rows = _rows(("D10 F.EM [SO 40]", "10.000000"), ("D6 B.EM [SO 30]", "8.000000"), ("D2.3 DRILL [SO 20]", "2.300000"))
    assert rows['T01']['D_ALERT'] == ''
    assert rows['T02']['D_ALERT'] == '공구명 D6 / 주석 DC 8'
    assert rows['T03']['D_ALERT'] == ''          # 2.3 = 2.300000 (숫자로 비교)


def test_no_alert_without_name_d_or_dc():
    rows = _rows(("M10 TAP [SO 35]", "10.000000"), ("D8 DRILL [SO 20]", ""))
    assert rows['T01']['D_ALERT'] == ''          # 공구명에 D가 없다
    assert rows['T02']['D_ALERT'] == ''          # 주석에 DC가 없다(공구명 D가 표 D)


def test_tap_type_is_mapped():
    assert app.derive_type('M10 TAP [SO 35]') == 'TAP'
