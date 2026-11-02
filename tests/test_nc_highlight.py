"""v2.2.7 — NC 코드 모달 색 표시(nc_color_line)와 테마 대비."""
import time

import pytest

import NC_Tool_List as app


def _paint(lines, lathe=False):
    """줄 목록 -> 줄마다 [(글자, 색 키)]"""
    state, out = 0, []
    for line in lines:
        spans, state = app.nc_color_line(line, state, lathe)
        out.append([(line[s:e], k) for s, e, k in spans])
    return out


def _color_of(painted, row, needle):
    return [k for text, k in painted[row] if needle in text]


def test_modal_color_carries_to_next_lines():
    p = _paint(['G00 X0. Y0.', 'Z5.', 'G01 Z-2. F300', 'X50.', 'G02 X60 R10', 'G03 X0 R10'])
    assert _color_of(p, 0, 'G00') == ['nc_g0'] and _color_of(p, 1, 'Z5.') == ['nc_g0']
    assert _color_of(p, 2, 'G01') == ['nc_g1'] and _color_of(p, 3, 'X50.') == ['nc_g1']
    assert _color_of(p, 4, 'G02') == ['nc_g2'] and _color_of(p, 5, 'G03') == ['nc_g3']


@pytest.mark.parametrize('code,key', [
    ('G0', 'nc_g0'), ('G00', 'nc_g0'), ('G1', 'nc_g1'), ('G01', 'nc_g1'),
    ('G2', 'nc_g2'), ('G02', 'nc_g2'), ('G3', 'nc_g3'), ('G03', 'nc_g3'),
    ('G81', 'nc_cycle'), ('G83', 'nc_cycle'), ('G73', 'nc_cycle'),
])
def test_code_variants(code, key):
    assert _color_of(_paint([code + ' X1']), 0, code) == [key]


@pytest.mark.parametrize('code', ['G10', 'G20', 'G28', 'G30', 'G17', 'G54', 'G90', 'G91', 'G94', 'G43'])
def test_similar_codes_do_not_change_color(code):
    assert _paint([code + ' X1']) == [[]]


def test_comments_are_uncolored_and_do_not_change_state():
    p = _paint(['G01 X1 (G02 M8 S100) X2', 'X3 ; G00', 'X4'])
    assert all(k == 'nc_g1' for _t, k in p[0])
    assert not any('G02' in t or 'M8' in t for t, _k in p[0])
    assert _color_of(p, 2, 'X4') == ['nc_g1']


def test_multiline_paren_comment():
    p = _paint(['G01 X1', '(note starts', 'G00 inside', 'ends) X2'])
    assert p[1] == [] and p[2] == []
    assert _color_of(p, 3, 'X2') == ['nc_g1']


def test_reset_codes():
    p = _paint(['G81 Z-5 R2', 'X1', 'G80', 'X2', 'G01 X3', 'M30', 'X4'])
    assert _color_of(p, 1, 'X1') == ['nc_cycle'] and p[3] == []
    assert p[5] == [] and p[6] == []
    assert _paint(['G02 X1', '%', 'X2'])[2] == []


def test_spindle_and_coolant_color_only_the_token():
    p = _paint(['G00 X0 S3000 M3 M8 Z5.', 'M5 M9'])
    assert _color_of(p, 0, 'S3000') == ['nc_spindle'] and _color_of(p, 0, 'M3') == ['nc_spindle']
    assert _color_of(p, 0, 'M8') == ['nc_coolant']
    assert _color_of(p, 0, 'Z5.') == ['nc_g0']  # G-1: 모달 색은 그대로
    assert _color_of(p, 1, 'M5') == ['nc_spindle'] and _color_of(p, 1, 'M9') == ['nc_coolant']
    assert _color_of(_paint(['M19']), 0, 'M19') == ['nc_spindle']
    assert _paint(['M6 T1', 'M30']) [0] == []


def test_lathe_cycles_differ_from_mill():
    assert _color_of(_paint(['G71 U1'], lathe=True), 0, 'G71') == ['nc_cycle']
    assert _paint(['G71 U1'], lathe=False) == [[]]
    assert _color_of(_paint(['G90 X1'], lathe=True), 0, 'G90') == ['nc_cycle']
    assert _paint(['G90 X1'], lathe=False) == [[]]


def test_lowercase_and_spaces():
    assert _color_of(_paint(['g01 x1 s500 m03']), 0, 'g01') == ['nc_g1']
    assert _color_of(_paint(['g01 x1 s500 m03']), 0, 's500') == ['nc_spindle']


# ---------- 테마 대비 ----------
def _lum(hex_color):
    h = hex_color.lstrip('#')
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    chans = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('key', ['nc_g0', 'nc_g1', 'nc_g2', 'nc_g3', 'nc_cycle', 'nc_spindle', 'nc_coolant'])
def test_contrast_on_editor_and_current_line(theme, key):
    t = app.THEMES[theme]
    assert _contrast(t[key], t['editor_bg']) >= 4.5
    assert _contrast(t[key], t['current_line']) >= 4.5


@pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt 없음')
def test_highlighter_applies_formats_and_recolors_following_lines():
    qapp = app.QApplication.instance() or app.QApplication([])
    edit = app.QPlainTextEdit()
    hl = app.NcSyntaxHighlighter(edit.document(), app.THEMES['dark'])
    edit.setPlainText('G01 X1\nX2\nG00 X3\n')

    def color(block, col):
        for r in edit.document().findBlockByNumber(block).layout().formats():
            if r.start <= col < r.start + r.length:
                return r.format.foreground().color().name()
        return None
    edit.document().findBlockByNumber(1).layout()
    hl.rehighlight()
    assert color(1, 0) == app.THEMES['dark']['nc_g1']
    cursor = edit.textCursor()
    cursor.setPosition(0)
    cursor.movePosition(cursor.Right, cursor.KeepAnchor, 3)
    cursor.insertText('G02')
    assert color(1, 0) == app.THEMES['dark']['nc_g2']
    hl.set_theme(app.THEMES['light'])
    assert color(1, 0) == app.THEMES['light']['nc_g2']


@pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt 없음')
def test_large_file_highlight_time():
    qapp = app.QApplication.instance() or app.QApplication([])
    edit = app.QPlainTextEdit()
    app.NcSyntaxHighlighter(edit.document(), app.THEMES['dark'])
    text = ''.join('G01 X%d.123 Y%d.456 Z-1.0 F300 (comment)\nG00 Z5.\nS3000 M3\n' % (i, i) for i in range(20000))
    start = time.perf_counter()
    edit.setPlainText(text)
    elapsed = time.perf_counter() - start
    print('60000 lines highlight: %.2fs' % elapsed)
    assert elapsed < 5
