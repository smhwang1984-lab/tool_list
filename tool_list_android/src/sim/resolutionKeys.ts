// 소재 해상도 목록의 엔진별 묶음 — 원본 nc_viewer_widget.py SIM_RES_* / normalize_resolution_key / resolution_choice (v2.7.1).
//   기본 엔진 · CPU  — 지금 쓰는 Z-map/복셀(셀 크기 mm). 저장 키는 예전과 같은 '자동', '0.05' ...
//   고해상도 엔진 · GPU — 소재 긴 변의 칸 수. 저장 키는 'gpu:auto', 'gpu:2048' ...
// 고해상도 엔진(원본 PLAN_gpu_sim_and_licensing.md 4장 G)은 아직 없어서 GPU 묶음은 흐리게 두고 고를 수 없다.
// 엔진을 넣을 때 GPU_ENGINE_AVAILABLE만 바꾸면 열린다.
// 원본과 다른 점(이유 기록, 안드로이드 CLAUDE.md 4절 6번): 휴대폰은 그래픽 메모리가 작아 8192 칸을 두지 않는다(4096까지).

export const GPU_ENGINE_AVAILABLE = false;
export const RES_CPU_KEYS = ['자동', '0.05', '0.1', '0.2', '0.5', '1.0'] as const;
export const RES_GPU_KEYS = ['gpu:auto', 'gpu:2048', 'gpu:4096'] as const;
export const RES_GROUP_CPU = '기본 엔진 · CPU';
export const RES_GROUP_GPU = '고해상도 엔진 · GPU';

/** 목록에 보이는 글자 */
export function resolutionLabel(key: string): string {
  if (key === '자동') return '자동';
  if (key === 'gpu:auto') return '자동 (그래픽 메모리에 맞춤)';
  if (key.startsWith('gpu:')) return `${key.slice(4)} 칸`;
  return `${key} mm`;
}

/** 저장돼 있던 값을 지금 쓸 수 있는 키로 바로잡는다. 모르는 값이거나 쓸 수 없는 엔진이면 '자동'. */
export function normalizeResolutionKey(key: unknown, gpuAvailable: boolean = GPU_ENGINE_AVAILABLE): string {
  const k = typeof key === 'string' ? key : '자동';
  if ((RES_CPU_KEYS as readonly string[]).includes(k)) return k;
  if (gpuAvailable && (RES_GPU_KEYS as readonly string[]).includes(k)) return k;
  return '자동';
}

export type ResolutionChoice = { engine: 'cpu'; value: number | null } | { engine: 'gpu'; value: number | null };

/** 키 → 엔진과 값. cpu의 값은 셀 크기(mm, 자동이면 null), gpu의 값은 긴 변 칸 수(자동이면 null). */
export function resolutionChoice(key: string): ResolutionChoice {
  if (key.startsWith('gpu:')) {
    const tail = key.slice(4);
    return { engine: 'gpu', value: tail === 'auto' ? null : parseInt(tail, 10) };
  }
  return { engine: 'cpu', value: key === '자동' ? null : parseFloat(key) };
}
