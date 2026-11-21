// 소재 윗면·옆면 색 (v2.8.0, G3): 칸 단위 색(공구 색 / 깎인 깊이 / 단색)과 칸 단위 법선 음영.
uniform sampler2D u_height;
uniform sampler2D u_xs;
uniform sampler2D u_ys;
uniform sampler2D u_cid;      // R32F (nx, ny) 색 id (안 깎임 = -1)
uniform sampler2D u_palette;  // RGBA32F (K, 1) 색 id → 색
uniform mat4 u_mv;
uniform ivec2 u_n;
uniform vec4 u_default;       // 안 깎인 소재·옆면 기본색
uniform vec3 u_stops[3];      // 깎인 깊이 색 3단
uniform vec2 u_depth;         // (ztop, zlo)
uniform int u_mode;           // 0 공구 색, 1 깎인 깊이, 2 단색
uniform int u_side;
uniform int u_palette_n;

in vec2 v_grid;
in float v_z;
out vec4 o_rgba;

const vec3 LIGHT = vec3(0.3162, 0.4743, 0.8221);   // 보는 쪽 기준 방향광(정규화됨)

void main() {
    if (u_side >= 0) {
        o_rgba = vec4(u_default.rgb * 0.62, 1.0);
        return;
    }
    ivec2 cell = clamp(ivec2(floor(v_grid)), ivec2(0), u_n - 2);
    float h00 = texelFetch(u_height, cell, 0).r;
    float h10 = texelFetch(u_height, cell + ivec2(1, 0), 0).r;
    float h01 = texelFetch(u_height, cell + ivec2(0, 1), 0).r;
    float h11 = texelFetch(u_height, cell + ivec2(1, 1), 0).r;
    float x0 = texelFetch(u_xs, ivec2(cell.x, 0), 0).r;
    float x1 = texelFetch(u_xs, ivec2(cell.x + 1, 0), 0).r;
    float y0 = texelFetch(u_ys, ivec2(cell.y, 0), 0).r;
    float y1 = texelFetch(u_ys, ivec2(cell.y + 1, 0), 0).r;
    float dzdx = (h10 + h11 - h00 - h01) / (2.0 * max(x1 - x0, 1e-6));
    float dzdy = (h01 + h11 - h00 - h10) / (2.0 * max(y1 - y0, 1e-6));
    vec3 n = normalize(vec3(-dzdx, -dzdy, 1.0));
    vec3 nv = normalize(mat3(u_mv) * n);
    float shade = 0.50 + 0.50 * max(dot(nv, LIGHT), 0.0);

    vec3 base = u_default.rgb;
    if (u_mode == 0) {
        int cid = int(floor(texelFetch(u_cid, cell, 0).r + 0.5));
        if (cid >= 0 && u_palette_n > 0)
            base = texelFetch(u_palette, ivec2(min(cid, u_palette_n - 1), 0), 0).rgb;
    } else if (u_mode == 1) {
        float t = clamp((u_depth.x - h00) / max(u_depth.x - u_depth.y, 1e-9), 0.0, 1.0);
        float pos = t * 2.0;
        int lo = int(min(floor(pos), 1.0));
        base = mix(u_stops[lo], u_stops[lo + 1], pos - float(lo));
    }
    o_rgba = vec4(base * shade, 1.0);
}
