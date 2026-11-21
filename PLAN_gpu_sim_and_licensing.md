# GPU 소재 시뮬레이션 · 상업 배포 라이선스 정리 플랜

> 작성 2026-11-21 · 대상: 데스크톱 `NC_Tool_List` v2.7.0~ / 안드로이드 `tool_list_android` v2.1.1~
> 작업 ID 순서대로 진행하고, 끝날 때마다 7장 진행 기록에 적는다. 두 앱은 같은 결과로 동작해야 한다(CLAUDE.md 4절).

---

## 0. 배경 — 검토 결과 요약

### 0.1 지금 해상도를 막는 것
| | PC | 안드로이드 |
|---|---|---|
| 3축 Z-map | 계산 약 100만 칸(0.05~0.5mm), **화면 메쉬 한 변 600**(안전 모드 300) — `nc_sim.py` `SIM_DISPLAY_GRID_MAX` | 화면 300 — `sim/simEngine.ts` |
| 3D 복셀(3+2·5축·턴밀) | 2,000만 칸, 최소 0.1mm — `nc_sim3d.py` | 300만 칸 — `sim/voxel.ts` |

계산한 정밀도를 화면이 버리고, 균일 3D 격자는 셀을 반으로 줄이면 메모리가 8배라 더 줄일 수 없다.

### 0.2 상용 CAM이 쓰는 엔진
CIMCO는 자체 GPU 커널(2022), Mastercam·Cimatron은 ModuleWorks GPU Simulation(덱셀 기반, Vulkan), Edgecam 등은 MachineWorks를 쓴다.
모두 유료 C++ SDK라 Sum Path(특히 안드로이드)에 넣을 수 없다. **공통 방식은 덱셀 계열 소재 + GPU** 이고, 이 방식은 직접 구현할 수 있다.

### 0.3 시안(승인 대기)
- GPU 시뮬레이션 뷰어 시안: https://claude.ai/artifact/3Sh6brpAEqANyUBtsb19gp
- `ncdata.nc` I-90 J-90 면(13,072선분): 현재 0.092mm / 100만 칸 / 화면 274×600 → **GPU 0.033mm / 760만 칸 / 화면 934×2048 + 칸 단위 음영**(8192 설정 시 0.017mm, 3,000만 칸).
- 방식: 소재 격자 한 칸 = GPU 화소 하나. 화소마다 공구 형상(평·볼·코너R·드릴)의 가장 낮은 점을 정확히 구해(볼록 함수 → 황금분할 탐색) 깊이 버퍼에 가장 낮은 값만 남긴다(깊이 시험 LESS). 화면은 그 깊이 텍스처를 바로 읽는다.
- 속도는 GPU 없는 서버(SwiftShader)에서만 쟀다(66초). **실제 PC·휴대폰 측정이 G6의 첫 일이다.**

---

## 1. 목표와 범위

1. **L — 상업 배포 라이선스 정리**: 오픈소스 고지(About), PyQt5(GPL) 문제 해결.
2. **G — GPU 고해상도 3축 Z-map**: PC·안드로이드 같은 셰이더, 같은 결과(골든), CPU 엔진은 대체 경로로 남긴다.
3. **T — 트라이덱셀(3+2·동시 5축·턴밀)**: G 다음 단계. 이 문서에서는 개요만.

범위 밖: 상용 SDK(ModuleWorks·MachineWorks) 도입, 공구 홀더 충돌 검사, GPU 선반 2D 단면(현재 엔진 유지).

---

## 2. L — 라이선스

| ID | 작업 | 상태 |
|---|---|---|
| L1 | **오픈소스 라이선스 고지** — 데스크톱 `third_party_notices.py`(COMPONENTS 한 곳에서 관리, 빌드 때 설치된 패키지의 LICENSE 원문을 모아 `_internal/licenses/THIRD_PARTY_NOTICES.txt`로 동봉, About → `오픈소스 라이선스 고지...`). 안드로이드 `tools/collect_licenses.mjs`(package-lock의 배포용 패키지 69개 원문 + Noto Sans KR OFL + AndroidX Apache-2.0 → `public/THIRD_PARTY_NOTICES.txt`, `npm run build`가 먼저 실행, About → `오픈소스 라이선스`) | **완료 v2.7.0 / 안드로이드 v2.1.1** |
| L2 | **PyQt5 → PySide6(LGPL)** — 3장 | 대기 |
| L3 | 배포 점검표: 설치본 `_internal\licenses\THIRD_PARTY_NOTICES.txt` 존재, About 버튼 동작, APK About 동작, 새 오픈소스 추가 시 COMPONENTS/`NOTICE_SUMMARY` 갱신 | 매 릴리스 |

남은 확인(빌드 PC): PyQt5·PyOpenGL·PyInstaller는 패키지 안에 라이선스 파일이 없거나(앞 둘) 빌드 venv에만 있어, 고지문에 원문 위치(URL)를 적었다. L2 후 PyQt5 항목은 PySide6(LGPL, 원문 동봉)로 바뀐다.

