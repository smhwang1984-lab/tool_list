"""v2.2.8 — UI 개편: 아이콘 툴바, ⚙ 설정 창, 툴패스 선 굵기."""
import pytest

import NC_Tool_List as app

pytestmark = pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt 없음')

PROGRAM = (
    'N1(#1: Tool Change)\n'
    ' (T1 // D50 F.MIL [SO 90] // T1 BT40-FMC22-90)\n'
    'M6T1\nG43\nG00 X0 Y0 Z50\nG01 X10 F300\nG01 Y10\nG00 Z100\nM30\n'
)


@pytest.fixture
def qapp():
    return app.QApplication.instance() or app.QApplication([])


@pytest.fixture
def fake_viewer_settings(monkeypatch):
    """뷰어는 레지스트리(QSettings)에 직접 저장한다 — 테스트가 이 PC 값을 건드리지 않게 막는다."""
    viewer_module = pytest.importorskip('nc_viewer_widget')

    class FakeSettings:
        store = {}

        def __init__(self, *_args):
            pass

        def value(self, key, default=None):
            return self.store.get(key, default)

        def setValue(self, key, value):
            self.store[key] = value

        def sync(self):
            pass

    FakeSettings.store = {}
    monkeypatch.setattr(viewer_module, 'QSettings', FakeSettings)
    return FakeSettings.store


@pytest.fixture
def window(qapp, tmp_path, monkeypatch, fake_viewer_settings):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    win = app.App(_root=str(tmp_path))
    yield win
    win.deleteLater()
    qapp.processEvents()


# ---------- 아이콘 ----------
def test_every_icon_draws_something(qapp):
    import ui_icons
    for name in ui_icons.ICON_PAINTERS:
        image = ui_icons.icon_pixmap(name, '#336699', 24).toImage()
        painted = sum(
            1 for x in range(24) for y in range(24) if (image.pixel(x, y) >> 24) & 0xFF
        )
        assert painted > 10, name


def test_icon_uses_requested_color(qapp):
    import ui_icons
    image = ui_icons.icon_pixmap('check_none', '#ff0000', 32).toImage()
    colors = {image.pixelColor(x, y).name() for x in range(32) for y in range(32)
              if image.pixelColor(x, y).alpha() == 255}
    assert '#ff0000' in colors


# ---------- 선 굵기 계산 ----------
def test_line_width_90_percent_is_previous_width():
    viewer_module = pytest.importorskip('nc_viewer_widget')
    for base in (1.5, 2.5, 3.5):
        assert viewer_module.toolpath_line_width(base, 90) == pytest.approx(base)


def test_line_width_10_percent_is_one_pixel_and_100_is_ten_percent_thicker():
    viewer_module = pytest.importorskip('nc_viewer_widget')
    assert viewer_module.toolpath_line_width(2.5, 10) == pytest.approx(1.0)
    assert viewer_module.toolpath_line_width(1.5, 10) == pytest.approx(1.0)
    assert viewer_module.toolpath_line_width(2.5, 100) == pytest.approx(2.75)


def test_line_width_steps_are_all_different():
    viewer_module = pytest.importorskip('nc_viewer_widget')
    widths = [viewer_module.toolpath_line_width(2.5, pct)
              for pct in viewer_module.TOOLPATH_LINE_WIDTH_STEPS]
    assert widths == sorted(widths)
    assert len(set(round(w, 4) for w in widths)) == 10


@pytest.mark.parametrize('raw, expected', [
    (None, 90), ('abc', 90), (0, 10), (5, 10), (44, 40), (150, 100), ('70', 70),
])
def test_clamp_line_width_pct(raw, expected):
    viewer_module = pytest.importorskip('nc_viewer_widget')
    assert viewer_module.clamp_line_width_pct(raw) == expected


# ---------- 뷰어 반영 ----------
def test_viewer_applies_and_saves_line_width(window, fake_viewer_settings):
    viewer = window.viewer
    if not hasattr(viewer, 'set_toolpath_line_width_pct'):
        pytest.skip('3D 뷰어 없음')
    assert viewer.toolpath_line_width_pct == 90
    window.src.setPlainText(PROGRAM)
    window.set_mode('viewer')
    items = [item for items in viewer.plot_items.values() for item in items]
    assert items
    assert {round(item.width, 3) for item in items} <= {1.5, 2.5}

    viewer.set_toolpath_line_width_pct(10)
    assert {round(item.width, 3) for item in items} == {1.0}
    assert fake_viewer_settings['toolpath_line_width_pct'] == 10

    viewer.set_toolpath_line_width_pct(100)
    assert {round(item.width, 3) for item in items} <= {1.65, 2.75}


