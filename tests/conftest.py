"""pytest 공용 설정 — 테스트가 만든 Qt 창을 테스트마다 실제로 파괴한다.

테스트들은 창 정리를 `deleteLater()`로 예약만 하는데, 예약된 삭제(DeferredDelete)는 이벤트 루프가
돌아야 실행된다. 전체 테스트를 한 프로세스에서 돌리면 뷰어(OpenGL 위젯 포함)가 수십 개 쌓여,
약 300번째 테스트(대용량 프로그램 로드)에서 Windows 접근 위반으로 프로세스가 죽는 일이 있었다
(v2.1.0·v2.2.0 개발 중 실측). 테스트가 끝날 때마다 예약된 삭제를 처리하고 가비지를 수거해
살아 있는 창 수를 일정하게 유지한다.
"""
import gc

import pytest


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
