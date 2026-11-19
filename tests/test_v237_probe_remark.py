# -*- coding: utf-8 -*-
"""v2.3.7: REMARK의 M300/M200 표기와 H번호 일치 검사."""
import pytest

NC = pytest.importorskip('NC_Tool_List')

TEXT = """N1 (#1: Tool Change)
M6 T3
G43 H3 Z100
M300H3
N2 (#2: Tool Change)
M6 T2
M300H5
M200
G41 D1
"""


def test_probe_suffix_match_mismatch_and_no_h():
    result = NC._radius_comp_by_n(TEXT.splitlines(), NC.N_RE)
    assert result['N1'] == '(M300H3)'
    assert result['N2'] == '(G41)(M300H5≠H2)(M200)'
    assert NC.RADIUS_COMP_MISMATCH_RE.search(result['N2'])
    assert not NC.RADIUS_COMP_MISMATCH_RE.search(result['N1'])


def test_v259_remark_probe_one_line():
    """v2.5.9: REMARK은 한 줄 — 모두 쓰면 "M300 N1, N2", 안 쓰는 N이 섞이면 "N1, M300H1:N2, N3"."""
    comp = {'N3': '(G41)(M300H3)(M200)', 'N7': '(M300H3)', 'N5': '(M300H6≠H5)', 'N9': '',
            'N1': '', 'N2': '(M300H1)', 'N4': '(M300)'}
    fmt = NC._format_remark
    assert fmt(['N2', 'N4'], {'N2': '(M300)', 'N4': '(M300)'}) == 'M300 N2, N4'
    assert fmt(['N1', 'N2', 'N4'], {'N2': '(M300)', 'N4': '(M300)'}) == 'N1, M300:N2, N4'
    assert fmt(['N1', 'N2'], comp) == 'N1, M300H1:N2'
    assert fmt(['N3', 'N7'], comp) == 'M300H3:N3(G41), N7 · M200:N3(G41)'
    assert fmt(['N5'], comp) == 'M300H6≠H5 N5'
    assert fmt(['N9'], comp) == 'N9'
    assert fmt(['N1', 'N3'], {'N1': '', 'N3': '(M300H1)(M200)'}) == 'N1, M300H1·M200:N3'
    assert fmt(['N1', 'N2', 'N3'], {'N2': '(M300)', 'N3': '(M200)'}) == 'N1, M300:N2 · M200:N3'
    mismatch = [m.group(0) for m in NC.RADIUS_COMP_DISPLAY_RE.finditer('N4, M300H6≠H5:N5')]
    assert mismatch == ['M300H6≠H5']
    assert NC.RADIUS_COMP_MISMATCH_RE.fullmatch(mismatch[0])


def test_v259_pdf_remark_fit():
    """v2.5.9: 긴 한 줄은 글자를 줄이고, 그래도 넘치면 "코드:N3 외2"로 줄인다."""
    same, size = NC._fit_remark_line('N1, M300H3:N3', 200, 'Helvetica-Bold', 5.0)
    assert (same, size) == ('N1, M300H3:N3', 5.0)
    line = 'N1, M300H3:N3, N7, N12'
    fitted, size = NC._fit_remark_line(line, 55, 'Helvetica-Bold', 5.0)
    assert fitted == line and 4.2 <= size < 5.0
    long = 'N1, M300H3:N3, N7, N12 · M200:N3, N7, N12, N15, N21, N30'
    short, _ = NC._fit_remark_line(long, 60, 'Helvetica-Bold', 5.0)
    assert short == 'N1, M300H3:N3 외2 · M200:N3 외5'
