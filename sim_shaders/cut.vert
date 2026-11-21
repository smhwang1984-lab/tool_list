// cut.vert — GPU Z-map 절삭 패스: 선분 하나 = 인스턴스 하나, 선분이 닿는 칸 범위를 덮는 사각형 하나.
//
// 이 파일에는 #version / precision 줄이 없다. 로더가 앞에 붙인다.
//   데스크톱(ModernGL, OpenGL 3.3): "#version 330 core\n"
//   안드로이드(WebGL2 / three.js) : "#version 300 es\nprecision highp float;\nprecision highp int;\n"
// 두 앱이 같은 파일을 쓴다 — 한쪽만 고치지 않는다(CLAUDE.md 4절). 같은 식의 CPU 기준 구현:
//   nc_sim_gpu_ref.py / tool_list_android/src/sim/zmapGpuRef.ts
//
// 소재 격자 한 칸 = 렌더 대상 화소 하나. 화소 (i, j)의 칸 중심은 격자 원점에서 (i*res, j*res)다.
// 선분 좌표는 격자 원점(x0, y0)을 뺀 값으로 받는다(float32 정밀도 — CPU에서 float64로 뺀다).
//
// 인스턴스 속성
//   a_seg_xy : (ax, ay, bx, by)       선분 시작·끝의 수평 좌표(격자 원점 기준, mm)
//   a_seg_z  : (az, bz, color, radius) 시작·끝 팁 높이, 절삭면 색 id, 공구 반지름
//   a_prof   : (kind, a, b, c)        공구 형상 매개변수(nc_sim.ToolShape.profile_params)

in vec4 a_seg_xy;
in vec4 a_seg_z;
in vec4 a_prof;

uniform vec2 u_size;   // 격자 칸 수 (nx, ny)
uniform float u_res;   // 칸 간격 (mm)

flat out vec4 v_seg_xy;
flat out vec4 v_seg_z;
flat out vec4 v_prof;

void main() {
    v_seg_xy = a_seg_xy;
    v_seg_z = a_seg_z;
    v_prof = a_prof;

    // CPU 엔진(nc_sim._stamp_numpy)과 같은 칸 범위: 선분 상자를 반지름만큼 넓혀 [floor, ceil]
    float r = a_seg_z.w;
    vec2 lo = min(a_seg_xy.xy, a_seg_xy.zw) - r;
    vec2 hi = max(a_seg_xy.xy, a_seg_xy.zw) + r;
    vec2 i0 = max(floor(lo / u_res), 0.0);
    vec2 i1 = min(ceil(hi / u_res), u_size - 1.0) + 1.0;   // 마지막 칸의 오른쪽 가장자리

    // 격자 밖이면 넓이 0짜리 사각형(화소가 생기지 않는다)
    bool empty = (i0.x >= i1.x) || (i0.y >= i1.y);
    vec2 corner = vec2(float(gl_VertexID & 1), float((gl_VertexID >> 1) & 1));
    vec2 pix = empty ? i0 : mix(i0, i1, corner);
    gl_Position = vec4(pix / u_size * 2.0 - 1.0, 0.0, 1.0);
}
