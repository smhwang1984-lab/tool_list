// Viewer 표시 설정 저장소 — 값이 바뀌면 구독자(3D 뷰어, P4)에게 알린다.
import {
  clampLineWidthPct, CUBE_DEFAULT, CUBE_MAX, CUBE_MIN, FOV_DEFAULT, FOV_MAX, FOV_MIN, LINE_WIDTH_DEFAULT_PCT,
  SENSITIVITY_DEFAULT, SENSITIVITY_MAX, SENSITIVITY_MIN,
} from '../core/viewerSettings';
import { getPref, getPrefNumber, setPref } from './prefs';

export interface ViewerSettings {
  lineWidthPct: number;
  sensitivityPct: number;
  cubeSizePx: number;
  fovDeg: number;
}

let current: ViewerSettings | null = null;
const listeners = new Set<(s: ViewerSettings) => void>();

export function getViewerSettings(): ViewerSettings {
  current ??= {
    lineWidthPct: clampLineWidthPct(getPref('toolpath_line_width_pct', String(LINE_WIDTH_DEFAULT_PCT))),
    sensitivityPct: getPrefNumber('sensitivity_pct', SENSITIVITY_DEFAULT, SENSITIVITY_MIN, SENSITIVITY_MAX),
    cubeSizePx: getPrefNumber('view_cube_size', CUBE_DEFAULT, CUBE_MIN, CUBE_MAX),
    fovDeg: getPrefNumber('fov_deg', FOV_DEFAULT, FOV_MIN, FOV_MAX),
  };
  return { ...current };
}

export function updateViewerSettings(patch: Partial<ViewerSettings>): ViewerSettings {
  const next = { ...getViewerSettings(), ...patch };
  next.lineWidthPct = clampLineWidthPct(next.lineWidthPct);
  next.sensitivityPct = Math.max(SENSITIVITY_MIN, Math.min(SENSITIVITY_MAX, Math.round(next.sensitivityPct)));
  next.cubeSizePx = Math.max(CUBE_MIN, Math.min(CUBE_MAX, Math.round(next.cubeSizePx)));
  next.fovDeg = Math.max(FOV_MIN, Math.min(FOV_MAX, Math.round(next.fovDeg)));
  current = next;
  setPref('toolpath_line_width_pct', String(next.lineWidthPct));
  setPref('sensitivity_pct', String(next.sensitivityPct));
  setPref('view_cube_size', String(next.cubeSizePx));
  setPref('fov_deg', String(next.fovDeg));
  for (const l of listeners) l({ ...next });
  return { ...next };
}

export function resetViewerSettings(): ViewerSettings {
  return updateViewerSettings({
    lineWidthPct: LINE_WIDTH_DEFAULT_PCT, sensitivityPct: SENSITIVITY_DEFAULT, cubeSizePx: CUBE_DEFAULT, fovDeg: FOV_DEFAULT,
  });
}

export function onViewerSettings(listener: (s: ViewerSettings) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
