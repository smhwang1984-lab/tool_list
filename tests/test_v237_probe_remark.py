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


def test_v255_remark_probe_goes_to_second_line():
    """v2.5.5: REMARK은 1줄 N번호(+G41/G42), 2줄 M300/M200(중복 합침).
    v2.5.8: 2줄에 측정한 N번호를 붙인다("M300H3: N3, N7")."""
    comp = {'N3': '(G41)(M300H3)(M200)', 'N7': '(M300H3)', 'N5': '(M300H6≠H5)', 'N9': ''}
    assert NC._format_remark(['N3', 'N7'], comp) == 'N3(G41), N7\nM300H3: N3, N7 · M200: N3'
    assert NC._format_remark(['N5'], comp) == 'N5\nM300H6≠H5: N5'
    assert NC._format_remark(['N9'], comp) == 'N9'
    mismatch = [m.group(0) for m in NC.RADIUS_COMP_DISPLAY_RE.finditer('N5\nM300H6≠H5')]
    assert mismatch == ['M300H6≠H5']
    assert NC.RADIUS_COMP_MISMATCH_RE.fullmatch(mismatch[0])


def test_v258_pdf_remark_fit_keeps_two_lines():
    """v2.5.8: 길어진 2줄째가 PDF 셀 폭을 넘어 줄바꿈(겹침)되지 않게 글자를 줄이거나 줄인다."""
    line = 'M300H3: N3, N7, N12'
    same, size = NC._fit_remark_line('M300H3: N3', 200, 'Helvetica-Bold', 5.0)
    assert (same, size) == ('M300H3: N3', 5.0)
    fitted, size = NC._fit_remark_line(line, 42, 'Helvetica-Bold', 5.0)
    assert fitted == line and 4.2 <= size < 5.0
    long = 'M300H3: N3, N7, N12 · M200: N3, N7, N12, N15, N21, N30'
    short, _ = NC._fit_remark_line(long, 60, 'Helvetica-Bold', 5.0)
    assert short == 'M300H3: N3 외2 · M200: N3 외5'
