// 원본 tests/test_v265_vericut.py 와 같은 기대값 — VERICUT 비교(장비 기본값 · 급속 속도 · G91 · G28/G30 · 사이클 해제)
import { describe, expect, it } from 'vitest';
import { DEFAULT_MACHINE_SPECS, isLatheMachine, loadMachineSpecs, MACHINE_5AXIS_AC, MACHINE_5AXIS_BC } from '../src/core/machines';
import { ModalTimeline, summaryText } from '../src/core/modal';
import {
  addIncrementalWord, effectiveFeedMmPerMin, machineRapidFeed, processNcLines, RAPID_FEED_MM_PER_MIN, SPEC_RAPID,
} from '../src/core/toolpath';

const timeline = (text: string, lathe = false): ModalTimeline =>
  new ModalTimeline(text.split('\n').map((l, i) => [i, l] as const), lathe);
const MILL3 = '3축 MCT (X Y Z)';
const run = (machine: string, text: string) => processNcLines(text.split('\n'), machine, DEFAULT_MACHINE_SPECS[machine]);

describe('v2.6.5 모달 정보 — VERICUT 규칙', () => {
  it('G00~G03은 고정 사이클 해제', () => {
    const tl = timeline('G0 G90 X0 Y0\nG81 X0 Y0 Z-5. R2. F100\nX10.\nG0 X20. Y20.');
    expect(tl.at(2).state.groups['09']).toBe('G81');
    const { state, changed } = tl.at(3);
    expect(state.groups['09']).toBe('G80');
    expect(changed.has('09')).toBe(true);
    expect(summaryText(state, false)).toBe('F100 · G00');
  });
  it('같은 줄의 사이클 코드는 그대로', () => {
    expect(timeline('G0 X0 Y0\nG0 G81 X0 Y0 Z-5. R2. F100').at(1).state.groups['09']).toBe('G81');
  });
  it('G28/G30은 길이 보정 해제', () => {
    const tl = timeline('G43 Z50. H2\nG0 X0\nG28 G91 Z0.\nG43 Z50. H3\nG30 G91 X0.');
    expect(tl.at(1).state.groups['08']).toBe('G43 H02');
    expect(tl.at(2).state.groups['08']).toBe('G49');
    expect(tl.at(3).state.groups['08']).toBe('G43 H03');
    expect(tl.at(4).state.groups['08']).toBe('G49');
  });
  it('선반 — 이동이 드릴 사이클 해제, G28은 그룹 08 없음', () => {
    const tl = timeline('G83 Z-10. F0.1\nG0 X50.\nG28 U0.', true);
    expect(tl.at(1).state.groups['10']).toBe('G80');
    expect(tl.at(2).state.groups['08']).toBeUndefined();
  });
});

describe('v2.6.5 장비 · 급속 속도', () => {
  it('증분 워드 더하기', () => {
    expect(addIncrementalWord('-90', '-5.')).toBe('-95');
    expect(addIncrementalWord('0.000', '-5.0')).toBe('-5');
    expect(addIncrementalWord('10', '-10.')).toBe('0');
    expect(addIncrementalWord('1.5', '0.25')).toBe('1.75');
  });
  it('장비 급속 속도', () => {
    expect(machineRapidFeed({ [SPEC_RAPID]: '30000' })).toBe(30000);
    expect(machineRapidFeed({ [SPEC_RAPID]: '30,000' })).toBe(30000);
    expect(machineRapidFeed({})).toBe(RAPID_FEED_MM_PER_MIN);
    expect(machineRapidFeed({ [SPEC_RAPID]: 'abc' })).toBe(RAPID_FEED_MM_PER_MIN);
    expect(machineRapidFeed({ [SPEC_RAPID]: '0' })).toBe(RAPID_FEED_MM_PER_MIN);
    expect(effectiveFeedMmPerMin('G00', 100, 10, 30000)).toBe(30000);
    expect(effectiveFeedMmPerMin('G00', 100, 10)).toBe(RAPID_FEED_MM_PER_MIN);
  });
  it('실제 장비 기본값과 장비 종류', () => {
    const m2 = DEFAULT_MACHINE_SPECS['5축 MCT (A to C) 화천 M2']!;
    expect([m2['X 행정'], m2['Y 행정'], m2['Z 행정'], m2['A축 범위']]).toEqual(['750', '650', '500', '-120~+30']);
    expect(DEFAULT_MACHINE_SPECS['5축 MCT (A to C) 화천 M4']!['A축 범위']).toBe('-120~+120');
    const d2 = DEFAULT_MACHINE_SPECS['5축 MCT (B to C) 화천 D2']!;
    expect([d2['B축 범위'], d2[SPEC_RAPID]]).toEqual(['-30~+110', '24000']);
    expect('5축 MCT (A to C) 화천 M2'.includes(MACHINE_5AXIS_AC)).toBe(true);
    expect('5축 MCT (B to C) 화천 D2'.includes(MACHINE_5AXIS_BC)).toBe(true);
    const vesta = '3축 MCT 화천 VESTA-2000';
    expect(vesta in DEFAULT_MACHINE_SPECS && !vesta.includes('4축') && !isLatheMachine(vesta)).toBe(true);
    expect(Object.values(DEFAULT_MACHINE_SPECS).every((s) => SPEC_RAPID in s)).toBe(true);
  });
  it('저장값에 없는 새 항목은 기본값으로', () => {
    const specs = loadMachineSpecs('{"3축 MCT (X Y Z)": {"X 행정": "1234"}}');
    expect(specs[MILL3]!['X 행정']).toBe('1234');
    expect(specs[MILL3]![SPEC_RAPID]).toBe('24000');
    expect('5축 MCT (B to C) 화천 D2' in specs).toBe(true);
  });
});

