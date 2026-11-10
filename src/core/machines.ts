// 장비 타입과 기본 스펙 — 원본 nc_viewer_widget.py DEFAULT_MACHINE_SPECS (순서 포함)
import { isLatheMachine } from './latheParser';

export const MACHINE_5AXIS_AC = '5축 MCT (A to C)';
export const MACHINE_5AXIS_BC = '5축 MCT (B to C)';
export const MACHINE_LATHE = 'CNC 선반 (턴밀 포함)';

export type MachineSpecs = Record<string, Record<string, string>>;

export const DEFAULT_MACHINE_SPECS: Readonly<MachineSpecs> = {
  [MACHINE_5AXIS_AC]: {
    'X 행정': '800', 'Y 행정': '800', 'Z 행정': '600', 'A축 범위': '-120~+30', 'C축 범위': '360',
  },
  '3축 MCT (X Y Z)': { 'X 행정': '1000', 'Y 행정': '600', 'Z 행정': '600' },
  '4축 MCT (B-Type)': { 'X 행정': '1200', 'Y 행정': '800', 'Z 행정': '800', 'B축 범위': '-120~+120' },
  [MACHINE_LATHE]: { 'X 행정': '300', 'Z 행정': '500', '최대 RPM': '4000' },
  [MACHINE_5AXIS_BC]: {
    'X 행정': '600', 'Y 행정': '600', 'Z 행정': '500', 'B축 범위': '-110~+110', 'C축 범위': '360',
  },
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
          specs[name] = Object.fromEntries(Object.entries(spec).map(([k, v]) => [String(k), String(v).trim()]));
        }
      }
    }
  } catch {
    /* 기본값 */
  }
  return specs;
}

export { isLatheMachine };
