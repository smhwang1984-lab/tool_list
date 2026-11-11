// Web Worker 진입점 — 메시지를 SimEngine 에 넘기고 결과를 돌려 준다
import { SimEngine, type InMsg } from './simEngine';

const ctx = self as unknown as { postMessage(m: unknown, t?: Transferable[]): void; onmessage: ((e: MessageEvent<InMsg>) => void) | null };
const engine = new SimEngine((m, transfer) => ctx.postMessage(m, transfer ?? []));
ctx.onmessage = (e) => engine.handle(e.data);
