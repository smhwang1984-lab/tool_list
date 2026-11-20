# -*- coding: utf-8 -*-
"""v2.5.7: 모든 버튼 이름 표시 + 폭이 모자라면 자동 두 줄 + 상단바 숨김은 설정에서 켜는 선택 기능."""
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
    win.showNormal()  # 시작할 때 예약된 showMaximized가 지나간 뒤 일반 크기로 둔다
    qapp.processEvents()
    yield win, settings_dir.name, qapp
    win.close()
    win.deleteLater()
    settings_dir.cleanup()
    qapp.processEvents()


def _all_named_buttons(win):
    buttons = [win.btn_open_file, win.btn_add_program, win.btn_example, win.btn_clear, win.btn_machine,
               win.stock_button, win.stock_clear_button, win.btn_edit_mode,
               win.btn_edit_save, win.btn_edit_password, win.run_button, win.btn_tool_mode,
               win.btn_viewer_mode, win.btn_settings, win.btn_help, win.btn_about, win.btn_hide_top_bar]
    return buttons


def test_every_top_button_shows_its_name(window):
    from PyQt5.QtCore import Qt
    win, _root, _qapp = window
    for button in _all_named_buttons(win):
        assert button.toolButtonStyle() == Qt.ToolButtonTextBesideIcon, button.text()
        assert button.text()
    assert win.btn_dark_mode.text().strip() == '다크'


def test_hide_is_off_by_default_and_button_hidden(window):
    win, _root, qapp = window
    assert win.top_bar_hide_enabled is False
    assert not win.btn_hide_top_bar.isVisible()
    win.toggle_top_bar_hidden()  # Ctrl+H도 꺼져 있으면 아무 일도 없다
    qapp.processEvents()
    assert not win.top_bar_hidden
    assert win.top_bar.isVisible()


def test_enable_hide_in_settings_shows_button_and_persists(window):
    win, root, qapp = window
    dialog = win.show_settings()
    dialog.hide_top_bar_check.setChecked(True)
    qapp.processEvents()
    assert win.top_bar_hide_enabled
    assert win.btn_hide_top_bar.isVisible()
    win.set_top_bar_hidden(True)
    win.save_layout_settings()
    other = app.App(_root=root)
    try:
        assert other.top_bar_hide_enabled
        assert other.top_bar_hidden
    finally:
        other.deleteLater()
        qapp.processEvents()


def test_disabling_hide_restores_hidden_bar(window):
    win, _root, qapp = window
    win.set_top_bar_hide_enabled(True)
    win.set_top_bar_hidden(True)
    qapp.processEvents()
    assert win.top_bar_hidden
    win.set_top_bar_hide_enabled(False)
    qapp.processEvents()
    assert not win.top_bar_hidden
    assert win.top_bar.isVisible()
    assert not win.btn_hide_top_bar.isVisible()


def test_hide_and_peek_still_work_when_enabled(window):
    win, _root, qapp = window
    win.set_top_bar_hide_enabled(True)
    qapp.processEvents()
    before = win.main_splitter.height()
    win.set_top_bar_hidden(True)
    qapp.processEvents()
    assert not win.top_bar.isVisible()
    assert win.top_bar_edge.isVisible()
    top = win.main_splitter.geometry().top()
    win._peek_top_bar(True)
    qapp.processEvents()
    assert win.top_bar.isVisible()
    assert win.main_splitter.geometry().top() == top  # 본문은 밀리지 않는다
    win._top_bar_peek_timer.stop()
    image = win.top_bar.grab().toImage()
    assert image.height() == win._top_bar_height
    win.set_top_bar_hidden(False)
    qapp.processEvents()
    assert win.main_splitter.height() == before


def test_wide_window_is_one_row(window):
    win, _root, qapp = window
    win.showNormal()
    win.resize(2200, 800)
    qapp.processEvents()
    assert not win._top_bar_two_rows
    assert win.top_bar.height() == app.TOP_BAR_HEIGHT_PX
    assert not win.top_row2.isVisible()


def test_narrow_window_wraps_toolbar_to_second_row_without_losing_buttons(window):
    win, _root, qapp = window
    win.showNormal()
    win.set_mode('viewer')
    win.btn_edit_save.setVisible(True)
    win.btn_edit_password.setVisible(True)
    win.resize(1300, 700)
    qapp.processEvents()
    win._update_top_bar_density(force=True)
    qapp.processEvents()
    assert win.centralWidget().width() < win._top_layout.minimumSize().width() + win.main_toolbar.minimumSizeHint().width()
    assert win._top_bar_two_rows
    assert win.top_bar.height() == app.TOP_BAR_HEIGHT_PX + app.TOP_BAR_ROW2_PX
    assert win.main_toolbar.parentWidget() is win.top_row2
    # 이름이 접히지 않는다
    from PyQt5.QtCore import Qt
    assert win.btn_open_file.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    # 설정류는 첫 줄 오른쪽 끝, 창 안에 있다
    button = win.btn_about
    assert button.mapTo(win, button.rect().topRight()).x() <= win.width()
    # 버튼이 줄어들고 창이 넓어지면 한 줄로 돌아온다
    win.set_mode('tool')
    win.btn_edit_save.setVisible(False)
    win.btn_edit_password.setVisible(False)
    win.resize(2200, 700)
    qapp.processEvents()
    assert not win._top_bar_two_rows
    assert win.main_toolbar.parentWidget() is win.top_row1


def test_hide_button_inside_window_when_enabled_and_narrow(window):
    win, _root, qapp = window
    win.set_top_bar_hide_enabled(True)
    win.showNormal()
    win.resize(win.minimumSizeHint().width(), 700)
    qapp.processEvents()
    button = win.btn_hide_top_bar
    assert button.isVisible()
    assert button.mapTo(win, button.rect().topRight()).x() <= win.width()


def test_ctrl_h_shortcut_is_installed(window):
    win, _root, _qapp = window
    keys = [shortcut.key().toString() for shortcut in win._shortcuts]
    assert 'Ctrl+H' in keys
