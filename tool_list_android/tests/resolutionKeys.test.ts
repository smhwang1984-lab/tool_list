import { describe, expect, it } from 'vitest';
import {
  RES_CPU_KEYS, RES_GPU_KEYS, gpuAvailability, normalizeResolutionKey, resolutionChoice, resolutionLabel, setGpuAvailability, simResolutionOf,
} from '../src/sim/resolutionKeys';

// 원본 tests/test_nc_sim_viewer.py test_resolution_keys_stay_compatible_and_gpu_group_is_closed_for_now 와 같은 약속
describe('해상도 엔진 묶음 (원본 v2.7.1)', () => {
  it('예전에 저장된 값은 그대로 읽힌다', () => {
    for (const k of RES_CPU_KEYS) expect(normalizeResolutionKey(k, false)).toBe(k);
  });

  it('고해상도 엔진이 없으면 gpu 키는 자동으로 바로잡고, 있으면 그대로 둔다', () => {
    expect(normalizeResolutionKey('gpu:4096', false)).toBe('자동');
    expect(normalizeResolutionKey('gpu:4096', true)).toBe('gpu:4096');
    expect(normalizeResolutionKey('7.7', true)).toBe('자동');
    expect(normalizeResolutionKey(undefined, true)).toBe('자동');
    expect(normalizeResolutionKey(5, true)).toBe('자동');
  });

  it('키에서 엔진과 값을 읽는다', () => {
    expect(resolutionChoice('자동')).toEqual({ engine: 'cpu', value: null });
    expect(resolutionChoice('0.2')).toEqual({ engine: 'cpu', value: 0.2 });
    expect(resolutionChoice('gpu:auto')).toEqual({ engine: 'gpu', value: null });
    expect(resolutionChoice('gpu:4096')).toEqual({ engine: 'gpu', value: 4096 });
  });

  it('목록 글자', () => {
    expect(resolutionLabel('0.05')).toBe('0.05 mm');
    expect(resolutionLabel('gpu:2048')).toBe('2048 칸');
    expect(resolutionLabel('자동')).toBe('자동');
  });

  it('고해상도 엔진은 뷰어가 알려 준 가용 여부를 따른다(처음에는 닫혀 있다)', () => {
    expect(gpuAvailability().ok).toBe(false);
    expect(normalizeResolutionKey('gpu:2048')).toBe('자동');
    setGpuAvailability(true, '', 'Adreno');
    try {
      expect(normalizeResolutionKey('gpu:2048')).toBe('gpu:2048');
      expect(normalizeResolutionKey('gpu:8192')).toBe('자동'); // 휴대폰은 4096까지
    } finally { setGpuAvailability(false, '시험'); }
    expect(RES_GPU_KEYS.length).toBeGreaterThan(0);
  });

  it('소재 계산에 넘기는 값', () => {
    expect(simResolutionOf('자동')).toBeNull();
    expect(simResolutionOf('0.2')).toBe(0.2);
    expect(simResolutionOf('gpu:auto')).toEqual({ gpu: null });
    expect(simResolutionOf('gpu:4096')).toEqual({ gpu: 4096 });
  });
});
