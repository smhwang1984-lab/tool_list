// v2.5.9: 3축 설정이어도 G43.4/G68.2 + 회전축 워드가 있으면 프로그램에서 5축 구성을 읽는다 (원본 test_nc_sim_viewer)
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { MACHINE_5AXIS_AC, MACHINE_5AXIS_BC, detectRotaryMachine, toolpathFromText } from '../src/core/toolpath';

const THREE = '3축 MCT (X Y Z)';
const text = readFileSync(new URL('./fixtures/O3210_excerpt.nc', import.meta.url), 'utf-8');

describe('v2.5.9 회전축 구성 자동 판정', () => {
  it('판정 규칙', () => {
    expect(detectRotaryMachine(['G1 X1.', 'G0 B0.'])).toBeNull();
    expect(detectRotaryMachine(['G43.4 Z150. H6', 'G1 B30. C10.'])).toBe(MACHINE_5AXIS_BC);
    expect(detectRotaryMachine(['G43.4 Z150. H6', 'G1 A30. C10.'])).toBe(MACHINE_5AXIS_AC);
    expect(detectRotaryMachine(['(G43.4 ) B30.'])).toBeNull();
  });
  it('3축 설정으로도 O3210 공구 축이 B→C 설정과 같다', () => {
    const lines = text.split(/\r?\n/);
    const first = lines.findIndex((l) => l.startsWith('G0 X-114.977'));
    const auto = toolpathFromText(text, THREE);
    const ref = toolpathFromText(text, MACHINE_5AXIS_BC);
    const a = auto.line_axis_map.get(first)!;
    const r = ref.line_axis_map.get(first)!;
    expect(a).toBeDefined();
    r.forEach((v, i) => expect(a[i]).toBeCloseTo(v, 9));
    expect(Math.hypot(a[0], a[1])).toBeGreaterThan(0.1);
    expect(auto.machine_auto_note).toBe('5축 B→C로 계산 · 장비 설정 3축');
    expect(ref.machine_auto_note).toBe('');
  });
});

describe('v2.5.9 테이블 회전 표시용 회전축 기록', () => {
  const prog = ['M6 T6', 'G43.4 Z150. H6', 'G0 X0. Y0. B30. C90.', 'G1 X10. Y0. Z5. F500', 'G49', 'G1 X20.', 'M30'];
  it('G43.4 구간은 [종류, A, B, C], G49 뒤는 null', () => {
    const r = toolpathFromText(prog.join('\n'), MACHINE_5AXIS_BC);
    const at = (line: number): unknown => r.seq_to_table_rot!.get(r.line_to_seq.get(line)!);
    expect(at(3)).toEqual(['bc', 0, 30, 90]);
    expect(at(5)).toBeNull();
  });
  it('A→C 와 3축 설정 자동 판정', () => {
    const ac = ['M6 T6', 'G43.4 Z150. H6', 'G0 X0. Y0. A-30. C0.', 'G1 X10. F500'];
    const r = toolpathFromText(ac.join('\n'), THREE);
    expect(r.seq_to_table_rot!.get(r.line_to_seq.get(3)!)).toEqual(['ac', -30, 0, 0]);
    expect(r.machine_auto_note).toBe('5축 A→C로 계산 · 장비 설정 3축');
  });
  it('G68.2 경사면은 공구 축에서 각도를 구한다', () => {
    const p = ['M6 T6', 'G68.2 P1 X0. Y0. Z0. I0. J-90. K0.', 'G53.1', 'G43 Z10. H6', 'G1 X1. F100'];
    const r = toolpathFromText(p.join('\n'), MACHINE_5AXIS_AC);
    const info = r.seq_to_table_rot!.get(r.line_to_seq.get(4)!);
    expect(info?.[0]).toBe('ac');
    expect(Math.abs(info![1])).toBeCloseTo(90, 5);
  });
});
