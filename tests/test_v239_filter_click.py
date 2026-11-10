# -*- coding: utf-8 -*-
"""v2.3.9: 공정 필터 — 켤 때만 프로그램 위치 이동, 끌 때는 그대로."""
import pytest

pytest.importorskip('PyQt5')
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QListWidget, QListWidgetItem  # noqa: E402

import nc_viewer_widget as nv  # noqa: E402


def test_filter_click_jumps_only_when_turned_on():
    app = QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    viewer.process_first_line = {'T01': 7}
    jumps = []
    viewer.process_activated.connect(jumps.append)
    item = QListWidgetItem('T01')
    item.setData(Qt.UserRole, 'T01')
    lst = QListWidget()
    lst.addItem(item)
    item.setSelected(True)
    viewer._on_tool_filter_item_clicked(item)
    assert jumps == [7]
    item.setSelected(False)
    viewer._on_tool_filter_item_clicked(item)
    assert jumps == [7]
