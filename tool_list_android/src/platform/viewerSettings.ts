// Viewer 표시 설정 저장소 — 값이 바뀌면 구독자(3D 뷰어, P4)에게 알린다.
import {
  clampLineWidthPct, clampTrailBlocks, TRAIL_BLOCKS_DEFAULT, CUBE_DEFAULT, CUBE_MAX, CUBE_MIN, FOV_DEFAULT, FOV_MAX, FOV_MIN, LINE_WIDTH_DEFAULT_PCT,
  SENSITIVITY_DEFAULT, SENSITIVITY_MAX, SENSITIVITY_MIN,
} from '../core/viewerSettings';
import { getPref, getPrefNumber, setPref } from './prefs';

export interface ViewerSettings {
  lineWidthPct: number;
  sensitivityPct: number;
  cubeSizePx: number;
  fovDeg: number;
  /** 원본 v2.5.9/v2.6.0: 5축 재생 중 테이블 회전 표시(기본 켜짐) */
  tableRotation: boolean;
  /** 원본 v2.6.0: 지난 경로 숨김(기본 꺼짐)과 남길 블록 수 */
  trailHide: boolean;
  trailBlocks: number;
}

let current: ViewerSettings | null = null;
const listeners = new Set<(s: ViewerSettings) => void>();

export function getViewerSettings(): ViewerSettings {
  current ??= {
    lineWidthPct: clampLineWidthPct(getPref('toolpath_line_width_pct', String(LINE_WIDTH_DEFAULT_PCT))),
    sensitivityPct: getPrefNumber('sensitivity_pct', SENSITIVITY_DEFAULT, SENSITIVITY_MIN, SENSITIVITY_MAX),
    cubeSizePx: getPrefNumber('view_cube_size', CUBE_DEFAULT, CUBE_MIN, CUBE_MAX),
    fovDeg: getPrefNumber('fov_deg', FOV_DEFAULT, FOV_MIN, FOV_MAX),
    tableRotation: getPref('table_rotation') !== 'off',
    trailHide: getPref('trail_hide') === 'on',
    trailBlocks: clampTrailBlocks(getPref('trail_blocks', String(TRAIL_BLOCKS_DEFAULT))),
  };
  return { ...current };
}

export function updateViewerSettings(patch: Partial<ViewerSettings>): ViewerSettings {
  const next = { ...getViewerSettings(), ...patch };
  next.lineWidthPct = clampLineWidthPct(next.lineWidthPct);
  next.sensitivityPct = Math.max(SENSITIVITY_MIN, Math.min(SENSITIVITY_MAX, Math.round(next.sensitivityPct)));
  next.cubeSizePx = Math.max(CUBE_MIN, Math.min(CUBE_MAX, Math.round(next.cubeSizePx)));
  next.fovDeg = Math.max(FOV_MIN, Math.min(FOV_MAX, Math.round(next.fovDeg)));
  next.tableRotation = !!next.tableRotation;
  next.trailHide = !!next.trailHide;
  next.trailBlocks = clampTrailBlocks(next.trailBlocks);
  current = next;
  setPref('toolpath_line_width_pct', String(next.lineWidthPct));
  setPref('sensitivity_pct', String(next.sensitivityPct));
  setPref('view_cube_size', String(next.cubeSizePx));
  setPref('fov_deg', String(next.fovDeg));
  setPref('table_rotation', next.tableRotation ? 'on' : 'off');
  setPref('trail_hide', next.trailHide ? 'on' : 'off');
  setPref('trail_blocks', String(next.trailBlocks));
  for (const l of listeners) l({ ...next });
  return { ...next };
}

export function resetViewerSettings(): ViewerSettings {
  return updateViewerSettings({
    lineWidthPct: LINE_WIDTH_DEFAULT_PCT, sensitivityPct: SENSITIVITY_DEFAULT, cubeSizePx: CUBE_DEFAULT, fovDeg: FOV_DEFAULT,
    tableRotation: true, trailHide: false, trailBlocks: TRAIL_BLOCKS_DEFAULT,
  });
}

export function onViewerSettings(listener: (s: ViewerSettings) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