describe('v2.6.5 경로 — G91 · G28/G30 · 사이클 해제', () => {
  it('G91 회전축 증분과 원점 복귀 표시', () => {
    const r = run(MACHINE_5AXIS_AC, 'G0 G90 A-90. C-90.\nG91 G0 C-5.\nG28 G91 Y0. A0. C0.\nG30 G91 X0.\nG90 G0 X1.');
    expect(r.modal_state_map.get(1)!.slice(3)).toEqual(['-90', '0.000', '-95']);
    expect(r.modal_state_map.get(2)!.slice(3)).toEqual(['0', '0.000', '0']);
    expect(r.modal_state_map.get(4)![0]).toBe('1');
  });
  it('G91 직선 이동은 증분', () => {
    const r = run(MILL3, 'G43 Z50. H1\nG0 G90 X0. Y0.\nG91 X10.\nX10. Y5.\nG90 X0.');
    expect(r.line_to_coord_map.get(2)!.slice(0, 2)).toEqual([10, 0]);
    expect(r.line_to_coord_map.get(3)!.slice(0, 2)).toEqual([20, 5]);
    expect(r.line_to_coord_map.get(4)!.slice(0, 2)).toEqual([0, 5]);
  });
  it('G30은 G28과 같은 원점', () => {
    const r = run(MILL3, 'G43 Z50. H1\nG0 G90 X10. Y10.\nG30 G91 X0.');
    expect(r.line_to_coord_map.get(2)![0]).toBeCloseTo(500);
  });
  it('G00이 밀링 사이클을 해제', () => {
    const r = run(MILL3, 'G43 Z50. H1\nG0 G90 X0. Y0.\nG81 X0. Y0. Z-5. R2. F100\nX10.\nG0 X20. Y20.');
    const pts = [...r.tool_paths.values()].flat().filter((p) => p.src_line === 4);
    expect(pts.length).toBe(1);
    expect(pts[0]!.type).toBe('G00');
    expect(pts[0]!.pt).toEqual([20, 20, 50]);
  });
});

describe('v2.6.5 장비 표시·회전 속도', () => {
  it('짧은 장비 이름과 단위', async () => {
    const { machineDisplayName, machineSpecUnit } = await import('../src/core/machines');
    expect(machineDisplayName('5축 MCT (B to C) 화천 D2')).toBe('화천 D2 · 5축 B→C');
    expect(machineDisplayName('5축 MCT (A to C) 화천 M4')).toBe('화천 M4 · 5축 A→C');
    expect(machineDisplayName('3축 MCT 화천 VESTA-2000')).toBe('화천 VESTA-2000 · 3축');
    expect(machineDisplayName('5축 MCT (A to C)')).toBe('5축 MCT (A to C)');
    expect(['X 행정', 'C축 범위', '최대 RPM', '급속 속도', '기타'].map(machineSpecUnit)).toEqual(['mm', '°', 'rpm', 'mm/min', '']);
  });
  it('회전 속도는 x10 고정', async () => {
    const { TABLE_ANIM_FIXED_RATE } = await import('../src/core/viewerSettings');
    expect(TABLE_ANIM_FIXED_RATE).toBeCloseTo(0.3 * 0.15, 9);
  });
  it('동시 5축 이동만 재생을 따른다', async () => {
    const { processNcLines } = await import('../src/core/toolpath');
    const r = processNcLines(['G0 G90 A0. C0.', 'G0 A-30. C90.', 'G43.4 H1', 'G1 X10. A-20. C100. F500', 'G1 X20.', 'G49', 'G1 A-10.'],
      '5축 MCT (A to C)', undefined);
    expect([...r.seq_table_follow!].map((s) => r.seq_to_line[s])).toEqual([3]);
  });
});