---

## 3. L2 — PySide6 전환 상세

**이유**: PyQt5는 GPL-3.0 또는 Riverbank 상용 라이선스다. 소스 비공개 판매(라이선스 키)와 GPL은 충돌한다. PySide6는 Qt 공식 바인딩, LGPL-3.0이라 동적 링크(onedir의 별도 DLL)로 상용 판매가 가능하다. *Riverbank 상용 라이선스를 이미 샀다면 L2는 선택 사항이다.*

| ID | 작업 |
|---|---|
| L2-1 | `nc_build_venv`에 PySide6 설치, pyqtgraph가 PySide6를 고르는지 확인(`PYQTGRAPH_QT_LIB=PySide6`) |
| L2-2 | import 교체: `NC_Tool_List.py`, `nc_viewer_widget.py`, `ui_icons.py`, `SumPath_License_Maker.py`, `tests/` — `PyQt5.Qt*` → `PySide6.Qt*`, `pyqtSignal` → `Signal`, `pyqtSlot` → `Slot` |
| L2-3 | Qt6 차이: `exec_()` → `exec()`, `QAction`·`QShortcut`은 `QtGui`, `QOpenGLWidget`은 `QtOpenGLWidgets`, 열거형 전체 이름(`Qt.AlignmentFlag.AlignLeft` 등), `QDesktopWidget` 제거(`QScreen`), 고DPI 기본 켜짐(화면 배율 확인), `QRegExp` → `QRegularExpression` |
| L2-4 | 소프트웨어 OpenGL 대체 경로(보안 PC 대응 v1.4.x) 재확인: PySide6 휠의 `opengl32sw.dll` 포함 여부, `QT_OPENGL=software` 동작 |
| L2-5 | `NC_Tool_List.spec`: hiddenimports를 PySide6로, excludes에서 `PySide6` 빼고 `PyQt5` 넣기. 배포 폴더 크기 비교 |
| L2-6 | `third_party_notices.COMPONENTS`: PyQt5·Qt 5 → PySide6·Qt 6(LGPL-3.0), shiboken6 |
| L2-7 | 전체 테스트 + 수동 점검(3D 뷰어, 재생, PDF, 라이선스 창, 단일 실행, 파일 연결), Windows 10/11 실행 |

위험: Qt6는 Windows 10 이상만 지원(대상 PC 확인). 3D 뷰어 마우스·확대 동작 테스트(`test_v23x_*`)가 많아 동작 차이를 먼저 본다.

---

## 4. G — GPU 고해상도 Z-map

### 4.1 설계 결정
- **셰이더 원본은 한 곳**: `sim_shaders/`(GLSL ES 3.00) — `cut.vert/frag`(절삭), `surface.vert/frag`(표시). 데스크톱은 파일을 읽고(앞에 `#version 330 core` 변환), 안드로이드는 Vite `?raw`로 가져온다. 같은 수식 = 같은 결과.
- **PC**: 3D 뷰어의 OpenGL 문맥(pyqtgraph `GLViewWidget`) 안에서 **ModernGL(MIT)** `moderngl.create_context()`로 기존 문맥을 감싸 FBO·텍스처를 관리한다. 필요 GL 3.3. 안 되면(안전 모드·소프트웨어 GL·GL<3.3) 지금 CPU 엔진(`nc_sim.ZMapStock` + numba)으로 자동 전환.
- **안드로이드**: three.js `WebGLRenderTarget` + `DepthTexture(FloatType)` + `RawShaderMaterial`(인스턴스 사각형). WebGL2 없으면 지금 `sim/zmap.ts`.
- **소재 결과 읽기**: STL 내보내기·충돌 표시·테스트용으로 깊이 텍스처를 numpy/Float32Array로 읽는다(`readPixels`, 필요할 때만).
- 공구 표: 평·볼·코너R·드릴(원뿔)·챔퍼. 지금 `nc_sim.ToolShape` 프로파일을 셰이더 uniform(R, 코너R, 원뿔 기울기)으로 옮긴다. 테이퍼·특수 프로파일은 G 후반에 표(1D 텍스처) 방식으로 넓힌다.

