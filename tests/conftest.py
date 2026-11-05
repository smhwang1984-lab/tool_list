"""pytest 공용 설정 — 테스트가 만든 Qt 창을 테스트마다 실제로 파괴한다.

테스트들은 창 정리를 `deleteLater()`로 예약만 하는데, 예약된 삭제(DeferredDelete)는 이벤트 루프가
돌아야 실행된다. 전체 테스트를 한 프로세스에서 돌리면 뷰어(OpenGL 위젯 포함)가 수십 개 쌓여,
약 300번째 테스트(대용량 프로그램 로드)에서 Windows 접근 위반으로 프로세스가 죽는 일이 있었다
(v2.1.0·v2.2.0 개발 중 실측). 테스트가 끝날 때마다 예약된 삭제를 처리하고 가비지를 수거해
살아 있는 창 수를 일정하게 유지한다.
"""
import gc
import os

import pytest

# 테스트가 App/뷰어를 만들 때마다 사용자의 실제 GL 안전 모드 카운터
# (%LOCALAPPDATA%\NC_Tool_List\viewer_gl_unsafe.flag)가 올라가지 않게 끈다. 지금까지는
# 일부 테스트 파일만 import 때 이 값을 넣어서, 그 파일 없이 한 파일만 돌리면 카운터가
# 올라가 실제 앱이 안전 모드로 떨어졌다(v2.2.8 개발 중 실측).
os.environ.setdefault('NC_TOOL_LIST_GL_SAFE_MODE', '0')


@pytest.fixture(autouse=True)
def _isolate_license_maker_dirs(tmp_path, monkeypatch):
    """발급 프로그램 테스트가 이 PC의 실제 %APPDATA%\\SumPath License Maker 나 저장소 폴더에
    서명 키·발급 기록·발급 파일을 남기지 않게 한다. 예전에는 일부 테스트가 portable_dir만 바꿔서
    발급 기록이 실제 %APPDATA%에 쌓였고, 거기 키가 생기면 USB 키가 없는 발급 프로그램이 그 키를
    잡았다(v2.3.0, 2026-11-05 실측). 각 테스트가 다시 바꾸는 값은 그 테스트 것이 우선한다."""
    import sys
    maker = sys.modules.get('SumPath_License_Maker')
    if maker is not None:
        monkeypatch.setattr(maker, 'appdata_dir', lambda: tmp_path / 'maker_appdata')
        monkeypatch.setattr(maker, 'portable_dir', lambda: tmp_path / 'maker_program')
        # v1.4.2 기존 키 자동 찾기가 실제 USB/드라이브/%APPDATA%를 뒤지지 않게 한다.
        monkeypatch.setattr(maker, 'key_search_roots', lambda: [])
        maker.reset_key_location_cache()
    yield
    if maker is not None:
        maker.reset_key_location_cache()


@pytest.fixture(autouse=True)
def _flush_deferred_qt_deletes():
    yield
    try:
        from PyQt5.QtCore import QEvent
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
    except Exception:  # noqa: BLE001 - Qt가 없는 환경(순수 엔진 테스트)에서는 할 일이 없다
        pass
    gc.collect()
