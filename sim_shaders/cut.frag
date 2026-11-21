// cut.frag — GPU Z-map 절삭 패스: 칸 하나에서 이 선분이 소재를 얼마나 낮추는지 정확히 구한다.
//
// 칸 중심 c에서, 선분 위의 팁 위치 p(t) = a + t*(b - a) (t = 0..1)이 공구 반지름 r 안에 드는 구간에서
//     f(t) = z(t) + h(d(t)),   z(t) = az + t*(bz - az),   d(t) = |c - p(t)|
// 의 최솟값이 그 칸의 새 윗면 높이다(h = 팁 기준 공구 높이, 아래 profile_h).
// h는 d에 대해 볼록·증가이고 d(t)도 볼록이므로 f는 구간에서 볼록 — 황금분할 탐색이 정확하다.
// 양 끝(t = lo, hi)은 따로 정확히 재서 끝점 오차를 없앤다.
//
// 결과는 깊이 버퍼에 쓴다: gl_FragDepth = (높이 - zlo) / (ztop - zlo), 깊이 시험 LESS, 깊이를 1.0(= ztop)으로
// 지워 두면 칸마다 가장 낮은 값만 남는다. 색 버퍼에는 깊이 시험을 통과한 때만 공구 색 id가 써진다.
//
// 같은 식의 CPU 기준 구현: nc_sim_gpu_ref.py / tool_list_android/src/sim/zmapGpuRef.ts.
// 상수(GOLD_ITER, INV_PHI, R2_EPS, VERTICAL_LEN2)와 profile_h 식은 기준 구현과 항상 같아야 한다
// (tests/test_nc_sim_gpu_ref.py가 이 파일의 상수 줄을 읽어 맞춰 본다).

flat in vec4 v_seg_xy;
flat in vec4 v_seg_z;
flat in vec4 v_prof;

uniform float u_res;   // 칸 간격 (mm)
uniform vec2 u_z;      // (zlo, ztop)

layout(location = 0) out float o_color;

const int GOLD_ITER = 24;
const float INV_PHI = 0.6180339887498949;
const float R2_EPS = 1e-9;
// float32에서는 r² 근처의 간격이 1e-6쯤이라 R2_EPS(1e-9)만으로는 "칸 중심이 정확히 반지름 위"인 줄(격자와 공구
// 반지름이 맞아떨어지면 흔하다)이 좌표 반올림 오차로 빠진다. CPU 엔진은 이 칸을 깎으므로 상대 여유를 더한다.
const float R2_REL_EPS = 1e-5;
const float VERTICAL_LEN2 = 1e-18;   // 수평 이동이 이보다 짧으면 수직 이동(낮은 끝점만 본다)

// 팁 기준 공구 높이. 종류 번호는 nc_sim.PROFILE_* 와 같다.
float profile_h(float d, vec4 p) {
    int kind = int(p.x + 0.5);
    if (kind == 1) {                      // 코너 R: a = 평평한 반경, b = 코너 R
        float dr = clamp(d - p.y, 0.0, p.z);
        return d > p.y ? p.z - sqrt(max(p.z * p.z - dr * dr, 0.0)) : 0.0;
    }
    if (kind == 2) {                      // 원뿔: a = 기울기
        return d * p.y;
    }
    if (kind == 3) {                      // 챔퍼: a = 평평한 반경
        return max(d - p.y, 0.0);
    }
    return 0.0;                           // 0 평바닥
}

float sweep_f(float t, vec2 q, vec2 dv, float az, float dz, vec4 prof) {
    vec2 w = q - t * dv;
    return az + dz * t + profile_h(sqrt(dot(w, w)), prof);
}

void main() {
    vec2 a = v_seg_xy.xy;
    vec2 dv = v_seg_xy.zw - v_seg_xy.xy;
    float az = v_seg_z.x;
    float dz = v_seg_z.y - v_seg_z.x;
    float radius = v_seg_z.w;

    vec2 c = floor(gl_FragCoord.xy) * u_res;   // 칸 중심(격자 원점 기준)
    vec2 q = c - a;
    float r2 = radius * radius * (1.0 + R2_REL_EPS) + R2_EPS;
    float len2 = dot(dv, dv);
    float qq = dot(q, q);

    float lo = 0.0;
    float hi = 1.0;
    if (len2 < VERTICAL_LEN2) {
        if (qq > r2) discard;
    } else {
        float qd = dot(q, dv);
        float disc = qd * qd - len2 * (qq - r2);
        if (disc < 0.0) discard;
        float sq = sqrt(disc);
        lo = max((qd - sq) / len2, 0.0);
        hi = min((qd + sq) / len2, 1.0);
        if (lo > hi) discard;
    }

    float best = min(sweep_f(lo, q, dv, az, dz, v_prof), sweep_f(hi, q, dv, az, dz, v_prof));

    // 황금분할 탐색(수평 이동이 있을 때만 — 수직 이동은 선형이라 끝점이 답이다)
    if (len2 >= VERTICAL_LEN2) {
        float ta = lo;
        float tb = hi;
        float tc = tb - (tb - ta) * INV_PHI;
        float td = ta + (tb - ta) * INV_PHI;
        float fc = sweep_f(tc, q, dv, az, dz, v_prof);
        float fd = sweep_f(td, q, dv, az, dz, v_prof);
        best = min(best, min(fc, fd));
        for (int k = 0; k < GOLD_ITER; k++) {
            if (fc < fd) {
                tb = td;
                td = tc;
                fd = fc;
                tc = tb - (tb - ta) * INV_PHI;
                fc = sweep_f(tc, q, dv, az, dz, v_prof);
                best = min(best, fc);
            } else {
                ta = tc;
                tc = td;
                fc = fd;
                td = ta + (tb - ta) * INV_PHI;
                fd = sweep_f(td, q, dv, az, dz, v_prof);
                best = min(best, fd);
            }
        }
    }

    float zlo = u_z.x;
    float ztop = u_z.y;
    if (best >= ztop) discard;                 // 소재 윗면 위 — 깎을 것이 없다
    best = max(best, zlo);                     // 바닥 아래로는 깎지 않는다
    gl_FragDepth = (best - zlo) / (ztop - zlo);
    o_color = v_seg_z.z;
}
