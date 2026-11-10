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
