// P0: 기기에서 WebGL(Three.js)이 뜨는지만 확인하는 자리표시 화면.
// 실제 뷰어(툴패스·방향 큐브·재생·제스처)는 P4·P5에서 이 자리를 바꾼다.
import * as THREE from 'three';

export function startPlaceholderViewer(host: HTMLElement): void {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (error) {
    host.innerHTML = '<div class="placeholder" style="color:#a6aab1">WebGL을 시작할 수 없습니다.<br>' +
      String(error) + '</div>';
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x11151c);
  host.append(renderer.domElement);

  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.textContent = 'P0 뷰어 자리 — WebGL 확인용 (툴패스는 P4)';
  host.append(overlay);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
  camera.up.set(0, 0, 1);
  camera.position.set(160, -200, 160);
  camera.lookAt(0, 0, 0);

  const grid = new THREE.GridHelper(200, 20, 0x3a4250, 0x2a303c);
  grid.rotation.x = Math.PI / 2; // XY 평면
  scene.add(grid);
  scene.add(new THREE.AxesHelper(60)); // X 빨강, Y 초록, Z 파랑

  const resize = () => {
    const { width, height } = host.getBoundingClientRect();
    if (width < 1 || height < 1) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
  };
  new ResizeObserver(resize).observe(host);
  resize();
}
