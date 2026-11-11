// WASM 절삭 핵심 루프(AssemblyScript, assembly/) 불러오기. 없으면(지원 안 함·메모리 부족) 각 소재가 JS 로 계산한다.
import { SIM_KERNELS_B64 } from './simKernels';

export interface KernelExports {
  stamp(
    occ: number, col: number, nx: number, ny: number, nz: number, x0: number, y0: number, z0: number, rx: number, ry: number, rz: number,
    ax: number, ay: number, az: number, bx: number, by: number, bz: number, ux: number, uy: number, uz: number,
    lut: number, lutLen: number, radius: number, invStep: number, length: number, color: number,
  ): number;
  zstamp(
    h: number, c: number, nx: number, ny: number, x0: number, y0: number, res: number,
    ax: number, ay: number, bx: number, by: number, z: number,
    lut: number, lutLen: number, radius: number, invStep: number, color: number, zlo32: number,
  ): number;
}

/** 소재 하나가 쓰는 WASM 메모리: [자료 dataBytes][lut 작업 공간] */
export interface Kernel {
  buffer: ArrayBuffer;
  ex: KernelExports;
  lutOff: number;
  lutCap: number;
  /** 마지막으로 lut 작업 공간에 복사한 표(같은 표면 다시 복사하지 않는다) */
  lastLut: Float64Array | null;
}

const LUT_CAP = 131072; // 8바이트 × 131072 = 1MB
let compiled: WebAssembly.Module | null = null;
let started: Promise<boolean> | null = null;

/** 앱 시작 때 한 번 컴파일한다(비동기). 끝나기 전에 만든 소재는 JS 로 계산한다. */
export function initSimWasm(): Promise<boolean> {
  if (!started) {
    started = (async () => {
      try {
        if (typeof WebAssembly === 'undefined') return false;
        const bin = atob(SIM_KERNELS_B64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        compiled = await WebAssembly.compile(bytes);
        return true;
      } catch {
        compiled = null;
        return false;
      }
    })();
  }
  return started;
}

export const simWasmReady = (): boolean => compiled !== null;
let disabled = false;
/** 시험·진단용: true 면 JS 로만 계산한다 */
export function setSimWasmDisabled(v: boolean): void { disabled = v; }

export function allocKernel(dataBytes: number): Kernel | null {
  if (!compiled || disabled) return null;
  try {
    const lutOff = Math.ceil(dataBytes / 8) * 8;
    const pages = Math.ceil((lutOff + LUT_CAP * 8) / 65536) + 1;
    const memory = new WebAssembly.Memory({ initial: pages });
    const inst = new WebAssembly.Instance(compiled, { env: { memory } });
    return { buffer: memory.buffer, ex: inst.exports as unknown as KernelExports, lutOff, lutCap: LUT_CAP, lastLut: null };
  } catch {
    return null; // 메모리를 못 얻으면 JS 로
  }
}

/** lut 를 작업 공간에 올린다. 너무 길면 false(JS 로 계산) */
export function loadLut(k: Kernel, lut: Float64Array): boolean {
  if (lut.length > k.lutCap) return false;
  if (k.lastLut !== lut) {
    new Float64Array(k.buffer, k.lutOff, lut.length).set(lut);
    k.lastLut = lut;
  }
  return true;
}
