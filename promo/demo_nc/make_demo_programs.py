# -*- coding: utf-8 -*-
"""홍보영상용 데모 NC 프로그램 생성기.

CATIA 포스트(PPTABLE 설정)가 찍어 주는 공구 정보 주석 형식을 그대로 따른다.
  N1(#1: Tool Change)
   (T2 // D10 F.EM [SO 40] // T2 BT40-SK16-120 )      <- 공구명 / SO / 홀더
   (LCF ... FL ... GL ... F n)                        <- 길이 정보
   (DC ... RE ... SIG ... PL ...)                     <- 지름·코너R·선단각
   (SPINDL ... FEED ...)                              <- 회전수·이송
실행: python make_demo_programs.py  ->  DEMO_MILL.nc, DEMO_LATHE.nc
"""
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def f(v):
    return ('%.3f' % v).rstrip('0').rstrip('.') + '.' if float(v).is_integer() else ('%.3f' % v).rstrip('0')


def tool_header(n, t, name, so, holder, lcf, fl, gl, flutes, dc, re_, sig, pl, rpm, feed):
    sig_s = 'SIG %8.6f' % sig if sig else 'SIG'
    pl_s = 'PL %10.6f' % pl if pl else 'PL'
    return [
        '',
        'N%d(#%d: Tool Change)' % (n, n),
        ' (T%d // %s [SO %d] // T%d %s )' % (t, name, so, t, holder),
        ' (LCF %12.6f FL %12.6f GL %12.6f F %d)' % (lcf, fl, gl, flutes),
        ' (DC %12.6f RE %12.6f %s %s )' % (dc, re_, sig_s, pl_s),
        ' (SPINDL %12.6f FEED %12.6f)' % (rpm, feed),
        'M6 T%d' % t,
        'M1',
        'G0 G90 G54',
        'S%d M3' % rpm,
        'G43 Z50. H%02d' % t,
        'M8',
    ]


def rect(cx, cy, hx, hy):
    return [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy), (cx - hx, cy - hy)]


def mill_program():
    L = ['%', 'O0100', '( ** TECH STAR ** )', '( PGM NO :  OP10_DEMO_BLOCK )', '( PROGRAMER : S M.HWANG )',
         '( COMPLETE TIME : 09:30:00 )', '( DATE : 2026-11-01 )', '( MACHINE : 3AX-MCT / WORK CODE: 100 )',
         '( STOCK : 100 X 80 X 30 )', 'G0 G90 G49 G69 G80 G40 G17']
    # 1) 페이스밀 D50 — 윗면 1mm
    L += tool_header(1, 1, 'D50 F.MIL', 60, 'BT40-FMC22-60', 60, 6, 120, 4, 50, 0.8, 0, 0, 2500, 1800)
    L += ['G0 X-80. Y-30.', 'Z5.', 'G1 Z-1. F600.']
    for i, y in enumerate((-30, 5, 40)):
        xs = (80, -80) if i % 2 == 0 else (-80, 80)
        L += ['G1 Y%s F1800.' % f(y), 'X%s' % f(xs[0])]
    L += ['G0 Z50.', 'M9']
    # 2) 평엔드밀 D10 — 사각 포켓 60x40 깊이 10 (2mm씩)
    L += tool_header(2, 2, 'D10 F.EM', 40, 'BT40-SK16-120', 38.5, 26, 160, 3, 10, 0, 0, 0, 8000, 2400)
    L += ['G0 X0. Y0.', 'Z2.']
    for z in (-3, -5, -7, -9, -11):
        L.append('G1 Z%s F500.' % f(z))
        for hx, hy in ((6, 1), (11, 6), (16, 11), (21, 11.5), (25, 15)):
            pts = rect(0, 0, hx, hy)
            L.append('G1 X%s Y%s F2400.' % (f(pts[0][0]), f(pts[0][1])))
            for x, y in pts[1:]:
                L.append('X%s Y%s' % (f(x), f(y)))
        L.append('G1 X0. Y0.')
    L += ['G0 Z50.', 'M9']
    # 3) 평엔드밀 D6 — 외곽 단차(R코너) 깊이 6
    L += tool_header(3, 3, 'D6 F.EM', 35, 'BT40-SK13-120', 35, 15, 155, 3, 6, 0, 0, 0, 10000, 2000)
    L += ['G0 X-60. Y-48.', 'Z2.']
    for z in (-3, -5, -7):
        L += ['G1 Z%s F600.' % f(z), 'G1 X-38. F2000.',
              'X38.', 'G3 X48. Y-38. I0. J10.', 'G1 Y38.', 'G3 X38. Y48. I-10. J0.',
              'G1 X-38.', 'G3 X-48. Y38. I0. J-10.', 'G1 Y-38.', 'G3 X-38. Y-48. I10. J0.', 'G1 X-60.']
    L += ['G0 Z50.', 'M9']
    # 4) 드릴 D8.5 — 4구멍
    L += tool_header(4, 4, 'D8.5 DRILL', 45, 'BT40-SK13-90', 45, 40, 135, 2, 8.5, 0, 118, 2.553, 2200, 260)
    for x, y in ((-40, -30), (40, -30), (40, 30), (-40, 30)):
        L += ['G0 X%s Y%s' % (f(x), f(y)), 'Z0.', 'G1 Z-22. F260.', 'G0 Z0.']
    L += ['G0 Z50.', 'M9']
    # 5) 볼엔드밀 D4 — 포켓 바닥 물결 각인
    L += tool_header(5, 5, 'D4 B.EM', 25, 'BT40-SK10-120', 25, 8, 140, 2, 4, 2, 0, 0, 12000, 1500)
    L += ['G0 X-20. Y0.', 'Z-9.']
    for k, y0 in enumerate((-6, 0, 6)):
        pts = [(-20 + i * 0.5, y0 + 3 * math.sin((-20 + i * 0.5) / 4.0)) for i in range(81)]
        if k % 2:
            pts.reverse()
        L.append('G1 X%s Y%s Z-11.6 F800.' % (f(pts[0][0]), f(round(pts[0][1], 3))))
        L += ['X%s Y%s' % (f(x), f(round(y, 3))) for x, y in pts[1:]]
        L.append('G1 Z-9.')
    L += ['G0 Z50.', 'M9', 'G91 G28 Z0.', 'M30', '%']
    return '\n'.join(L) + '\n'


