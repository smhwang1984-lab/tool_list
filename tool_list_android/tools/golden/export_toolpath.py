# -*- coding: utf-8 -*-
"""P4-T1: 원본 NCViewerWidget.process_nc_lines 결과를 골든 JSON으로 남긴다.

NC 파일마다 장비(밀링 3축/4축/5축 AC·BC/선반)별로 경로 계산을 돌려
선분(점·종류·원본 줄·seq)·줄↔seq 대응·가공 시간을 tests/golden/toolpath/<파일>__<장비>.json 에 쓴다.
원본은 고치지 않는다(QT offscreen + 속성만 지정).

실행: ..\\..\\nc_build_venv\\Scripts\\python.exe tools\\golden\\export_toolpath.py ..  (tool_list_android 폴더에서 실행, 원본 = 상위 폴더 tool_list)
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / 'tests' / 'golden' / 'toolpath'
FIXTURES = ROOT / 'tests' / 'fixtures'
MAX_LINES = 700           # 한 파일에서 경로 계산에 쓰는 앞쪽 줄 수(JSON 크기를 줄인다)
M3, M4, M5A, M5B, LATHE = '3축 MCT (X Y Z)', '4축 MCT (B-Type)', '5축 MCT (A to C)', '5축 MCT (B to C)', 'CNC 선반 (턴밀 포함)'
# 파일별로 비교할 장비 (작은 파일은 밀링·선반 모두, 큰 파일은 알맞은 장비만)
CASES = {
    'O1699.nc': [M3, LATHE], 'O2222.nc': [M3, LATHE], 'O3210_excerpt.nc': [M3, LATHE], 'O4006.nc': [M3, LATHE],
    'O4811.nc': [M3, LATHE], 'O4812.nc': [M3, LATHE],
    '5ax_A_To_C.nc': [M3, M4, M5A, M5B], 'TurnMill_Test.nc': [LATHE], 'ncdata.nc': [M3],
    'sub_pg_test.nc': [M3, LATHE], 'O3210.NC': [LATHE],
}


def clean(value):
    """JSON으로 쓸 수 있게 바꾼다 (numpy, tuple, set 처리). 실수는 그대로 둔다."""
    import numpy as np
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, set):
        return sorted(clean(v) for v in value)
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float):
        if value != value:
            return 'nan'
        if value in (float('inf'), float('-inf')):
            return 'inf' if value > 0 else '-inf'
    return value


def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if len(argv) < 2:
        print(__doc__)
        return 2
    source = Path(argv[1]).resolve()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['NC_TOOL_LIST_GL_SAFE_MODE'] = '0'
    sys.path.insert(0, str(source))
    os.chdir(source)

    from PyQt5.QtWidgets import QApplication
    import nc_viewer_widget as nv
    app = QApplication.instance() or QApplication([])
    viewer = nv.NCViewerWidget()
    machines = list(viewer.machine_specs.keys())
    print('장비:', machines)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('*.json'):
        old.unlink()
    count = 0
    for path in sorted(FIXTURES.iterdir()):
        if path.suffix.lower() not in ('.nc', '.mpf', '.tap'):
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp949', errors='replace')
        lines = text.splitlines()[:MAX_LINES]
        for machine in CASES.get(path.name, [M3]):
            viewer.current_machine_type = machine
            viewer.last_render_signature = None
            try:
                viewer.process_nc_lines(lines)
            except Exception as error:   # 이 장비로는 계산할 수 없는 프로그램은 오류 문구를 남긴다
                data = {'file': path.name, 'machine': machine, 'error': '%s: %s' % (type(error).__name__, error)}
                print('  오류', path.name, machine, data['error'][:80])
            else:
                data = {
                    'file': path.name, 'machine': machine, 'line_count': len(lines),
                    'specs': clean(viewer.machine_specs.get(machine, {})),
                    'tool_paths': clean(viewer.tool_paths),
                    'process_tool_map': clean(viewer.process_tool_map),
                    'process_first_line': clean(viewer.process_first_line),
                    'process_first_seq': clean(viewer.process_first_seq),
                    'line_to_coord_map': clean(viewer.line_to_coord_map),
                    'line_to_tool_map': clean(viewer.line_to_tool_map),
                    'seq_to_line': clean(viewer.seq_to_line),
                    'seq_to_tool_map': clean(viewer.seq_to_tool_map),
                    'seq_to_coord_map': clean(viewer.seq_to_coord_map),
                    'seq_to_c_rot': clean(viewer.seq_to_c_rot),
                    'line_to_seq': clean(viewer.line_to_seq),
                    'line_to_seq_all': clean(viewer.line_to_seq_all),
                    'line_feed_state': clean(viewer.line_feed_state),
                    'line_axis_map': clean(viewer.line_axis_map),
                    'line_lathe_map': clean(viewer.line_lathe_map),
                    'modal_state_map': clean(viewer.modal_state_map),
                    'seq_to_modal_state': clean(viewer.seq_to_modal_state),
                    'seq_to_elapsed_sec': clean(viewer.seq_to_elapsed_sec),
                    'seq_to_dwell_sec': clean(viewer.seq_to_dwell_sec),
                    'process_time_sec': clean(viewer.process_time_sec),
                    'total_time_sec': clean(viewer.total_time_sec),
                }
            name = '%s__%s.json' % (path.stem, machine.replace(' ', '_').replace('/', '_'))
            (OUT / name).write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            count += 1
    print('쓴 파일', count, '->', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
