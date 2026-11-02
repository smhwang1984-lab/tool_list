"""v2.2.7 — 편집 모드: 비밀번호(해시), 인코딩 보존 저장, 읽기 모드 시작, 즉시 반영."""
import pytest

import NC_Tool_List as app

pytestmark = pytest.mark.skipif(app.QT_IMPORT_ERROR is not None, reason='Qt 없음')

PROGRAM = (
    'N1(#1: Tool Change)\n'
    ' (T1 // D50 F.MIL [SO 90] // T1 BT40-FMC22-90)\n'
    ' (SO    90.000000 GL   115.000000 PL )\n'
    'M6 T1\nG0 X0 Y0\nG1 X10 F300\nM30\n'
)


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    return tmp_path


# ---------- 비밀번호 ----------
def test_default_password_is_1234(appdata):
    assert app.verify_edit_password('1234')
    assert not app.verify_edit_password('0000')
    assert not app.verify_edit_password('')


def test_changed_password_stored_as_hash(appdata):
    app.set_edit_password('abcd9')
    assert app.verify_edit_password('abcd9')
    assert not app.verify_edit_password('1234')
    stored = app.load_app_settings()['edit_password']
    assert 'abcd9' not in str(stored)
    assert stored['algo'] == 'pbkdf2_sha256' and len(stored['salt']) == 32 and len(stored['hash']) == 64


def test_same_password_gets_different_salt(appdata):
    app.set_edit_password('abcd9')
    first = app.load_app_settings()['edit_password']
    app.set_edit_password('abcd9')
    second = app.load_app_settings()['edit_password']
    assert first['salt'] != second['salt'] and first['hash'] != second['hash']


def test_removing_key_resets_to_default(appdata):
    app.set_edit_password('abcd9')
    settings = app.load_app_settings()
    del settings['edit_password']
    app.save_app_settings(settings)
    assert app.verify_edit_password('1234') and not app.verify_edit_password('abcd9')


def test_corrupt_entry_falls_back_to_default(appdata):
    app.save_app_settings({'edit_password': {'algo': 'pbkdf2_sha256', 'iter': 'x', 'salt': 'zz', 'hash': '1'}})
    assert app.verify_edit_password('1234')


# ---------- 인코딩/줄바꿈 보존 ----------
@pytest.mark.parametrize('encoding,newline', [
    ('utf-8', '\n'), ('utf-8', '\r\n'), ('utf-8-sig', '\r\n'), ('cp949', '\r\n'), ('cp949', '\n'),
])
def test_roundtrip_keeps_bytes(tmp_path, encoding, newline):
    original = '%\nO1234 (가공 프로그램)\nG0 X0\nM30\n'.replace('\n', newline).encode(encoding)
    path = tmp_path / 'a.nc'
    path.write_bytes(original)
    text, enc, nl, lossy = app.decode_program_bytes(path.read_bytes())
    assert (enc, nl, lossy) == (encoding, newline, False)
    assert '가공 프로그램' in text and '\r' not in text
    app.save_program_text(path, text, enc, nl)
    assert path.read_bytes() == original
    assert (tmp_path / 'a.nc.bak').read_bytes() == original


def test_invalid_bytes_are_flagged_lossy():
    text, enc, _nl, lossy = app.decode_program_bytes(b'G0 X0 \xff\xfe\x80\n')
    assert lossy and enc == 'utf-8'


def test_unencodable_text_writes_nothing(tmp_path):
    path = tmp_path / 'a.nc'
    path.write_bytes(b'G0\n')
    with pytest.raises(UnicodeEncodeError):
        app.save_program_text(path, 'G0 中❤', 'cp949', '\n')
    assert path.read_bytes() == b'G0\n'


# ---------- 창 동작 ----------
def _type(window, text):
    """사용자 입력처럼 전체를 바꿔 넣는다(setPlainText는 수정 표시를 지운다)."""
    window.src.selectAll()
    window.src.insertPlainText(text)


def _window(tmp_path):
    qapp = app.QApplication.instance() or app.QApplication([])
    window = app.App(_root=str(tmp_path / 'root'))
    qapp.processEvents()
    return qapp, window


def test_starts_read_only_even_after_opening_file(appdata):
    qapp, window = _window(appdata)
    try:
        assert not window.edit_mode and window.src.isReadOnly()
        path = appdata / 'p.nc'
        path.write_text(PROGRAM, encoding='utf-8')
        window.load_file(str(path))
        assert not window.edit_mode and window.src.isReadOnly()
        assert not window.btn_edit_save.isVisible() and not window.btn_edit_mode.isChecked()
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_edit_updates_tool_list_after_debounce_and_saves(appdata):
    qapp, window = _window(appdata)
    try:
        path = appdata / 'p.nc'
        path.write_bytes(PROGRAM.replace('\n', '\r\n').encode('cp949'))
        window.load_file(str(path))
        assert window.table.rowCount() == 1
        window._set_edit_mode(True)
        assert not window.src.isReadOnly()
        _type(window, PROGRAM.replace('D50 F.MIL', 'D12 F.MIL'))
        assert window.edit_refresh_timer.isActive()
        window._apply_edit_refresh()
        assert 'D12' in window.table_text(0, 'NAME')
        assert window.src.document().isModified()
        assert window.save_edit()
        saved = path.read_bytes()
        assert b'D12' in saved and b'\r\n' in saved
        assert (appdata / 'p.nc.bak').exists()
        assert not window.src.document().isModified()
        window._set_edit_mode(False)
        assert window.src.isReadOnly()
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_wrong_password_keeps_read_only(appdata, monkeypatch):
    qapp, window = _window(appdata)
    try:
        monkeypatch.setattr(app.QInputDialog, 'getText', staticmethod(lambda *a, **k: ('9999', True)))
        monkeypatch.setattr(app.QMessageBox, 'warning', staticmethod(lambda *a, **k: None))
        window.btn_edit_mode.setChecked(True)
        window.toggle_edit_mode(True)
        assert not window.edit_mode and window.src.isReadOnly() and not window.btn_edit_mode.isChecked()
        monkeypatch.setattr(app.QInputDialog, 'getText', staticmethod(lambda *a, **k: ('1234', True)))
        window.toggle_edit_mode(True)
        assert window.edit_mode and not window.src.isReadOnly()
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_discarding_restores_saved_text(appdata, monkeypatch):
    qapp, window = _window(appdata)
    try:
        path = appdata / 'p.nc'
        path.write_text(PROGRAM, encoding='utf-8')
        window.load_file(str(path))
        window._set_edit_mode(True)
        _type(window, 'G0 X0\n')
        monkeypatch.setattr(window, '_ask_save_changes', lambda: app.QMessageBox.Discard)
        window.btn_edit_mode.setChecked(False)
        window.toggle_edit_mode(False)
        assert not window.edit_mode and window.src.toPlainText() == PROGRAM
        assert path.read_text(encoding='utf-8') == PROGRAM
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_table_manual_edit_warns_before_entering(appdata, monkeypatch):
    qapp, window = _window(appdata)
    try:
        window.src.setPlainText(PROGRAM)
        window.run()
        window._table_manually_edited = True
        monkeypatch.setattr(app.QInputDialog, 'getText', staticmethod(lambda *a, **k: ('1234', True)))
        monkeypatch.setattr(window, '_confirm_table_loss', lambda: False)
        window.toggle_edit_mode(True)
        assert not window.edit_mode
    finally:
        window.deleteLater()
        qapp.processEvents()
