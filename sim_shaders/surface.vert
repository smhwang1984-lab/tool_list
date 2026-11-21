// 소재 윗면·옆면 그리기 (v2.8.0, G3): 높이 텍스처를 정점 셰이더에서 직접 읽는다. 정점 버퍼 없음.
//   윗면: u_side < 0. 행 하나 = 인스턴스 하나(TRIANGLE_STRIP, 정점 2*nx개). 정점 v → 열 v>>1, 행 인스턴스+(v&1).
//   옆면: u_side 0..3(앞·뒤·왼·오른쪽 테두리). 정점 v → 테두리 따라 v>>1번째, 짝수 = 윗면 높이, 홀수 = 바닥.
uniform sampler2D u_height;   // R32F (nx, ny) 칸마다 높이
uniform sampler2D u_xs;       // R32F (nx, 1) 열 좌표
uniform sampler2D u_ys;       // R32F (ny, 1) 행 좌표
uniform mat4 u_mvp;
uniform ivec2 u_n;            // (nx, ny)
uniform float u_zlo;
uniform int u_side;

out vec2 v_grid;              // 격자 좌표(열, 행) — 칸 번호는 floor
out float v_z;

void main() {
    int i = gl_VertexID >> 1;
    int odd = gl_VertexID & 1;
    ivec2 c;
    float z;
    if (u_side < 0) {
        c = ivec2(i, gl_InstanceID + odd);
        z = texelFetch(u_height, c, 0).r;
    } else {
        if (u_side == 0) c = ivec2(i, 0);
        else if (u_side == 1) c = ivec2(i, u_n.y - 1);
        else if (u_side == 2) c = ivec2(0, i);
        else c = ivec2(u_n.x - 1, i);
        z = (odd == 0) ? texelFetch(u_height, c, 0).r : u_zlo;
    }
    float x = texelFetch(u_xs, ivec2(c.x, 0), 0).r;
    float y = texelFetch(u_ys, ivec2(c.y, 0), 0).r;
    v_grid = vec2(c);
    v_z = z;
    gl_Position = u_mvp * vec4(x, y, z, 1.0);
}