def test_saved_line_width_is_restored_and_used_for_new_paths(window, fake_viewer_settings):
    viewer_module = pytest.importorskip('nc_viewer_widget')
    fake_viewer_settings['toolpath_line_width_pct'] = 50
    viewer = viewer_module.NCViewerWidget()
    try:
        assert viewer.toolpath_line_width_pct == 50
        viewer.set_source_text(PROGRAM)
        widths = {round(item.width, 3) for items in viewer.plot_items.values() for item in items}
        expected = {round(viewer_module.toolpath_line_width(b, 50), 3) for b in (1.5, 2.5)}
        assert widths and widths <= expected
        # 재생 궤적(PG 매칭)도 같은 비율을 따른다(기준 3.5 / 급속 1.5).
        assert viewer.update_trace_item(0, [(0, 0, 0), (1, 0, 0)], 'G01', (1.0, 0.0, 0.0))
        assert viewer.dynamic_trace_items[0].width == pytest.approx(viewer_module.toolpath_line_width(3.5, 50))
        viewer.set_toolpath_line_width_pct(90)
        assert viewer.dynamic_trace_items[0].width == pytest.approx(3.5)
    finally:
        viewer.deleteLater()


# ---------- 설정 창 ----------
def test_settings_dialog_drives_viewer(window):
    if not hasattr(window.viewer, 'set_toolpath_line_width_pct'):
        pytest.skip('3D 뷰어 없음')
    dialog = window.show_settings()
    assert dialog.isVisible() and not dialog.isModal()
    combo = dialog.line_width_combo
    assert [combo.itemData(i) for i in range(combo.count())] == list(range(10, 101, 10))
    assert combo.currentData() == 90
    assert not combo.itemIcon(0).isNull()

    combo.setCurrentIndex(combo.findData(30))
    assert window.viewer.toolpath_line_width_pct == 30

    dialog.sensitivity_slider.setValue(120)
    assert window.viewer.sensitivity_slider.value() == 120
    dialog.cube_slider.setValue(200)
    assert window.viewer.view_cube_size_slider.value() == 200

    # Alt+휠처럼 바깥에서 바뀐 값도 열린 창에 따라온다.
    window.viewer.sensitivity_slider.setValue(70)
    assert dialog.sensitivity_slider.value() == 70

    dialog.reset_defaults()
    assert window.viewer.toolpath_line_width_pct == 90
    assert window.viewer.sensitivity_slider.value() == 40
    assert window.viewer.view_cube_size_slider.value() == 160
    assert window.show_settings() is dialog
    dialog.close()


def test_view_controls_row_moved_off_the_3d_view(window):
    viewer = window.viewer
    if not hasattr(viewer, 'view_controls'):
        pytest.skip('3D 뷰어 없음')
    window.show()
    assert viewer.view_controls.isHidden()
    assert viewer.layout().indexOf(viewer.gl_view) == 0


def test_settings_dialog_disabled_without_viewer(window):
    window.viewer = app.QWidget()
    dialog = app.SettingsDialog(window)
    assert not dialog.line_width_combo.isEnabled()
    assert not dialog.unavailable_label.isHidden()
    dialog.deleteLater()


# ---------- 툴바 ----------
def test_toolbar_buttons_call_existing_functions(window, monkeypatch):
    called = []
    for name in ('open_file', 'open_add_program_files', 'load_example', 'clear', 'run',
                 'show_settings', 'show_help', 'show_about'):
        monkeypatch.setattr(window, name, lambda *_a, _n=name: called.append(_n), raising=True)
    # 연결은 _build_ui 때 이미 끝났으므로, 같은 버튼에 다시 연결해 신호 경로만 확인한다.
    pairs = (
        (window.btn_open_file, 'open_file'), (window.btn_add_program, 'open_add_program_files'),
        (window.btn_example, 'load_example'), (window.btn_clear, 'clear'), (window.run_button, 'run'),
        (window.btn_settings, 'show_settings'), (window.btn_help, 'show_help'),
        (window.btn_about, 'show_about'),
    )
    for button, name in pairs:
        button.clicked.disconnect()
        button.clicked.connect(getattr(window, name))
        button.click()
    assert called == [name for _button, name in pairs]


def test_mode_buttons_switch_mode(window):
    window.btn_viewer_mode.click()
    assert window.current_mode == 'viewer' and window.btn_viewer_mode.isChecked()
    window.btn_tool_mode.click()
    assert window.current_mode == 'tool' and window.btn_tool_mode.isChecked()


