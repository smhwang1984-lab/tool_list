# -*- coding: utf-8 -*-
"""홍보영상 소스 화면을 실제 Sum Path(NC Tool List) 앱에서 자동으로 캡처한다.

실제 앱 창(App)을 띄우고, 데모/실제 NC 프로그램을 읽어 툴리스트 산출 → Viewer →
소재 설정 → 형상 시뮬레이션 재생까지 사람이 하는 순서대로 조작하면서 화면을 PNG로 저장한다.
라이선스 창은 거치지 않는다(App 클래스를 직접 만든다). 사용자 설정(레지스트리/QSettings)은
임시 폴더로 돌려 실제 PC 설정을 건드리지 않는다.

  Windows : python promo\\capture_app.py
  Linux   : xvfb-run -a -s "-screen 0 1920x1080x24" python3 promo/capture_app.py

결과: promo/build/shots/*.png, promo/build/frames/<scene>/0000.png ...
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROMO = Path(__file__).resolve().parent
ROOT = PROMO.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix='sumpath_promo_'))
os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
os.environ['APPDATA'] = str(TMP / 'appdata')
os.environ['LOCALAPPDATA'] = str(TMP / 'localappdata')

from PyQt5.QtCore import QCoreApplication, QSettings, QTimer  # noqa: E402

QCoreApplication.setOrganizationName('SumPathPromoCapture')

import NC_Tool_List as app  # noqa: E402
import nc_viewer_widget as nvw  # noqa: E402


class _TempSettings(QSettings):
    """앱이 QSettings("NC Tool List", ...)로 여는 설정(Windows에서는 레지스트리)을
    임시 폴더의 ini 파일로 돌린다 — 캡처 중 장비 종류·소재 값을 바꿔도 이 PC의 실제 설정은 그대로다."""

    def __init__(self, *args):
        if len(args) == 2 and all(isinstance(a, str) for a in args):
            (TMP / 'qsettings').mkdir(parents=True, exist_ok=True)
            super().__init__(str(TMP / 'qsettings' / ('%s_%s.ini' % args)), QSettings.IniFormat)
        else:
            super().__init__(*args)


app.QSettings = _TempSettings
nvw.QSettings = _TempSettings
from pyqtgraph import Vector  # noqa: E402

sys.path.insert(0, str(PROMO / 'demo_nc'))
import make_demo_programs  # noqa: E402

OUT = PROMO / 'build'
SHOTS = OUT / 'shots'
FRAMES = OUT / 'frames'
DEMO = PROMO / 'demo_nc'
REAL_PROGRAM = ROOT / 'ncdata.nc'

MILL_FRAMES = 150
LATHE_FRAMES = 110
ROTATE_FRAMES = 90

qa = app.QApplication.instance() or app.QApplication(sys.argv)
win = app.App(_root=str(TMP / 'root'))
win.resize(1920, 1080)
win.show()


def pump(n=15):
    for _ in range(n):
        qa.processEvents()


def shot(name, widget=None):
    pump()
    (widget or win).grab().save(str(SHOTS / ('%s.png' % name)))
    print('  shot', name, flush=True)


def frame_dir(name):
    d = FRAMES / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    return d


def viewer():
    return win.viewer


def set_camera(center, distance, elevation=30, azimuth=-45):
    viewer().gl_view.setCameraPosition(pos=Vector(*center), distance=distance,
                                       elevation=elevation, azimuth=azimuth)
    pump()


def set_machine(name):
    win.machine_type_combo.setCurrentText(name)
    pump(20)


def load(path, lathe=False):
    win.set_mode('list')
    win.tool_mode_combo.setCurrentText('선반' if lathe else '밀링')
    win.load_file(str(path))
    pump()
    win.run()
    pump()


def sim_to(seq):
    """형상 시뮬레이션 엔진을 seq 시점의 누적 절삭 결과로 맞춘다.
    앱은 평소 '공정 필터에서 선택한 공정까지'의 누적 형상을 보여 준다. 영상에서는 같은 엔진을
    프레임마다 조금씩 전진시켜 깎여 나가는 과정을 연속 화면으로 만든다."""
    v = viewer()
    v._sim_advance_to_seq(seq)
    v.sim_wait(180000)
    v._sim_do_mesh_refresh()


def play_frames(name, count, center, distance, elevation=30, azimuth=-45, orbit=0.0):
    """PG 매칭 재생과 같은 경로(_goto_seq)로 seq를 전진시키며 프레임을 저장한다."""
    v = viewer()
    total = v.sequence_length()
    d = frame_dir(name)
    labels = []
    for i in range(count):
        seq = int(round((total - 1) * (i / (count - 1)) ** 1.1))
        win._goto_seq(seq)
        sim_to(seq)
        key = v.seq_to_tool_map.get(seq)
        labels.append(v._tool_display_text(key) if key else '')
        set_camera(center, distance, elevation, azimuth + orbit * i / (count - 1))
        pump(6)
        win.grab().save(str(d / ('%04d.png' % i)))
    # 프레임마다 그 시점의 공정 이름(공정 필터 목록과 같은 문구) — 영상 라벨에 쓴다
    (d / 'meta.json').write_text(json.dumps({'labels': labels}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('  frames', name, count, flush=True)


def scene_mill():
    print('[mill] demo milling program', flush=True)
    load(DEMO / 'DEMO_MILL.nc')
    shot('mill_list')
    pdf = OUT / 'mill_toollist.pdf'
    app.export_tool_list_pdf(str(pdf), win.current_rows(), win.metadata)

    win.set_mode('viewer')
    pump(30)
    win.set_machine_panel_expanded(True)
    set_machine(nvw.MACHINE_5AXIS_AC)
    shot('machine_5ax_panel')
    set_machine('3축 MCT (X Y Z)')
    shot('machine_3ax_panel')
    win.set_machine_panel_expanded(False)
    pump()

    v = viewer()
    v._sim_sync = True
    win.pg_match_check.setChecked(True)      # PG 매칭: 재생 위치까지의 경로만 표시
    win._goto_seq(0)
    set_camera((0, 0, -10), 230)
    shot('mill_toolpath')
    # 사용자가 하는 그대로: [소재] 창을 열고 치수를 넣은 뒤 [적용]
    dialog = v.open_stock_dialog(win)
    pump(10)
    dialog.enable_check.setChecked(True)
    for key, value in (('T', 30.0), ('W', 80.0), ('L', 100.0)):
        dialog.dim_spins[key].setValue(value)
    dialog.resolution_combo.setCurrentText('0.2')
    pump(10)
    dialog._apply()
    pump(20)
    shot('mill_stock_dialog', dialog)
    dialog.hide()
    sim_to(0)
    set_camera((0, 0, -10), 230)
    shot('mill_stock_ready')
    play_frames('mill_sim', MILL_FRAMES, (0, 0, -10), 230, orbit=40)
    shot('mill_sim_done')
    for mode in ('depth',):
        v.set_sim_color_mode(mode)
        pump(10)
        shot('mill_sim_%s' % mode)
    v.set_sim_color_mode('tool')


def scene_lathe():
    print('[lathe] demo lathe program', flush=True)
    win.set_mode('list')
    load(DEMO / 'DEMO_LATHE.nc', lathe=True)
    shot('lathe_list')
    win.set_mode('viewer')
    pump(20)
    win.set_machine_panel_expanded(True)
    set_machine(nvw.MACHINE_LATHE)
    shot('machine_lathe_panel')
    win.set_machine_panel_expanded(False)
    load(DEMO / 'DEMO_LATHE.nc', lathe=True)   # 선반 장비로 다시 해석
    win.set_mode('viewer')
    pump(20)
    v = viewer()
    v._sim_sync = True
    win._goto_seq(0)
    dialog = v.open_stock_dialog(win)
    pump(10)
    dialog.enable_check.setChecked(True)
    for key, value in (('diameter', 60.0), ('length', 80.0), ('front_z', 0.5), ('bore', 0.0)):
        if key in dialog.dim_spins:
            dialog.dim_spins[key].setValue(value)
    pump(10)
    dialog._apply()
    pump(20)
    shot('lathe_stock_dialog', dialog)
    dialog.hide()
    sim_to(0)
    set_camera((-35, 0, 0), 190, elevation=25, azimuth=-60)
    shot('lathe_stock_ready')
    play_frames('lathe_sim', LATHE_FRAMES, (-35, 0, 0), 190, elevation=25, azimuth=-60, orbit=30)
    shot('lathe_sim_done')


def scene_real():
    print('[real] 5-axis production program', flush=True)
    win.set_mode('list')
    load(REAL_PROGRAM)
    shot('real_list')
    win.set_mode('viewer')
    pump(30)
    set_machine(nvw.MACHINE_5AXIS_AC)
    win.pg_match_check.setChecked(False)     # 재생 위치와 무관하게 전체 툴패스를 보인다
    pump(20)
    set_camera((15, -20, 60), 235)
    shot('real_toolpath')
    d = frame_dir('real_rotate')
    for i in range(ROTATE_FRAMES):
        set_camera((15, -20, 60), 235, elevation=28, azimuth=-80 + 120 * i / (ROTATE_FRAMES - 1))
        pump(4)
        win.grab().save(str(d / ('%04d.png' % i)))
    print('  frames real_rotate', flush=True)
    win.show_settings()
    pump(20)
    if getattr(win, '_settings_dialog', None) is not None:
        shot('settings_dialog', win._settings_dialog)
        win._settings_dialog.hide()


def main():
    t0 = time.time()
    # 데모 NC 프로그램은 저장소에 넣지 않고(.nc는 .gitignore 대상) 매번 새로 만든다
    (DEMO / 'DEMO_MILL.nc').write_text(make_demo_programs.mill_program(), encoding='utf-8')
    (DEMO / 'DEMO_LATHE.nc').write_text(make_demo_programs.lathe_program(), encoding='utf-8')
    SHOTS.mkdir(parents=True, exist_ok=True)
    FRAMES.mkdir(parents=True, exist_ok=True)
    try:
        scene_mill()
        scene_lathe()
        scene_real()
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        qa.exit(1)
        return
    print('done in %.1fs' % (time.time() - t0), flush=True)
    qa.exit(0)


if __name__ == '__main__':
    QTimer.singleShot(1200, main)
    code = qa.exec_()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
