// 소재 해상도 목록의 엔진별 묶음 — 원본 nc_viewer_widget.py SIM_RES_* / normalize_resolution_key / resolution_choice (v2.7.1).
//   기본 엔진 · CPU  — 지금 쓰는 Z-map/복셀(셀 크기 mm). 저장 키는 예전과 같은 '자동', '0.05' ...
//   고해상도 엔진 · GPU — 소재 긴 변의 칸 수. 저장 키는 'gpu:auto', 'gpu:2048' ...
// 고해상도 엔진(원본 PLAN_gpu_sim_and_licensing.md 4장 G, v2.8.1 G4)은 이 기기가 WebGL2 하드웨어 그래픽을 쓸 수 있을 때만 열린다.
// 뷰어가 만들어질 때 sim/zmapGpu.gpuProbe 결과를 setGpuAvailability 로 알린다. 못 쓰면 GPU 묶음은 흐리게 두고 이유를 보인다.
// 원본과 다른 점(이유 기록, 안드로이드 CLAUDE.md 4절 6번): 휴대폰은 그래픽 메모리가 작아 8192 칸을 두지 않는다(4096까지).

let gpuState = { ok: false, reason: '그래픽 확인 전입니다', renderer: '' };
export function setGpuAvailability(ok: boolean, reason = '', renderer = ''): void { gpuState = { ok, reason, renderer }; }
export function gpuAvailability(): { ok: boolean; reason: string; renderer: string } { return gpuState; }

export const RES_CPU_KEYS = ['자동', '0.05', '0.1', '0.2', '0.5', '1.0'] as const;
export const RES_GPU_KEYS = ['gpu:auto', 'gpu:2048', 'gpu:4096', 'gpu:max'] as const;
export const RES_GROUP_CPU = '기본 엔진 · CPU';
export const RES_GROUP_GPU = '고해상도 엔진 · GPU';

/** 목록에 보이는 글자 */
export function resolutionLabel(key: string): string {
  if (key === '자동') return '자동';
  if (key === 'gpu:auto') return '자동 (그래픽 메모리에 맞춤)';
  if (key === 'gpu:max') return '최고 (CAM 수준 · 목표 0.01 mm)';
  if (key.startsWith('gpu:')) return `${key.slice(4)} 칸`;
  return `${key} mm`;
}

/** 저장돼 있던 값을 지금 쓸 수 있는 키로 바로잡는다. 모르는 값이거나 쓸 수 없는 엔진이면 '자동'. */
export function normalizeResolutionKey(key: unknown, gpuAvailable: boolean = gpuState.ok): string {
  const k = typeof key === 'string' ? key : '자동';
  if ((RES_CPU_KEYS as readonly string[]).includes(k)) return k;
  if (gpuAvailable && (RES_GPU_KEYS as readonly string[]).includes(k)) return k;
  return '자동';
}

export type ResolutionChoice = { engine: 'cpu'; value: number | null } | { engine: 'gpu'; value: number | null; max?: boolean };

/** 키 → 엔진과 값. cpu의 값은 셀 크기(mm, 자동이면 null), gpu의 값은 긴 변 칸 수(자동이면 null). */
export function resolutionChoice(key: string): ResolutionChoice {
  if (key.startsWith('gpu:')) {
    const tail = key.slice(4);
    if (tail === 'max') return { engine: 'gpu', value: null, max: true };
    return { engine: 'gpu', value: tail === 'auto' ? null : parseInt(tail, 10) };
  }
  return { engine: 'cpu', value: key === '자동' ? null : parseFloat(key) };
}

/** 소재 계산에 넘기는 해상도: 숫자 = CPU 셀 크기(mm), null = CPU 자동, { gpu } = 고해상도 엔진(긴 변 칸 수, null이면 자동) */
export type SimResolution = number | null | { gpu: number | null; max?: boolean };

export function simResolutionOf(key: string): SimResolution {
  const c = resolutionChoice(key);
  return c.engine === 'gpu' ? (c.max ? { gpu: null, max: true } : { gpu: c.value }) : c.value;
}
