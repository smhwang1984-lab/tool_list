// WebGL 을 쓸 수 없을 때의 대체 화면 — 툴패스를 XY 평면(선반은 Z-X)으로 2D 캔버스에 그린다.
import type { ToolpathResult } from '../core/toolpath';
import { cssColor, RAPID_MOVE_COLOR, segmentBuckets, toolColorForIndex } from './segments';

export interface Fallback2D {
  draw(res: ToolpathResult | null, lathe: boolean): void;
}

export function createFallback2D(host: HTMLElement, message: string): Fallback2D {
  host.innerHTML = '';
  const note = document.createElement('div');
  note.style.cssText = 'position:absolute;left:8px;top:8px;right:8px;color:#c7d0e0;font-size:12px;z-index:1;pointer-events:none';
  note.textContent = `3D 화면(WebGL)을 쓸 수 없어 2D 평면 보기로 표시합니다. (${message})`;
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'width:100%;height:100%;display:block;background:#11151c';
  host.style.position = 'relative';
  host.append(canvas, note);
  let last: { res: ToolpathResult | null; lathe: boolean } = { res: null, lathe: false };

  const render = (): void => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(host.clientWidth, 1), h = Math.max(host.clientHeight, 1);
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const g = canvas.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = '#11151c'; g.fillRect(0, 0, w, h);
    const { res, lathe } = last;
    if (!res) return;
    // 선반 점은 [z, y, x/2]: 가로 = Z, 세로 = 지름 방향(반경). 밀링은 가로 = X, 세로 = Y.
    const ax = lathe ? 0 : 0, ay = lathe ? 2 : 1;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    const groups: { color: string; cut: number[]; rapid: number[] }[] = [];
    let i = 0;
    for (const path of res.tool_paths.values()) {
      const b = segmentBuckets(path);
      groups.push({ color: cssColor(toolColorForIndex(i++)), cut: b.cut, rapid: b.rapid });
      for (const arr of [b.cut, b.rapid]) {
        for (let k = 0; k < arr.length; k += 3) {
          const x = arr[k + ax]!, y = arr[k + ay]!;
          if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
        }
      }
    }
    if (!Number.isFinite(minX)) return;
    const pad = 24;
    const sx = (w - pad * 2) / Math.max(maxX - minX, 1e-6), sy = (h - pad * 2) / Math.max(maxY - minY, 1e-6);
    const s = Math.min(sx, sy);
    const ox = (w - (maxX - minX) * s) / 2, oy = (h + (maxY - minY) * s) / 2;
    const px = (x: number): number => ox + (x - minX) * s;
    const py = (y: number): number => oy - (y - minY) * s;
    const stroke = (arr: number[], color: string): void => {
      g.strokeStyle = color; g.beginPath();
      for (let k = 0; k < arr.length; k += 6) {
        g.moveTo(px(arr[k + ax]!), py(arr[k + ay]!));
        g.lineTo(px(arr[k + 3 + ax]!), py(arr[k + 3 + ay]!));
      }
      g.stroke();
    };
    g.lineWidth = 1;
    for (const grp of groups) stroke(grp.rapid, cssColor(RAPID_MOVE_COLOR));
    g.lineWidth = 1.4;
    for (const grp of groups) stroke(grp.cut, grp.color);
  };
  window.addEventListener('resize', render);
  return { draw(res, lathe) { last = { res, lathe }; render(); } };
}
