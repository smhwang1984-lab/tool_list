// 장비 타입과 기본 스펙 — 원본 nc_viewer_widget.py DEFAULT_MACHINE_SPECS (순서 포함)
import { isLatheMachine } from './latheParser';

export const MACHINE_5AXIS_AC = '5축 MCT (A to C)';
export const MACHINE_5AXIS_BC = '5축 MCT (B to C)';
export const MACHINE_LATHE = 'CNC 선반 (턴밀 포함)';

export type MachineSpecs = Record<string, Record<string, string>>;

export const DEFAULT_MACHINE_SPECS: Readonly<MachineSpecs> = {
  [MACHINE_5AXIS_AC]: {
    'X 행정': '800', 'Y 행정': '800', 'Z 행정': '600', 'A축 범위': '-120~+30', 'C축 범위': '360', '급속 속도': '24000',
  },
  '3축 MCT (X Y Z)': { 'X 행정': '1000', 'Y 행정': '600', 'Z 행정': '600', '급속 속도': '24000' },
  '4축 MCT (B-Type)': { 'X 행정': '1200', 'Y 행정': '800', 'Z 행정': '800', 'B축 범위': '-120~+120', '급속 속도': '24000' },
  [MACHINE_LATHE]: { 'X 행정': '300', 'Z 행정': '500', '최대 RPM': '4000', '급속 속도': '24000' },
  [MACHINE_5AXIS_BC]: {
    'X 행정': '600', 'Y 행정': '600', 'Z 행정': '500', 'B축 범위': '-110~+110', 'C축 범위': '360', '급속 속도': '24000',
  },
  // 원본 v2.6.5: 실제 장비(VERICUT 장비 파일의 행정 · 회전축 범위)
  [`${MACHINE_5AXIS_AC} 화천 M2`]: {
    'X 행정': '750', 'Y 행정': '650', 'Z 행정': '500', 'A축 범위': '-120~+30', 'C축 범위': '360', '급속 속도': '24000',
  },
  [`${MACHINE_5AXIS_AC} 화천 M4`]: {
    'X 행정': '950', 'Y 행정': '1000', 'Z 행정': '651', 'A축 범위': '-120~+120', 'C축 범위': '360', '급속 속도': '24000',
  },
  [`${MACHINE_5AXIS_BC} 화천 D2`]: {
    'X 행정': '650', 'Y 행정': '500', 'Z 행정': '500', 'B축 범위': '-30~+110', 'C축 범위': '360', '급속 속도': '24000',
  },
  '3축 MCT 화천 VESTA-2000': { 'X 행정': '2004', 'Y 행정': '850', 'Z 행정': '801', '급속 속도': '24000' },
};

export const cloneDefaultSpecs = (): MachineSpecs => JSON.parse(JSON.stringify(DEFAULT_MACHINE_SPECS)) as MachineSpecs;

/** 저장된 JSON 을 읽어 기본값과 합친다. 깨졌으면 기본값. 저장된 장비만 덮어쓰고 없는 장비는 기본값으로 둔다. */
export function loadMachineSpecs(raw: string): MachineSpecs {
  const specs = cloneDefaultSpecs();
  try {
    const saved = JSON.parse(raw) as unknown;
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      for (const [name, spec] of Object.entries(saved as Record<string, unknown>)) {
        if (spec && typeof spec === 'object' && !Array.isArray(spec)) {
          // 원본 v2.6.5: 저장값에 없는 새 항목(급속 속도 등)은 기본값으로 채운다
          specs[name] = { ...(specs[name] ?? {}), ...Object.fromEntries(Object.entries(spec).map(([k, v]) => [String(k), String(v).trim()])) };
        }
      }
    }
  } catch {
    /* 기본값 */
  }
  return specs;
}

export { isLatheMachine };

// 원본 v2.6.5 machine_display_name: 실제 장비는 "화천 D2 · 5축 B→C"처럼 장비 이름을 앞에 둔다(저장 이름은 그대로).
const MACHINE_KIND_SHORT: [string, string][] = [
  ['5축 MCT (A to C)', '5축 A→C'], ['5축 MCT (B to C)', '5축 B→C'],
  ['4축 MCT (B-Type)', '4축'], ['3축 MCT (X Y Z)', '3축'], ['3축 MCT', '3축'],
];
export function machineDisplayName(name: string): string {
  const at = name.indexOf(' 화천 ');
  if (at < 0) return name;
  let kind = name.slice(0, at);
  const model = name.slice(at + ' 화천 '.length);
  for (const [full, short] of MACHINE_KIND_SHORT) if (kind === full) { kind = short; break; }
  return `화천 ${model} · ${kind}`;
}

/** 원본 v2.6.5 machine_spec_unit: 스펙 칸 오른쪽 단위 */
export function machineSpecUnit(key: string): string {
  if (key.endsWith('행정')) return 'mm';
  if (key.endsWith('범위')) return '°';
  if (key === '최대 RPM') return 'rpm';
  if (key === '급속 속도') return 'mm/min';
  return '';
}
