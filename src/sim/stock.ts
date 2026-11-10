// 소재 배치 — 원본 nc_sim.py parse_stock_size_comment / StockSpec / auto_resolution
export type Axis = 'X' | 'Y' | 'Z';
export type DimKey = 'T' | 'W' | 'L';
export const AXES: readonly Axis[] = ['X', 'Y', 'Z'];
export const DIM_KEYS: readonly DimKey[] = ['T', 'W', 'L'];
export type Bounds = Record<Axis, [number, number]>;

const STOCK_SIZE_RE = /^\(\s*STOCK\s*SIZE([^)]*)\)/i;
const KEYED_RE = /([TWL])\s*=?\s*(\d+(?:\.\d*)?|\.\d+)/gi;
const NUMBER_RE = /\d+(?:\.\d*)?|\.\d+/g;
const HEADER_MAX_LINES = 200;
const BODY_RE = /^(?:N\d+\s*)?(?:M0?6|T\d+|G0?[0-3].*[XYZ]\s*-?[\d.])/i;

/** 프로그램 상단 주석 `(STOCK SIZE : T50 W95 L385)` 에서 소재 치수를 읽는다. */
export function parseStockSizeComment(lines: readonly string[]): Record<DimKey, number> | null {
  for (let i = 0; i < lines.length && i < HEADER_MAX_LINES; i++) {
    const text = lines[i]!.trim();
    if (text.startsWith('(')) {
      const m = STOCK_SIZE_RE.exec(text);
      if (m) {
        const body = m[1]!;
        const keyed: Record<string, string> = {};
        for (const k of body.matchAll(KEYED_RE)) keyed[k[1]!.toUpperCase()] = k[2]!;
        let values: Record<DimKey, number>;
        if (keyed.T !== undefined && keyed.W !== undefined && keyed.L !== undefined) {
          values = { T: parseFloat(keyed.T), W: parseFloat(keyed.W), L: parseFloat(keyed.L) };
        } else {
          const numbers = body.match(NUMBER_RE) ?? [];
          if (numbers.length < 3) return null;
          values = { T: parseFloat(numbers[0]!), W: parseFloat(numbers[1]!), L: parseFloat(numbers[2]!) };
        }
        return values.T > 0 && values.W > 0 && values.L > 0 ? values : null;
      }
    } else if (BODY_RE.test(text)) break;
  }
  return null;
}

export type Reference = 'center' | 'neg' | 'pos' | 'top' | 'bottom';

export class StockSpec {
  readonly dims: Record<DimKey, number>;
  readonly axisOf: Record<DimKey, Axis>;
  readonly reference: Record<Axis, Reference>;
  readonly offset: Record<Axis, number>;

  constructor(
    dims: Record<DimKey, number>, axisOf: Record<DimKey, Axis>,
    reference: Partial<Record<Axis, Reference>> = {}, offset: Partial<Record<Axis, number>> = {},
  ) {
    this.dims = { ...dims };
    this.axisOf = { ...axisOf };
    if (Object.values(axisOf).sort().join() !== 'X,Y,Z') throw new Error('T/W/L 은 X/Y/Z 에 하나씩 배정해야 합니다');
    this.reference = { X: 'center', Y: 'center', Z: 'top', ...reference };
    this.offset = { X: 0, Y: 0, Z: 0, ...offset };
  }

  lengthOf(axis: Axis): number {
    for (const key of DIM_KEYS) if (this.axisOf[key] === axis) return this.dims[key] ?? 0;
    return 0;
  }

  bounds(): Bounds {
    const out = {} as Bounds;
    for (const axis of AXES) {
      const length = Math.max(this.lengthOf(axis), 0);
      const ref = this.reference[axis];
      let lo: number, hi: number;
      if (ref === 'neg' || ref === 'bottom') [lo, hi] = [0, length];
      else if (ref === 'pos' || ref === 'top') [lo, hi] = [-length, 0];
      else [lo, hi] = [-length / 2, length / 2];
      out[axis] = [lo + this.offset[axis], hi + this.offset[axis]];
    }
    return out;
  }
}

/** 소재 XY 면적이 대략 targetCells 격자가 되도록 해상도(mm)를 고른다(0.05~0.5). */
export function autoResolution(bounds: Bounds, targetCells = 1_000_000, safeMode = false): number {
  const area = Math.max(bounds.X[1] - bounds.X[0], 1e-6) * Math.max(bounds.Y[1] - bounds.Y[0], 1e-6);
  const target = safeMode ? Math.max(Math.floor(targetCells / 4), 1) : targetCells;
  const res = Math.min(Math.max(Math.sqrt(area / Math.max(target, 1)), 0.05), 0.5);
  return Math.round(res * 1000) / 1000;
}