def test_toolbar_buttons_have_icons_and_tooltips(window):
    for button in (window.btn_open_file, window.btn_add_program, window.btn_example, window.btn_clear,
                   window.btn_edit_mode, window.btn_edit_save, window.btn_edit_password,
                   window.run_button, window.btn_tool_mode, window.btn_viewer_mode,
                   window.btn_settings, window.btn_help, window.btn_about):
        assert not button.icon().isNull(), button.text()
        assert button.toolTip(), button.text()
    for button in (window.btn_prev_tool_search, window.btn_next_tool_search, window.btn_search,
                   window.reset_program_button, window.stock_button, window.pdf_button,
                   window.copy_button):
        assert not button.icon().isNull(), button.text()


def test_theme_change_redraws_icons(window, monkeypatch):
    import ui_icons
    colors = []
    original = ui_icons.icon

    def spy(name, color, size=20):
        colors.append(color)
        return original(name, color, size)

    monkeypatch.setattr(ui_icons, 'icon', spy)
    window.apply_theme('light')
    assert app.THEMES['light']['icon'] in colors
    colors.clear()
    window.apply_theme('dark')
    assert app.THEMES['dark']['icon'] in colors
    assert app.THEMES['light']['icon'] not in colors


def test_checked_mode_button_icon_uses_accent_text(window, monkeypatch):
    import ui_icons
    calls = []
    original = ui_icons.icon
    monkeypatch.setattr(ui_icons, 'icon', lambda n, c, s=20: (calls.append((n, c)), original(n, c, s))[1])
    window.set_mode('viewer')
    assert ('toolpath', window.theme['accent_text']) in calls
    assert ('table', window.theme['icon']) in calls


def test_filter_select_buttons_keep_text_and_icon(window):
    """사용자 요청: 공정 필터의 전체/해제는 아이콘과 글자가 함께 보여야 한다."""
    assert window.btn_select_all_tools.text() == '전체'
    assert window.btn_select_no_tools.text() == '해제'
    assert not window.btn_select_all_tools.icon().isNull()
    assert not window.btn_select_no_tools.icon().isNull()


def test_filter_row_fits_at_minimum_program_pane_width(window, qapp):
    """프로그램 패널을 최소 폭까지 줄여도 공정 필터 줄 버튼 글자가 잘리지 않는다."""
    window.set_mode('viewer')
    window.show()
    _let_startup_timers_fire(qapp)
    # 화면이 작은 환경(offscreen 등)에서도 두 패널 최소 폭이 다 들어가게 창을 넓힌다.
    window.showNormal()
    window.resize(2400, 900)
    qapp.processEvents()
    window.main_splitter.setSizes([100, 2000])  # 최소 폭까지 줄인다
    qapp.processEvents()
    assert window.main_splitter.sizes()[0] == window.program_panel.minimumWidth()
    for _ in range(5):
        qapp.processEvents()
    for button in (window.reset_program_button, window.btn_select_all_tools,
                   window.btn_select_no_tools, window.stock_button):
        assert button.width() >= button.sizeHint().width(), button.text()


def test_main_starts_maximized():
    import inspect
    source = inspect.getsource(app.main)
    assert 'window.showMaximized()' in source
    assert 'window.show()' not in source


def _let_startup_timers_fire(qapp):
    # App.__init__이 예약한 최대화(0ms, 재확인 300ms)가 먼저 끝나야 아래 상태를 우리가 정한다.
    import time
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)


def test_startup_recheck_maximizes_a_normal_window(window, qapp):
    window.show()
    _let_startup_timers_fire(qapp)
    window.showNormal()
    window.resize(900, 600)
    qapp.processEvents()
    assert not window.isMaximized()
    window._ensure_maximized_on_start()
    qapp.processEvents()
    assert window.isMaximized()


def test_startup_recheck_leaves_minimized_or_hidden_window(window, qapp):
    window.show()
    _let_startup_timers_fire(qapp)
    window.showNormal()
    qapp.processEvents()
    window.hide()
    window._ensure_maximized_on_start()
    assert not window.isVisible()
    window.showMinimized()
    qapp.processEvents()
    window._ensure_maximized_on_start()
    qapp.processEvents()
    assert not window.isMaximized()


def test_edit_buttons_hidden_until_edit_mode(window):
    assert window.btn_edit_save.isHidden() and window.btn_edit_password.isHidden()
    window._set_edit_mode(True)
    assert not window.btn_edit_save.isHidden() and not window.btn_edit_password.isHidden()
    window._set_edit_mode(False)
    assert window.btn_edit_save.isHidden()
