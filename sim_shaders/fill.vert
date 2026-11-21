// 화면 전체를 덮는 사각형 — 이미 깎인 소재 상태(높이·색 id)를 렌더 대상에 다시 올릴 때 쓴다.
// 정점 버퍼 없이 gl_VertexID 0..3 (TRIANGLE_STRIP).
void main() {
    vec2 corner = vec2(float(gl_VertexID & 1), float((gl_VertexID >> 1) & 1));
    gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0);
}
