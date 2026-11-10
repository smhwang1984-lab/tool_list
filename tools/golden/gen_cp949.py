"""원본 Python cp949 표를 src/core/cp949Table.ts 로 내보낸다.  실행: python tools/golden/gen_cp949.py"""
import json
from pathlib import Path

entries = []
for lead in range(0x81, 0xFF):
    for trail in range(256):
        try:
            ch = bytes([lead, trail]).decode('cp949')
        except UnicodeDecodeError:
            continue
        entries.append((lead * 256 + trail, ord(ch)))
runs = []
for pos, cp in entries:
    if runs and runs[-1][0] + runs[-1][2] == pos and runs[-1][1] + runs[-1][2] == cp:
        runs[-1][2] += 1
    else:
        runs.append([pos, cp, 1])
flat, pp, pc = [], 0, 0
for pos, cp, n in runs:
    flat += [pos - pp, cp - pc, n]
    pp, pc = pos + n, cp + n
src = ("// 자동 생성 파일 — tools/golden/gen_cp949.py 로 만든다. 직접 고치지 않는다.\n"
       "// 원본 Python cp949 코덱의 2바이트 표(%d글자). [위치 차이, 글자코드 차이, 연속 길이]를 이어 붙인 모양.\n"
       "// 위치 = 앞바이트*256 + 뒤바이트. (WebView·Node의 euc-kr 디코더는 표가 달라서 쓰지 않는다.)\n"
       "export const CP949_RUNS: readonly number[] = %s;\n") % (len(entries), json.dumps(flat, separators=(',', ':')))
Path(__file__).resolve().parents[2].joinpath('src/core/cp949Table.ts').write_text(src, encoding='utf-8', newline='\n')
