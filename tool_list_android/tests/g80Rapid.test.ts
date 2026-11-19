import { afterEach, describe, expect, it } from 'vitest';
import { setLatheG80Rapid, toolpathFromText } from '../src/core/toolpath';

const NC = ['N1 T0101', 'G50 S2000', 'G96 S150 M03', 'G0 X50. Z5.', 'G1 Z-10. F0.2', 'G80 X60. Z5.', 'G0 X70.'].join('\n');
const lastType = (): string | undefined => {
  const r = toolpathFromText(NC, 'CNC 선반 (턴밀 포함)');
  const nodes = [...r.tool_paths.values()].flat().filter((n) => n.src_line === 5);
  return nodes[nodes.length - 1]?.type;
};

describe('선반 G80 이동', () => {
  afterEach(() => setLatheG80Rapid(false));
  it('옵션이 켜지면 G80 줄의 이동은 급속(G00)', () => {
    setLatheG80Rapid(true);
    expect(lastType()).toBe('G00');
  });
  it('끄면 원본처럼 G80', () => {
    setLatheG80Rapid(false);
    expect(lastType()).toBe('G80');
  });
});