### 4.2 작업
| ID | 작업 | 완료 기준 |
|---|---|---|
| G0 | 시안 승인(0.3 뷰어, CLAUDE.md 5절) | 사용자 승인 |
| G1 | `sim_shaders/` 작성 + CPU 기준 구현(`nc_sim_gpu_ref.py` / `sim/zmapGpuRef.ts`: 셰이더와 같은 수식을 화소 단위로) | 기준 구현이 지금 `ZMapStock` 결과와 칸마다 1e-3mm 이내(공구 가장자리 칸 제외) |
| G2 | PC `nc_sim_gpu.py`: ModernGL 절삭(구간 증분·되감기 = 다시 그리기), `GpuZMapStock`이 `ZMapStock`과 같은 인터페이스(재생 슬라이더·공정 스냅샷 대신 즉시 재계산) | 기존 시뮬레이션 테스트가 GPU 경로로도 통과 |
| G3 | PC 표시: `GLGraphicsItem` 하위 클래스로 높이 텍스처 직접 그리기(인스턴스 띠, 칸 단위 법선·공구 색·깊이 색), 옆면, 기존 모서리 선 옵션 대체 | 시안과 같은 화면, 600 제한 없음 |
| G4 | 안드로이드 `sim/zmapGpu.ts` + `viewer/simLayer.ts` 연결 | 시안과 같은 화면 |
| G5 | 골든: `tools/golden/export_zmap.py`에 GPU 기준 구현 결과 추가, 두 앱 비교 시험. 실제 GPU 결과는 Playwright(크로미움 소프트웨어 GL)로 기준 구현과 비교 | `npm test`, `pytest` 통과, SOURCE_REV 갱신 |
| G6 | 성능 측정: 내장 그래픽(Intel UHD)·외장 PC, 휴대폰 2대 이상. 목표 — 13k선분·4096 전체 계산 1초 이내, 재생 60fps | 측정표를 7장에 기록 |
| G7 | 설정: 해상도(자동/2048/4096/8192), 안전 모드면 CPU, 정보 표시(셀 크기·칸 수) | 설정 창 저장·복원 시험 |
| G8 | 확대 고정밀(Quality Zoom): 보이는 영역만 더 작은 셀로 다시 계산 | 0.01mm 이하 표시 |
| G9 | G68.2 면별 소재 → 지금 3D 복셀 경로와의 경계 정리(3+2는 T 단계 전까지 면별 Z-map 미리보기 옵션) | 사용자 확인 |

### 4.3 위험과 대응
| 위험 | 대응 |
|---|---|
| 보안 PC·구형 그래픽(GL 3.3 미만), 소프트웨어 GL | 기능 감지 후 CPU 엔진 자동 전환, 로그에 사유 기록 |
| GPU 부동소수 차이로 두 앱 결과가 1e-4mm 수준 다름 | 골든 비교에 허용 오차(1e-3mm), 기준 구현은 같은 수식 |
| 큰 격자 메모리(8192² = 깊이 256MB + 색 64MB) | 그래픽 메모리 조회 후 상한, 휴대폰은 4096까지 |
| 아주 긴 선분의 사각형이 넓어 화소 낭비 | 긴 선분을 조각으로 나눠 인스턴스 추가 |
| 급속 이송(G0) 충돌 표시 | 별도 패스(깎지 않고 닿는 칸 수만 셈, 지금 규칙 그대로) |

---

## 5. T — 트라이덱셀(개요)
3+2·동시 5축·턴밀 소재를 X·Y·Z 세 방향 덱셀(광선마다 구간 목록)로 바꾼다. 메모리가 부피가 아니라 면적에 비례해 0.02mm대가 가능하다. GPU 절삭은 세 방향 각각 깊이 박리(depth peeling)로 그린다. 표시는 덱셀 → 화면 레이캐스트. G가 끝난 뒤 별도 플랜(`PLAN_tridexel.md`)을 쓴다.

---

## 6. 버전 계획
| 데스크톱 | 안드로이드 | 내용 |
|---|---|---|
| 2.7.0 | 2.1.1 | L1 오픈소스 라이선스 고지(완료) |
| 2.7.x | — | L2 PySide6 전환 |
| 2.8.0 | 2.2.0 | G1~G7 GPU Z-map |
| 2.8.x | 2.2.x | G8~G9 |
| 2.9.0~ | 2.3.0~ | T 트라이덱셀 |

빌드본은 매번 둘 다(설치본 + release APK). 오픈소스가 바뀌면 `ABOUT_RELEASE_INSTRUCTIONS.md` "Open source" 줄과 COMPONENTS를 함께 고친다.

---

## 7. 진행 기록
| 날짜 | 버전 | ID | 내용 |
|---|---|---|---|
| 2026-11-21 | 2.7.0 / A 2.1.1 | 검토·시안 | 오픈소스 엔진 검토, 상용 CAM 엔진 조사, GPU 시안(0.3), 라이선스 검토(PyQt5 GPL 위험 발견) |
| 2026-11-21 | 2.7.0 / A 2.1.1 | L1 | 오픈소스 라이선스 고지 About 연결(데스크톱·안드로이드), 고지문 자동 생성, 테스트 추가 |
| 2026-11-21 | 2.7.1 / A 2.1.2 | G7 준비 | 소재 해상도 목록을 엔진별 두 묶음(기본 CPU / 고해상도 GPU 칸 수)으로 나눔. GPU 묶음은 엔진 전까지 "준비 중"(`GPU_ENGINE_AVAILABLE`). 앱이 처음 한 번 Windows 그래픽 설정에 고성능(외장 우선, 없으면 내장)을 직접 씀(`ensure_gpu_preference`) |
