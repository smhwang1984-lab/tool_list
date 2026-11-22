// 깎은 결과(깊이 + 색 id)를 표시용 높이·색 텍스처로 바꾼다 (v2.8.1, G4 안드로이드). fill.vert(화면 전체 사각형)와 함께 쓴다.
// 깊이 → 높이: h = zlo + depth * (ztop - zlo) (cut.frag·fill.frag의 정규화와 역).
// u_block > 1이면 표시 격자를 줄인다: 블록마다 가장 낮은 칸의 높이·색을 쓴다(좁은 홈이 사라지지 않게 — nc_sim.display_grid와 같은 생각).
uniform sampler2D u_depth;    // 깊이 텍스처(절삭 렌더 대상)
uniform sampler2D u_cid;      // R32F 색 id(안 깎임 = -1)
uniform vec2 u_z;             // (zlo, ztop)
uniform ivec2 u_n;            // 계산 격자 칸 수 (nx, ny)
uniform ivec2 u_block;        // 표시 칸 하나가 덮는 계산 칸 수 (bx, by)
uniform ivec2 u_origin;       // 렌더 대상 왼쪽 아래가 가리키는 표시 칸 번호(띠로 나눠 읽을 때)

layout(location = 0) out float o_h;
layout(location = 1) out float o_c;

void main() {
    ivec2 base = (ivec2(gl_FragCoord.xy) + u_origin) * u_block;
    float best = 1e30;
    float bestc = -1.0;
    for (int j = 0; j < u_block.y; j++) {
        for (int i = 0; i < u_block.x; i++) {
            ivec2 c = base + ivec2(i, j);
            if (c.x >= u_n.x || c.y >= u_n.y) continue;
            float h = u_z.x + texelFetch(u_depth, c, 0).r * (u_z.y - u_z.x);
            if (h < best) {
                best = h;
                bestc = texelFetch(u_cid, c, 0).r;
            }
        }
    }
    o_h = best;
    o_c = bestc;
}
