// 소재 상태 올리기: 칸마다 높이 텍스처의 값을 깊이로, 색 id 텍스처의 값을 색 첨부로 쓴다(깊이 시험 항상 통과).
// 깊이 정규화는 cut.frag와 같다: (h - zlo) / (ztop - zlo).
uniform sampler2D u_height;   // R32F, 칸마다 높이(mm)
uniform sampler2D u_cid;      // R32F, 칸마다 색 id(안 깎임 = -1)
uniform vec2 u_z;             // (zlo, ztop)

layout(location = 0) out float o_color;

void main() {
    ivec2 cell = ivec2(gl_FragCoord.xy);
    float h = texelFetch(u_height, cell, 0).r;
    gl_FragDepth = clamp((h - u_z.x) / (u_z.y - u_z.x), 0.0, 1.0);
    o_color = texelFetch(u_cid, cell, 0).r;
}
