// 원본 ui_icons.py(v2.2.8)의 도형을 SVG로 옮긴 것. 좌표는 원본과 같은 0~1 정규화 값을 100배 했다.
// 선 굵기 0.085 → 8.5, 둥근 끝/이음. 채움(fill) 도형은 class="f".

type Pt = [number, number];

const s = (v: number) => +(v * 100).toFixed(2);
const pts = (p: Pt[]) => p.map(([x, y]) => `${s(x)},${s(y)}`).join(' ');
const poly = (...p: Pt[]) => `<polygon points="${pts(p)}"/>`;
const pline = (...p: Pt[]) => `<polyline points="${pts(p)}"/>`;
const line = (x1: number, y1: number, x2: number, y2: number, w?: number) =>
  `<line x1="${s(x1)}" y1="${s(y1)}" x2="${s(x2)}" y2="${s(y2)}"${w ? ` stroke-width="${w * 100}"` : ''}/>`;
const rect = (x: number, y: number, w: number, h: number, r = 0) =>
  `<rect x="${s(x)}" y="${s(y)}" width="${s(w)}" height="${s(h)}" rx="${s(r)}"/>`;
const circle = (cx: number, cy: number, r: number, fill = false) =>
  `<circle cx="${s(cx)}" cy="${s(cy)}" r="${s(r)}"${fill ? ' class="f"' : ''}/>`;

function gear(): string {
  const p: Pt[] = [];
  const teeth = 8;
  for (let i = 0; i < teeth * 2; i++) {
    const angle = ((i * 180) / teeth - 90) * (Math.PI / 180);
    const radius = i % 2 === 0 ? 0.44 : 0.33;
    for (const offset of [-6, 6]) {
      const a = angle + offset * (Math.PI / 180);
      p.push([0.5 + radius * Math.cos(a), 0.5 + radius * Math.sin(a)]);
    }
  }
  return poly(...p) + circle(0.5, 0.5, 0.13);
}

