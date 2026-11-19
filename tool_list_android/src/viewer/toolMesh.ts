// 공구 모양(회전체) — 원본 nc_tool_marker.build_tool_mesh. 팁이 원점, 몸통은 +Z 방향.
import * as THREE from 'three';
import type { ToolShape } from '../sim/toolShape';

const SEGMENTS = 28;
const PROFILE_STEPS = 8;
/** 날 길이가 아주 긴(무제한 포함) 공구는 지름의 이 배수까지만 그린다 */
const MAX_BODY_DIAMETERS = 8;

/** (반경, 팁에서의 높이) 점 목록 — 중심에서 시작해 날끝 둘레를 지나 몸통 윗면까지 */
export function toolProfile(shape: ToolShape): [number, number][] {
  const radius = shape.radius;
  const { lut, invStep } = shape.radialLut(radius / PROFILE_STEPS);
  const pts: [number, number][] = [];
  let lastH = 0;
  for (let i = 0; i <= PROFILE_STEPS; i++) {
    const r = (radius * i) / PROFILE_STEPS;
    const h = lut[Math.min(Math.round(r * invStep), lut.length - 1)] ?? 0;
    pts.push([r, h]);
    lastH = h;
  }
  let top = Math.max(shape.cutLength, radius * 2);
  top = Math.min(top, radius * 2 * MAX_BODY_DIAMETERS);
  top = Math.max(top, lastH + radius * 0.5);
  pts.push([radius, top], [0, top]);
  return pts;
}

export function buildToolGeometry(shape: ToolShape): THREE.BufferGeometry {
  const prof = toolProfile(shape);
  const pos = new Float32Array(prof.length * SEGMENTS * 3);
  prof.forEach(([r, h], i) => {
    for (let k = 0; k < SEGMENTS; k++) {
      const a = (k / SEGMENTS) * Math.PI * 2;
      const o = (i * SEGMENTS + k) * 3;
      pos[o] = Math.cos(a) * r; pos[o + 1] = Math.sin(a) * r; pos[o + 2] = h;
    }
  });
  const idx: number[] = [];
  for (let i = 0; i < prof.length - 1; i++) {
    for (let k = 0; k < SEGMENTS; k++) {
      const k2 = (k + 1) % SEGMENTS;
      const a = i * SEGMENTS + k, b = i * SEGMENTS + k2, c = (i + 1) * SEGMENTS + k, d = (i + 1) * SEGMENTS + k2;
      idx.push(a, b, c, b, d, c);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}
