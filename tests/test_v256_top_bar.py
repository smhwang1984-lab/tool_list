# -*- coding: utf-8 -*-
"""v2.5.6: 한 줄 상단바 + 숨김(Ctrl+H, 손잡이, 임시 표시, 기억) 검사."""
import tempfile

import pytest

app = pytest.importorskip('NC_Tool_List')
pytestmark = pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt is not available')


@pytest.fixture()
def window():
    qapp = app.QApplication.instance() or app.QApplication([])
    settings_dir = tempfile.TemporaryDirectory()
    win = app.App(_root=settings_dir.name)
    win.show()
    qapp.processEvents()
    yield win, settings_dir.name, qapp
    win.close()
    win.deleteLater()
    settings_dir.cleanup()
    qapp.processEvents()


def test_single_row_bar_has_fixed_height_and_hide_button_last(window):
    win, _root, _qapp = window
    assert win.top_bar.height() == app.TOP_BAR_HEIGHT_PX
    layout = win.top_bar.layout()
    last = layout.itemAt(layout.count() - 1).widget()
    assert last is win.btn_hide_top_bar
    assert not win.top_bar_hidden


def test_hide_and_show_toggle_removes_bar_height(window):
    win, _root, qapp = window
    before = win.main_splitter.height()
    win.set_top_bar_hidden(True)
    qapp.processEvents()
    assert win.top_bar_hidden
    assert not win.top_bar.isVisible()
    assert win.top_bar_edge.isVisible()
    # 숨기면 위쪽 손잡이(8px)만 남으므로 본문이 40px 커진다
    assert win.main_splitter.height() - before == app.TOP_BAR_HEIGHT_PX - app.TOP_BAR_EDGE_PX
    win.toggle_top_bar_hidden()
    qapp.processEvents()
    assert not win.top_bar_hidden
    assert win.top_bar.isVisible()
    assert not win.top_bar_edge.isVisible()
    assert win.main_splitter.height() == before


def test_peek_overlays_without_moving_content_and_closes(window):
    win, _root, qapp = window
    win.set_top_bar_hidden(True)
    qapp.processEvents()
    top = win.main_splitter.geometry().top()
    win._peek_top_bar(True)
    qapp.processEvents()
    assert win.top_bar.isVisible()
    assert win.top_bar.geometry().top() == 0
    assert win.main_splitter.geometry().top() == top  # 본문은 밀리지 않는다
    # 마우스가 상단바 밖이면 닫힌다
    win._top_bar_peek_timer.stop()
    from PyQt5.QtGui import QCursor
    QCursor.setPos(win.mapToGlobal(win.rect().center()))
    win._end_top_bar_peek()
    assert not win.top_bar.isVisible()
    assert win.top_bar_hidden


def test_hidden_state_is_saved_and_restored(window):
    win, root, qapp = window
    win.set_top_bar_hidden(True)
    win.save_layout_settings()
    other = app.App(_root=root)
    try:
        assert other.top_bar_hidden
        assert not other.top_bar.isVisibleTo(other)
    finally:
        other.deleteLater()
        qapp.processEvents()


def test_ctrl_h_shortcut_is_installed(window):
    win, _root, _qapp = window
    keys = [shortcut.key().toString() for shortcut in win._shortcuts]
    assert 'Ctrl+H' in keys


def test_hide_button_stays_inside_window_at_minimum_width(window):
    """가장 좁은 창에서도 숨김 화살표가 화면 안(상단바 오른쪽 끝)에 있어야 한다."""
    win, _root, qapp = window
    win.showNormal()
    min_width = win.minimumSizeHint().width()
    win.resize(min_width, 700)
    qapp.processEvents()
    button = win.btn_hide_top_bar
    right = button.mapTo(win, button.rect().topRight()).x()
    assert 0 <= button.mapTo(win, button.rect().topLeft()).x()
    assert right <= win.width()
    assert button.isVisible()


def test_narrow_bar_folds_labels_but_keeps_run_label(window):
    win, _root, qapp = window
    win.showNormal()
    win.resize(win.minimumSizeHint().width(), 700)
    qapp.processEvents()
    from PyQt5.QtCore import Qt
    assert win.run_button.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    if win._top_bar_compact:
        assert win.btn_open_file.toolButtonStyle() == Qt.ToolButtonIconOnly


def test_hide_button_stays_visible_after_viewer_mode_and_edit_mode(window):
    """Viewer 모드(버튼 4개 추가)·편집 모드(저장/비밀번호 추가)로 바꿔도 숨김 화살표는 창 안에 있다."""
    win, _root, qapp = window
    win.showNormal()
    win.set_mode('viewer')
    win.btn_edit_save.setVisible(True)
    win.btn_edit_password.setVisible(True)
    win._update_top_bar_density()
    win.resize(win.minimumSizeHint().width(), 700)
    qapp.processEvents()
    button = win.btn_hide_top_bar
    assert button.isVisible()
    assert button.mapTo(win, button.rect().topRight()).x() <= win.width()


def test_peek_overlay_screenshot_renders_bar(window, tmp_path):
    win, _root, qapp = window
    win.set_top_bar_hidden(True)
    win._peek_top_bar(True)
    qapp.processEvents()
    image = win.top_bar.grab().toImage()
    assert image.width() == win.centralWidget().width()
    assert image.height() == app.TOP_BAR_HEIGHT_PX