def lathe_program():
    L = ['%', 'O3300', '( ** TECH STAR ** )', '(PART NO. : DEMO-SHAFT-01)', '(OPERATION : OP10)',
         '(PGM NO. : O3300)', '(PROGRAMER : SM.HWANG)', '(TIME : 2026-11-01 10:00:00)',
         '( MACHINE : LATHE / STOCK D60 L80 )', '']
    # 1) 외경 황삭
    L += ['N1', '( T01 - PCLNR 2525M 12 )', '( T01 - CNMG 120408 | R-0.8 )', 'G0X150.Z100.', 'T0100',
          'G50S2500', 'G96S220M3', 'T0101', 'G99G18X64.Z2.', 'G1Z0.5F.2', 'X-1.6F.15', 'G0X64.Z2.']
    # 단차 프로파일: 0~-30 지름 36, -30~-55 지름 48, 나머지 60
    for d in (56, 52, 48):
        L += ['G0X%s' % f(d), 'G1Z-55.F.25', 'X62.', 'G0Z2.']
    for d in (44, 40, 37):
        L += ['G0X%s' % f(d), 'G1Z-30.F.25', 'X50.', 'G0Z2.']
    L += ['G0X150.Z100.T0100', 'M1', '']
    # 2) 외경 정삭 + 모따기
    L += ['N2', '( T03 - PDJNR 2525M 15 )', '( T03 - DNMG 150404 | R-0.4 )', 'G0X150.Z100.', 'T0300',
          'G96S260M3', 'T0303', 'G99G18X30.Z2.', 'G1X30.Z0.F.1', 'X36.Z-3.', 'Z-30.', 'X44.', 'X48.Z-32.',
          'Z-55.', 'X56.', 'X60.Z-57.', 'G0X64.', 'G0X150.Z100.T0300', 'M1', '']
    # 3) 홈 가공
    L += ['N3', '( T05 - MGEHR 2525-3 )', '( T05 - MGMN 300-M | R-0.2 )', 'G0X150.Z100.', 'T0500',
          'G97S800M3', 'T0505', 'G99G18X50.Z-42.', 'G1X40.F.05', 'G0X50.', 'Z-44.', 'G1X40.F.05', 'G0X50.',
          'G0X150.Z100.T0500', 'M1', '']
    # 4) 나사 M36x2
    L += ['N4', '( T07 - SER 2525 M16 )', '( T07 - 16ER 2.0 ISO )', 'G0X150.Z100.', 'T0700', 'G97S700M3',
          'T0707', 'G99G18X40.Z5.', 'G76P020060Q50R.02', 'G76X33.54Z-24.P1227Q300R0.F2.0',
          'G0X150.Z100.T0700', 'M30', '%']
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    (HERE / 'DEMO_MILL.nc').write_text(mill_program(), encoding='utf-8')
    (HERE / 'DEMO_LATHE.nc').write_text(lathe_program(), encoding='utf-8')
    print('written:', HERE / 'DEMO_MILL.nc', HERE / 'DEMO_LATHE.nc')