const SHAPES: Record<string, () => string> = {
  folder_open: () =>
    pline([0.08, 0.82], [0.08, 0.22], [0.36, 0.22], [0.44, 0.3], [0.8, 0.3], [0.8, 0.42]) +
    poly([0.08, 0.82], [0.22, 0.44], [0.96, 0.44], [0.82, 0.82]),
  folder_add: () =>
    pline([0.7, 0.82], [0.06, 0.82], [0.06, 0.24], [0.34, 0.24], [0.42, 0.32], [0.84, 0.32], [0.84, 0.48]) +
    line(0.8, 0.56, 0.8, 0.96, 0.1) + line(0.6, 0.76, 1.0, 0.76, 0.1),
  document: () =>
    poly([0.22, 0.08], [0.6, 0.08], [0.8, 0.28], [0.8, 0.92], [0.22, 0.92]) +
    pline([0.6, 0.08], [0.6, 0.28], [0.8, 0.28]) +
    [0.46, 0.6, 0.74].map((y) => line(0.34, y, 0.68, y)).join(''),
  eraser: () =>
    poly([0.12, 0.62], [0.5, 0.24], [0.86, 0.6], [0.58, 0.88], [0.38, 0.88]) +
    line(0.3, 0.44, 0.68, 0.82) + line(0.38, 0.88, 0.92, 0.88),
  pencil: () =>
    poly([0.16, 0.84], [0.2, 0.64], [0.66, 0.18], [0.82, 0.34], [0.36, 0.8]) +
    line(0.58, 0.26, 0.74, 0.42) + line(0.2, 0.64, 0.36, 0.8),
  save: () =>
    poly([0.12, 0.12], [0.74, 0.12], [0.88, 0.26], [0.88, 0.88], [0.12, 0.88]) +
    rect(0.28, 0.12, 0.4, 0.24) + rect(0.26, 0.54, 0.48, 0.34),
  key: () =>
    circle(0.3, 0.5, 0.17) + line(0.47, 0.5, 0.9, 0.5) + line(0.76, 0.5, 0.76, 0.66) + line(0.88, 0.5, 0.88, 0.62),
  run: () =>
    rect(0.08, 0.14, 0.62, 0.56, 0.04) + line(0.08, 0.32, 0.7, 0.32) + line(0.08, 0.5, 0.7, 0.5) +
    line(0.3, 0.14, 0.3, 0.7) + `<polygon class="f" points="${pts([[0.58, 0.54], [0.58, 0.96], [0.96, 0.75]])}"/>`,
  table: () =>
    rect(0.1, 0.16, 0.8, 0.68, 0.05) + line(0.1, 0.36, 0.9, 0.36) + line(0.1, 0.6, 0.9, 0.6) +
    line(0.36, 0.16, 0.36, 0.84),
  toolpath: () =>
    pline([0.1, 0.8], [0.1, 0.22], [0.36, 0.22], [0.36, 0.66], [0.62, 0.66], [0.62, 0.22], [0.86, 0.22]) +
    circle(0.86, 0.22, 0.09, true) + circle(0.1, 0.8, 0.07, true),
  gear,
  help: () =>
    circle(0.5, 0.5, 0.4) +
    '<text x="50" y="52" text-anchor="middle" dominant-baseline="central" font-size="56" font-weight="700" class="t">?</text>',
  // 다크모드 버튼(원본은 글자 버튼) — 터치 화면에서 잘 보이도록 아이콘으로 그린다.
  moon: () => '<path d="M70 62 A30 30 0 1 1 42 20 A24 24 0 0 0 70 62 Z"/>',
  sun: () =>
    circle(0.5, 0.5, 0.18) +
    Array.from({ length: 8 }, (_, i) => {
      const a = (i * Math.PI) / 4;
      return line(0.5 + 0.3 * Math.cos(a), 0.5 + 0.3 * Math.sin(a), 0.5 + 0.42 * Math.cos(a), 0.5 + 0.42 * Math.sin(a));
    }).join(''),
  info: () => circle(0.5, 0.5, 0.4) + line(0.5, 0.46, 0.5, 0.72, 0.11) + circle(0.5, 0.31, 0.06, true),
  // 3D 뷰어 겹침 버튼 — 글자 기호(📍 ▶ ⏭)가 기기마다 이모지로 바뀌어 선 아이콘으로 그린다.
  pin: () => circle(0.5, 0.5, 0.26) + circle(0.5, 0.5, 0.06, true) +
    line(0.5, 0.06, 0.5, 0.22) + line(0.5, 0.78, 0.5, 0.94) + line(0.06, 0.5, 0.22, 0.5) + line(0.78, 0.5, 0.94, 0.5),
  // 상단바 숨김/펼침 화살표
  chevron_up: () => pline([0.2, 0.64], [0.5, 0.34], [0.8, 0.64]),
  chevron_down: () => pline([0.2, 0.36], [0.5, 0.66], [0.8, 0.36]),
  // v2.0.9: 모달 정보 · 프로그램 창 접기 탭
  chevron_left: () => pline([0.64, 0.2], [0.34, 0.5], [0.64, 0.8]),
  chevron_right: () => pline([0.36, 0.2], [0.66, 0.5], [0.36, 0.8]),
  play: () => poly([0.3, 0.18], [0.3, 0.82], [0.82, 0.5]),
  pause: () => line(0.34, 0.2, 0.34, 0.8) + line(0.66, 0.2, 0.66, 0.8),
  prev: () => line(0.2, 0.2, 0.2, 0.8) + poly([0.8, 0.2], [0.8, 0.8], [0.34, 0.5]),
  next: () => line(0.8, 0.2, 0.8, 0.8) + poly([0.2, 0.2], [0.2, 0.8], [0.66, 0.5]),
  rewind: () => '<path d="M24 50 A28 28 0 1 0 34 28"/>' + pline([0.2, 0.18], [0.34, 0.28], [0.22, 0.42]),
};

/** 아이콘 SVG 문자열. 색은 CSS(stroke: currentColor 계열)로 정한다. */
export function icon(name: string): string {
  const body = SHAPES[name]?.() ?? '';
  return (
    `<svg viewBox="0 0 100 100" fill="none" stroke-width="8.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
    `<style>.f{fill:currentColor;stroke:none}.t{fill:currentColor;stroke:none;font-family:sans-serif}</style>` +
    body +
    '</svg>'
  );
}
