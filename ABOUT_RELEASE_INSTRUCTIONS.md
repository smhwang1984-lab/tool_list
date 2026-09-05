# About / Release Instructions

Last updated: 2026-09-05 (v1.6.6)

## About button requirements

- Add an About button using the same application version as the current release.
- The About popup must be lightweight and viewer-style, with no changes to unrelated features.
- The popup must display:
  - Application purpose
  - Version
  - Open source software used
  - Build/creation date in year-month-day format
  - Creator: Hwang.seonmun

## Release packaging requirements

- Create the installer/package for the same version after adding or updating the About popup.
- Do not modify unrelated behavior or features while preparing this release.
- Prefer PyInstaller onedir packaging with UPX disabled for Windows security software compatibility.
- Install the complete `dist/NC_Tool_List` folder, including `_internal`, rather than a single self-extracting executable.
- Prefer TSERP-style installation under `C:\NC_Tool_List` when matching existing accepted plant PC deployment behavior.
- As of v1.5.0, the user explicitly asked for `.nc`/`.mpf`/`.tap` to be registered as this app's default program, so the installer now writes HKCR file-association registry entries (`ChangesAssociations=yes`) with `uninsdeletekey`/`uninsdeletevalue` so they're removed cleanly on uninstall. Do not revert this without the user asking.

## Version history maintenance

- Every time a new version is created, append a record here.
- Each record must include:
  - Version
  - Release/build date
  - Summary of the version change
  - Open source software used or changed in that version
  - Installer/package creation status

## Version history

### 2026-09-05 (latest, v1.6.6)

- Version: 1.6.6
- Release/build date: 2026-09-05 (사용자 승인 후 설치본·포터블 패키지 생성 완료)
- Summary: 사용자 요청 6건, 선반 모드의 "밀링 툴(구동공구) 혼합 가공" 단계(LATHE_MODE_GUIDELINES.md §8
  승인 후 별도 단계)로 진입.
  1. **선반 툴리스트** — 공정 순서 정렬을 MCT처럼 공구번호 순 + 빈 행 유지로 바꾸고, INSERT/홀더
     셀 폭을 내용에 맞춰 넓혀 폰트 축소·말줄임을 없앴다(화면 표 + PDF).
  2. **M35 턴밀 Y축** — `M35`(구동공구 ON)~`M34`(선삭 복귀) 상태를 추적해 실제 기계 Y워드를
     반영하고, `G12.1`/`G112` 극좌표 보간 중에는 C 워드를 각도가 아니라 Y(mm)로 해석한다.
  3. **평면별 원호** — M35 중 `G17`(기계 X-Y)/`G19`(기계 Y-Z) 평면 원호를 로컬 좌표로 계산한 뒤
     C만큼 배치 회전(밀링 4/5축 원호와 같은 방식).
  4. **M98 서브프로그램** — `M30` 뒤 `O<번호>` 헤더 ~ 다음 헤더(또는 파일 끝)를 본문으로 보고
     `M98 P<번호> [L<반복>]` 호출 지점에 펼친다.
  5. **C축 회전 시뮬레이션** — 재생 커서가 있을 때(동적 트레이스 + 커서 구)만 공구가 +X 센터에
     고정된 것처럼 회전을 상쇄한다. 정적 전체 경로는 기존(v1.6.4~5) 표현 그대로 유지.
  6. **뷰 제한** — 선반 ISO 투영에서도 뷰 큐브를 숨겨 ISO/선반 두 각도로만 보게 제한.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup
  (변경 없음 — 의존성 추가/제거 없음).
- Details:
  - **선반 툴리스트 정렬/셀 폭(`NC_Tool_List.py`):** `parse_lathe_program()`이 이제 TOOL NO의
    앞 두 자리(공구번호)/뒤 두 자리(옵셋)로 정렬하고, 빠진 공구번호는 밀링(`parse_program`의
    `range(1, max+1)` 빈 행 로직)과 같은 모양으로 빈 행을 채운다. T워드를 못 찾은 항목은 정렬된
    본문 뒤에 원래 순서로 붙인다. `App._update_lathe_dynamic_col_width()`가 `QFontMetrics`로
    헤더/셀 실제 내용 폭을 재서 `LATHE_COL_WIDTH`보다 넓으면 그 값을 쓰고, `_relayout_tool_table()`은
    선반일 때 `scale`을 1.0으로 고정(밀링은 패널 폭에 맞춰 줄어드는 기존 동작 그대로). PDF도
    `LATHE_PDF_COLUMN_WEIGHTS`를 INSERT/홀더 쪽으로 재배분.
  - **M35 구동공구 Y축(`nc_viewer_widget.py`):** `lathe_local_point(z, x_diameter, y_value)`(C
    회전 전 로컬 좌표) + `lathe_rotate_c(point, c_deg)`(주축 둘레 회전)로 `lathe_world_point()`를
    분해 — `y_value=0`이면 v1.6.4 결과와 완전히 동일(회귀 없음). `M35`/`M34` 모달 플래그
    (`lathe_milling_active`)를 `is_lathe` 분기에서만 추적. `G12.1`/`G13.1`은 이제 `is_lathe and
    lathe_milling_active`일 때 `continue`를 건너뛰어 같은 블록의 모션 워드도 처리하고, 극좌표 중
    C 워드는 각도가 아니라 Y(mm)로 해석(`O4006.nc:107` "X-.076Z-11.C-.067R.077"이 근거).
  - **평면별 원호(`nc_viewer_widget.py`):** `ARC_PLANE_AXES`에 `LATHE_G17`(반경-Y, I/J)/
    `LATHE_G19`(Y-기계Z, J/K) 키를 추가(기존 G17/G18/G19/LATHE 키는 그대로). M35 중 G17/G19
    원호는 로컬(`start_local`/`target_local`) 평면에서 `_arc_points()`로 보간한 뒤 결과 점마다
    `lathe_rotate_c(pt, cc_deg)`를 적용 — 밀링 4/5축 원호가 로컬로 그리고 배치 회전하는 것과
    같은 방식(v1.4.5).
  - **M98 서브프로그램(`nc_viewer_widget.py`):** `NCViewerWidget._expand_lathe_subprograms()`
    신설 — `M30` 뒤 `O<번호>` 헤더들을 스캔해 본문 범위를 잡고, 메인 프로그램을 순회하며
    `M98 P<번호> [L<반복>]`을 만나면 그 자리에 본문을 펼친다(재귀 10단계 상한, 미정의 P번호는
    무시). 반환값은 `(원본 줄번호, 텍스트)` 쌍이라 `process_nc_lines()`의 `idx` 기반
    `line_to_tool_map`/`line_to_coord_map`/`src_line`이 그대로 맞는다 — 커서 동기화가 깨지지
    않는다. 선반이 아니면 기존 `enumerate(lines)` 그대로. **G90/G91 증분 모드는 이번 단계에
    넣지 않았다** — 이 선반 방언에서 G90은 고정 사이클(G70~G76 계열) 표기와 겹쳐, 밀링처럼
    단순 절대/증분 스위치로 해석하면 오히려 잘못될 위험이 있다(LATHE_MODE_GUIDELINES.md §8
    "선반 고정 사이클"과 같은 사유로 별도 승인 단계로 미룸).
  - **C축 회전 시뮬레이션(`nc_viewer_widget.py`):** `line_to_c_rot[idx]`에 줄마다 유효 C
    회전각을 기록(`modal_state_map`과 같은 자리에서 우선 채우고, C가 실제로 갱신되는 곳에서
    덮어씀). `set_cursor_line()`이 `is_lathe_mode()`일 때 그 값을 `_rotate_gl_items()`로
    동적 트레이스(`dynamic_trace_items`)에 걸고, 커서 구는 `lathe_rotate_c(pt, -c_rot)`로 회전
    성분을 뺀 위치(+X 센터)에 둔다. 정적 전체 경로(`plot_items`)는 손대지 않아 "툴패스를 볼
    때는 지금과 같이" 요구를 지킨다.
  - **뷰 제한(`nc_viewer_widget.py`):** `set_camera_projection()`의 뷰 큐브 가시성을
    `not (lathe or orbit_locked)`로 바꿔 — 기존엔 `orbit_locked`(= "선반" 뷰에서만 True)만
    봐서 선반 ISO에서 뷰 큐브가 그대로 보이고 클릭돼 임의 각도로 샐 수 있었다. 밀링은 `lathe`가
    항상 False라 기존 동작(뷰 큐브 항상 보임) 그대로.
- Verification: `pytest tests/test_nc_tool_list.py` **128/128 통과**(기존 120개 + v1.6.6 신규 8개:
  선반 툴리스트 정렬+빈행, `lathe_world_point(y_value=...)`가 로컬+회전 합성과 일치 및 `y=0`일 때
  회귀 없음, M35+G17/G19 원호가 기계 XY/YZ 평면과 C 회전을 반영하는지, G12.1 중 C가 Y(mm)로
  처리되는지, M98 반복 호출 확장 + 호출 안 된 서브프로그램 미포함 + 원본 줄번호 보존, C축 회전
  시 커서 구가 +X 센터에 고정되고 동적 트레이스만 회전(정적 경로는 항등)하는지, 선반 ISO에서도
  뷰 큐브가 숨겨지는지). 실제 `O4006.nc`(M35+G12.1)/`O1699.nc`(M35+G17+Y축 헬리컬)를 뷰어에
  직접 로드해 크래시 없이 처리되고 G12.1 구간의 Y값이 실제 파일 수치(mm)와 일치하는지 육안
  확인했다. 개발 중 전체 pytest 실행에서 10개가 실패한 적이 있었는데, v1.6.5와 같은 원인
  (`QSettings("NC Tool List", "EmbeddedViewer")`가 이 PC의 다른 세션/스크립트와 공유되어 생기는
  외부 간섭 — 이번엔 릴리스 전 O4006.nc/O1699.nc 육안 확인 스크립트가 남긴 값)이었고, 그 값을
  정리한 뒤 재실행해 128/128이 안정적으로 재현됨을 두 번 확인했다. 코드 회귀가 아니다.
- Installer/package: **생성 완료** (사용자 승인 후 빌드).
  - `python -m PyInstaller --noconfirm --clean NC_Tool_List.spec` — onedir, UPX 비활성,
    `dist\NC_Tool_List` 146 MB, `_internal` 포함. `OpenGL\DLLS` 제외 확인(freeglut/gle32/gle64 DLL 없음).
  - `ISCC.exe NC_Tool_List.iss` (Inno Setup 6) — `installer\NC_Tool_List_Setup_v1.6.6.exe` 47.4 MB,
    설치 경로 `C:\NC_Tool_List`, `.nc`/`.mpf`/`.tap` 파일 연결 등록 포함.
  - 포터블: `installer\NC_Tool_List_Portable_v1.6.6.zip` 62.4 MB (dist 내용물을 zip 루트에 담는 기존
    구조, 311개 항목으로 v1.6.3~v1.6.5와 동일).
  - 빌드 검증: 프리즈된 `NC_Tool_List.exe`의 파일/제품 버전이 `1.6.6.0`으로 찍히고, 실제로 실행해
    `startup.log`에 트레이스백 없이 `Starting Sum Path v1.6.6 frozen=True`가 남는 것을 확인한 뒤 종료했다.
    설치 프로그램 자체의 VersionInfo도 1.6.6 / NC Tool List / S M.HWANG으로 확인했다.
  - 산출물은 저장소의 `installer\` 폴더(gitignore 대상이라 커밋되지 않음)에 둔다.

### 2026-09-05 (latest, v1.6.5)

- Version: 1.6.5
- Release/build date: 2026-09-05 (사용자 승인 후 설치본·포터블 패키지 생성 완료)
- Summary: 사용자 요청 3건, 플랜 구성 후 승인받아 진행.
  1. **선반 뷰 카메라** — "선반" 투영에서는 툴패스가 화면 상단에 고정돼 보이던 문제를 고치고,
     좌드래그로 상하좌우 이동(팬)만 되게 하며(회전은 잠금), 사각형을 그려 한 번에 확대하는
     "드래그줌" 버튼을 추가했다.
  2. **좌표 오버레이 위치** — 선반 뷰일 때 좌표 표시를 좌상단에서 화면 하단(재생 속도바 바로
     위)으로 옮긴다.
  3. **선반 전용 툴리스트** — 밀링 양식과 완전히 별개인 4열(TOOL NO/INSERT/홀더/REMARK) 표를
     신설. TOOL NO는 옵셋까지 포함하고, 1번째 주석 줄이 홀더, 2번째가 인서트다. 3D 뷰어 공정
     필터 라벨도 선반에서는 인서트 이름을 쓴다.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup
  (변경 없음 — 의존성 추가/제거 없음).
- Details:
  - **선반 뷰 카메라(`nc_viewer_widget.py`):** `OrthographicGLViewWidget`에 `orbit_locked`(선반
    "선반" 투영에서만 True) — 켜져 있으면 좌드래그가 pyqtgraph 기본 orbit 대신 `pan(dx, dy, 0,
    'view')`을 직접 호출한다(기존 Ctrl+좌드래그 팬과 같은 호출 규약). "ISO" 버튼은 항상
    `orbit_locked=False`로 자유 회전. 잠금 중에는 뷰 큐브(모서리 오리엔테이션 큐브)도 숨겨
    드래그/면 클릭으로 우회 회전하지 못하게 한다. `NCViewerWidget._lathe_path_center_and_radius()`
    로 로드된 경로의 바운딩박스 중심/반지름을 구해, 선반 투영에서는 원점이 아니라 그 중심으로
    카메라를 리센터한다 — 선반은 X(지름)가 반경으로 바뀌어 항상 월드 Z≥0(화면 절반)에만 그려져
    원점 리센터로는 위로 쏠려 보였다. 밀링 리센터(`_zoom_to_fit_distance`, 원점 recenter)는
    `is_lathe_mode()` 분기 밖에 그대로 둬 전혀 손대지 않았다. 선반 전용 "드래그줌" 토글 버튼
    (`ProjectionOverlayWidget`, 밀링에는 없음) — 켜진 동안 좌드래그가 `QRubberBand` 사각형을
    그리고, 손을 떼면 `_apply_drag_zoom()`이 그 사각형 중심을 화면 중앙으로 `pan()`한 뒤 사각형이
    차지하던 비율만큼 `distance`를 줄이고 자동으로 꺼진다(직교 투영이라 화면 픽셀 비율 = 확대
    비율이 정확히 성립).
  - **좌표 오버레이 하단 배치(`nc_viewer_widget.py`):** `top_left_widgets` 목록(좌표+투영 오버레이가
    좌상단에 쌓이던 곳)과 별개로 `bottom_coord_widget` 슬롯을 추가. `NCViewerWidget._place_coord_overlay()`
    가 선반 모드면 좌표 오버레이를 그 목록에서 빼서 `bottom_coord_widget`으로 옮기고, 밀링으로
    돌아오면 원래 자리(좌상단 첫 번째)로 되돌린다. `_reposition_bottom_coord()`가 재생 속도바
    바로 위 중앙에 배치한다.
  - **선반 전용 툴리스트 파서(`NC_Tool_List.py`):** `parse_lathe_program()` 신설 — 실제 선반
    프로그램(`O1699.nc`, 사용자 제공 샘플) 양식 기준. 밀링의 `N#(#: Tool Change)`/`[SO ..]` 표기와
    달리, 선반은 `N<번호>` 단독 라인 바로 아래 통짜 괄호 주석 두 줄이 각각 **1번째 = 홀더,
    2번째 = 인서트**다(`LATHE_N_RE`, `LATHE_FULL_COMMENT_LINE_RE`). 그 블록(다음 N 라인 전까지)
    안에서 옵셋이 살아있는 `Tnnnn`(뒤 두 자리 ≠ `00`, `T0000` 제외, `LATHE_ANY_T_RE`)을 TOOL NO로
    삼고, 없으면 옵셋 00짜리 T워드를 그대로 쓴다 — v1.6.4의 `Tnn00` 우선순위와 같은 규약. 같은
    TOOL NO(옵셋까지 동일)를 쓰는 N 블록은 한 행으로 합치고 REMARK에 N번호를 누적하며, 옵셋이
    다르면(`T0101` vs `T0111`) 별도 행으로 남는다(사용자 승인 규약). O1699.nc(공구 9개, N1~N9)로
    실측 검증.
  - **표 스키마 분리(`NC_Tool_List.py`):** `LATHE_COLUMNS`(TOOL NO/INSERT/홀더/REMARK) 4열과
    전용 폭(`LATHE_COL_WIDTH`)을 추가. `App.active_columns()`/`active_col_width()`/
    `_active_col_width_total()`이 `is_lathe_program()`을 보고 밀링 16열/선반 4열을 갈아 끼우며,
    표 생성(`_configure_table_columns()`)·행 편집(`show_row_editor`/`set_table_row`/`table_text`)·
    복사(`copy_table`)·리사이즈(`_relayout_tool_table`)가 전부 이 메서드를 거친다. 밀링 열 상수
    (`COLUMNS`/`COL_WIDTH`)와 그 로직은 그대로 둬 기존 동작에 영향이 없다.
  - **선반 전용 PDF(`NC_Tool_List.py`):** 기존 16열 고정 레이아웃(`export_tool_list_pdf` 등)과 별도로
    `export_lathe_tool_list_pdf`/`make_lathe_pdf_table`/`LATHE_PDF_COLUMN_WEIGHTS`(4열)를 신설.
    `App.save_pdf()`가 `is_lathe_program()`에 따라 둘 중 하나를 부른다.
  - **3D 뷰어 필터 라벨(`NC_Tool_List.py`):** `lathe_tool_name_map_from_rows()` — 선반은 필터
    라벨의 이름 자리에 NAME 대신 INSERT를 쓴다(뷰어의 2자리 공구번호 키 `T01`~에 매핑).
    `App.tool_name_map()`이 `is_lathe_program()`으로 밀링용 `tool_name_map_from_rows()`와 갈라 쓴다.
- Verification: `pytest tests/test_nc_tool_list.py` **120/120 통과**(기존 113개 유지 + v1.6.5 신규 18개:
  선반 뷰 좌드래그가 각도는 그대로 두고 중심만 옮기는지(팬), 드래그줌이 사각형만큼 확대 후
  자동으로 꺼지는지, "선반" 투영이 회전을 잠그고 바운딩박스 중심으로 리센터하는지(밀링과 달리
  원점이 아님을 명시적으로 확인) + "ISO"가 잠금을 푸는지, 좌표 오버레이가 선반에서 재생바
  위로 옮겨졌다가 밀링 복귀 시 좌상단으로 되돌아오는지, `parse_lathe_program`이 O1699.nc 양식의
  홀더/인서트/TOOL NO/REMARK를 정확히 읽는지 + 같은 TOOL NO 병합/다른 옵셋 별도 행 규약,
  `lathe_tool_name_map_from_rows`가 INSERT를 2자리 공구번호로 매핑하는지). 실제 `O1699.nc`
  샘플로 표/PDF/필터맵까지 엔드투엔드 스모크 테스트를 돌려 확인했다. 개발 중 pytest 전량 실행에서
  간헐적 실패가 몇 차례 나왔는데, 원인을 추적한 결과 이 PC에서 동시에 도는 다른 세션/워크트리와
  `QSettings("NC Tool List", "EmbeddedViewer")`(실제 Windows 레지스트리 키, 테스트별로 격리되지
  않음)를 공유해서 생기는 외부 간섭이었다(격리된 반복 실행에서는 항상 120/120 통과). 코드
  회귀가 아니라는 것을 확인했다 — 이 QSettings 공유 문제 자체는 이번 작업 범위 밖의 기존 구조라
  손대지 않았다.
- Installer/package: **생성 완료** (사용자 승인 후 빌드).
  - `python -m PyInstaller --noconfirm --clean NC_Tool_List.spec` — onedir, UPX 비활성,
    `dist\NC_Tool_List` 146 MB, `_internal` 포함. `OpenGL\DLLS` 제외 확인(freeglut/gle32/gle64 DLL 없음).
  - `ISCC.exe NC_Tool_List.iss` (Inno Setup 6) — `installer\NC_Tool_List_Setup_v1.6.5.exe` 46 MB,
    설치 경로 `C:\NC_Tool_List`, `.nc`/`.mpf`/`.tap` 파일 연결 등록 포함.
  - 포터블: `installer\NC_Tool_List_Portable_v1.6.5.zip` 62.4 MB (dist 내용물을 zip 루트에 담는 기존
    구조, 311개 항목으로 v1.6.3~v1.6.4와 동일).
  - 빌드 검증: 프리즈된 `NC_Tool_List.exe`의 파일/제품 버전이 `1.6.5.0`으로 찍히고, 실제로 실행해
    `startup.log`에 트레이스백 없이 `Starting Sum Path v1.6.5 frozen=True`가 남는 것을 확인한 뒤 종료했다.
    설치 프로그램 자체의 VersionInfo도 1.6.5 / NC Tool List / S M.HWANG으로 확인했다.
  - 산출물은 저장소의 `installer\` 폴더(gitignore 대상이라 커밋되지 않음)에 둔다.

### 2026-09-05 (v1.6.4)

- Version: 1.6.4
- Release/build date: 2026-09-05 (사용자 승인 후 설치본·포터블 패키지 생성 완료)
- Summary: 사용자 요청 3건.
  1. **PDF 출력 방식 변경**: 툴 리스트 PDF를 낼 때 저장 위치를 묻지 않는다. 임시 폴더에 만들어
     곧바로 기본 PDF 프로그램으로 띄우고, 저장은 사용자가 그 뷰어에서 필요할 때만 하게 한다.
  2. **CNC 선반(Lathe) 모드 개념 도입 — 기본 모드까지**. 새 문서 `LATHE_MODE_GUIDELINES.md`에
     설계 지침을 먼저 못박았다. **최우선 규칙: 선반은 기존 밀링/MCT 장비 툴패스에 절대 영향을
     주지 않는다.**
  3. **선반 공구 교체 기준 `Tnn00`** (사용자가 별도로 지시·승인). 선반은 M6가 없고 옵셋 00인
     T 워드가 공구 교체 지점이다.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup
  (변경 없음 — 의존성 추가/제거 없음).
- Details:
  - **PDF 바로 열기(`NC_Tool_List.py`):** 새 `pdf_preview_dir()` / `pdf_preview_path(metadata, directory=None)`.
    `%TEMP%\NC_Tool_List_PDF` 아래에 `default_pdf_filename()` 이름으로 파일을 만든다. 같은 이름의
    PDF가 이미 뷰어에 열려 있어 지울 수 없으면(Windows 파일 잠김) `이름(1).pdf`, `이름(2).pdf` …로
    최대 50회까지 새 이름을 찾는다. `App.export_pdf()`에서 `QFileDialog.getSaveFileName` 호출을
    제거하고 이 경로로 바로 `save_pdf()`를 부른다. `save_pdf()`는 더 이상 "PDF 출력 완료" 안내창을
    띄우지 않는다(저장한 게 아니므로) — 생성 실패/열기 실패 시에만 메시지를 보여준다. 도움말
    문구도 "PDF 출력(기본 PDF 프로그램으로 바로 열림)"으로 갱신.
  - **선반 좌표계(`nc_viewer_widget.py`):** 새 모듈 함수 `is_lathe_machine()`, `lathe_world_point(z, x_diameter, c_deg)`.
    선반은 축을 스왑해 월드에 올린다 — **기계 Z -> 월드 X(화면 수평), 기계 X 반경 -> 월드 Z(화면 수직)**,
    C축은 반경을 주축(월드 X) 둘레로 회전시킨 성분(월드 Y). **X 워드는 지름이므로 반경 = X / 2**로
    환산한다(X20 -> 실제 반경 10). `process_nc_lines()`의 선반 분기에서 `cx`가 이제 지름 값을 그대로
    들고 있고, 월드로 내릴 때만 `lathe_world_point()`를 거친다. 좌표 오버레이(X~C)는 프로그램에
    적힌 지령값을 그대로 보여주므로 X는 여전히 지름으로 표시된다.
  - **선반 원호(`nc_viewer_widget.py`):** `ARC_PLANE_AXES`에 **새 키** `"LATHE": (0, 2, 1, "k", "i")`를
    추가했다(기존 G17/G18/G19 항목은 손대지 않음 — 밀링 무영향). 선반 G02/G03은 이 평면으로 보간하며,
    시작/끝점이 이미 반경 공간이라 지름 개념이 원호에도 반영되고, I(X 방향 중심 오프셋)와 R은 선반
    관례대로 **반경 값**이므로 다시 절반으로 나누지 않는다. (u=월드 X, v=월드 Z) 배치라 기존 보간
    루틴의 G02 규약이 선반 뷰에서도 그대로 시계 방향이 된다.
  - **선반 전용 G28 / 고정 사이클(`nc_viewer_widget.py`):** 두 곳 모두 선반 전용 분기를 앞에 두고
    `continue` 하도록 분리했고, 뒤따르는 밀링 블록의 조건은 `(g43_active or is_lathe)` -> `g43_active`로
    바꿨다(밀링에서는 `is_lathe`가 항상 False라 동작은 동일, 의도만 명시적으로). 선반 사이클은
    밀링처럼 수직 Z로 내려가지 않고 **주축 방향(기계 Z)으로** R점 -> 최종 깊이로 움직인다.
  - **선반 전용 투영(`nc_viewer_widget.py`):** `_VIEW_PROJECTIONS`에 `"LATHE": (0, -90)` 추가 — 월드 XZ
    평면 정면 뷰라 화면에서 기계 Z가 수평, 기계 X(지름)가 수직으로 보인다. `ProjectionOverlayWidget`을
    버튼 목록 교체형으로 리팩터링(`MILL_BUTTONS` / `LATHE_BUTTONS`, `_rebuild_buttons()`, `set_lathe_mode()`,
    `button_labels()`). 선반 모드에서는 XY/XZ/YZ 대신 **ISO(축이 바뀐 상태) + 선반** 2개만 노출한다.
  - **투영 오버레이 찌그러짐 버그 수정(`nc_viewer_widget.py`):** 실제 앱을 띄워 장비를 선반으로 바꿨더니
    오버레이가 라벨 폭(40x20)까지 줄어들고 버튼이 2px 폭으로 잘려 보였다. 원인은 **이미 화면에 떠 있는
    오버레이의 레이아웃에 나중에 끼워 넣은 위젯이 숨김 상태로 들어와, 레이아웃 크기 계산에서 아예
    빠지는 것**이었다(단위 테스트에서는 위젯을 띄우지 않아 드러나지 않았다). `_rebuild_buttons()`가
    새 버튼을 `ensurePolished()` 후 `show()` 하고, 새 `_fit_to_contents()`가 레이아웃 캐시를 무효화한 뒤
    `QApplication.sendPostedEvents(self, QEvent.LayoutRequest)`로 보류 중인 레이아웃 갱신을 동기로
    흘려보내고 크기를 다시 잡은 다음 부모의 `_reposition_top_left()`로 위치까지 맞춘다.
  - **선반 공구 교체 기준 `Tnn00`(사용자 승인, `NC_Tool_List.py` + `nc_viewer_widget.py`):** 선반은 M6가
    없고 **`Tnn00`(옵셋 00)이 공구 교체 지점**이다. T 뒤 네 자리 중 앞 두 자리가 공구 번호, 뒤 두 자리가
    옵셋 번호이며, `T0101`처럼 옵셋이 살아 있는 블록은 교체가 아니고 `T0000`은 옵셋 취소라 제외한다
    (`LATHE_T_RE = r'T(?!0000)(\d{2})00(?!\d)'`). 적용 지점 3곳: ① `parse_program(text, name_types, lathe=False)`이
    선반일 때 주석을 걷어낸(`code_without_comments`) 코드에서 `Tnn00`을 찾아 공구 블록을 끊는다,
    ② 뷰어 `process_nc_lines()`의 공정 분리가 선반에서 `M6` 대신 `Tnn00`을 본다(밀링의 `M6 Tnn` 분기는
    그대로 두고 `if is_lathe / else`로 완전히 갈랐다), ③ `find_next_tool_change_span(text, start, lathe=False)`
    ('다음공구검색')도 선반에서 `Tnn00`만 짚고, 없을 때 안내 문구가 "Tnn00 항목 없음"으로 바뀐다.
    `App.is_lathe_program()`이 장비 콤보를 보고 이 플래그를 넘기며, 장비를 바꾸면 같은 원문이라도
    다시 파싱하도록 파싱 캐시 키에 `_last_parsed_lathe`를 추가했다. 뷰어 의존성 없이도 툴 리스트가
    동작해야 하므로 `is_lathe_machine()`은 `NC_Tool_List.py`에도 따로 둔다.
  - **선반 축 화살표 라벨(`nc_viewer_widget.py`):** 새 `_LATHE_AXIS_LABELS = ("Z", "C", "X")`와
    `is_lathe_mode()` / `current_axis_labels()`. `set_machine_type()`이 새 `_apply_lathe_mode_ui()`를 불러
    장비를 바꿀 때마다 투영 버튼과 축 문자를 갱신하고, 선반 최초 진입 시 카메라를 `"XZ"`가 아니라
    `"LATHE"` 프리셋으로 맞춘다. 밀링으로 되돌리면 전부 원상복구된다.
- Verification: `pytest tests/test_nc_tool_list.py` **113/113 통과** (기존 98개 전부 유지 + v1.6.4 신규 15개:
  `Tnn00` 정규식이 T0101/T0000/T012345/M6T1을 걸러내는지, 선반 `parse_program`이 Tnn00으로 공구를
  끊는지(같은 원문을 밀링 기준으로 읽으면 0개), '다음공구검색'이 선반에서 Tnn00만 짚는지,
  밀링의 M6 Tnn 인식이 그대로인지, 뷰어 공정 분리가 Tnn00에서만 갈라지는지,
  `lathe_world_point` 지름/축스왑/C축, 선반 경로 반경 환산, 선반 원호 R 정확도 + G02 시계방향,
  선반 투영버튼·축라벨 전환/복구, **선반을 거쳤다 돌아와도 밀링 툴패스가 완전히 동일한지**,
  투영 오버레이가 버튼 교체 후에도 찌그러지지 않는지(위 버그 회귀 고정 — 수정을 되돌리면 20 != 30으로
  실패하는 것을 확인했다), PDF 임시 경로 이름/재사용/잠김 시 폴백, `export_pdf`에 저장 다이얼로그가 없는지).
  또한 **실제 앱 창(1600x950)을 띄워** 선반 프로그램을 넣고 Viewer 모드 -> 장비 콤보에서 "2축 선반" 선택 ->
  투영 "선반"/"ISO" 버튼을 실제로 클릭하는 사용자 경로 그대로 구동해 스크린샷으로 확인했다.
  선반 샘플(`G00 X100. Z5.` / `G01 X100. Z-20.` / `G02 X60. Z-40. R20.` / `G01 X20. Z-40.`)을 오프스크린으로
  돌려 X100 -> 월드 (5, 0, 50), 원호 12점이 중심 (-40, 50)에서 반지름 20.000000을 유지하고 각도가
  단조 감소(선반 뷰 기준 시계 방향)하는 것을 확인했다.
- Installer/package: **생성 완료** (사용자 승인 후 빌드).
  - `python -m PyInstaller --noconfirm --clean NC_Tool_List.spec` — onedir, UPX 비활성(보안 프로그램 오탐 회피),
    `dist\NC_Tool_List` 145.0 MB, `_internal` 포함.
  - `ISCC.exe NC_Tool_List.iss` (Inno Setup 6) — `installer\NC_Tool_List_Setup_v1.6.4.exe` 45.2 MB,
    설치 경로 `C:\NC_Tool_List`, `.nc`/`.mpf`/`.tap` 파일 연결 등록 포함.
  - 포터블: `installer\NC_Tool_List_Portable_v1.6.4.zip` 62.4 MB (dist 내용물을 zip 루트에 담는 기존 구조,
    311개 항목으로 v1.6.3과 동일).
  - 빌드 검증: 프리즈된 `NC_Tool_List.exe`의 파일/제품 버전이 `1.6.4.0`으로 찍히고, 실제로 실행해
    `startup.log`에 트레이스백 없이 `Starting Sum Path v1.6.4 frozen=True`가 남는 것을 확인한 뒤 종료했다.
    설치 프로그램 자체의 VersionInfo도 1.6.4 / NC Tool List / S M.HWANG으로 확인했다.
  - 산출물은 저장소의 `installer\` 폴더(gitignore 대상이라 커밋되지 않음)에 둔다.

### 2026-09-05 (v1.6.3)

- Version: 1.6.3
- Release/build date: 2026-09-05
- Summary: v1.6.2 실사용 피드백 8건:
  1. **Bug fix**: 다크모드 토글 버튼이 v1.6.2에서 앱 상단 바로 옮겨졌는데, 그 상단 바 배경은 테마와 무관하게 항상 어두운 남색이다. 그런데도 아이콘 색을 테마에 따라 밝음/어두움으로 바꾸고 있어서, 라이트 테마일 때 어두운 아이콘(#1f2937)이 똑같이 어두운 상단 바 위에서 거의 안 보였다(다크 테마일 때만 우연히 밝은 아이콘이라 보였음). 이제 아이콘 색을 테마와 무관하게 항상 밝게(#f2f5fa) 고정한다.
  2. "큐브" 슬라이더/라벨이 v1.6.2에서 실수로 그대로 남아 있었다 — 감도와 같은 비율(40%)로 폰트·바 폭을 줄인다. 실제 3D 오리엔테이션 큐브 자체의 크기 범위/기본값은 이전과 같이 그대로 둔다(사용자가 명시적으로 손대지 말라고 요청한 부분).
  3. "좌표"(X~C) 표시를 불투명 배경의 QGroupBox 행에서 3D 화면 왼쪽 위의 투명 오버레이(`CoordOverlayWidget`)로 바꿔, 그 자리의 공구 경로가 가려지지 않게 했다. 축 프리픽스 글자(X:, Y: 등)는 어두운 3D 캔버스 위에서도 보이도록 흰색으로 고정했다(값 자체의 축별 색상은 그대로 유지).
  4. 투영(ISO/XY/XZ/YZ) 버튼 간격이 너무 붙어 있다는 피드백으로 4px -> 10px로 넓혔다.
  5. 재생 시 쓰는 체크박스(텍스트 정지/정지/옵션정지/PG 매칭)가 체크되면 눈에 띄도록, 체크 시 인디케이터를 초록으로 채우고 글자도 굵은 초록으로 바꾸는 전용 스타일(`PLAYBACK_CHECKBOX_STYLE`)을 추가했다.
  6. 공구 리스트 표가 패널 폭보다 넓어 가로 스크롤바가 생기던 문제 — 표 폰트/셀 폭이 현재 패널 폭에 맞춰 가변으로 줄어들거나(최대 v1.6.2의 15%-축소 기준 크기까지) 늘어나도록 `App._relayout_tool_table()`을 추가하고, 새 `ToolTableWidget`(자체 `resized` 시그널)으로 표 크기가 바뀔 때마다(스플리터 드래그 포함) 자동으로 다시 계산한다.
  7. ISO 버튼을 누르면 좌표가 화면 중앙에 오도록(v1.6.2) 했던 동작에 더해, 로드된 경로 전체가 화면 안에 다 들어오도록 카메라 거리도 자동으로 맞춘다(줌 전체 보기, `_zoom_to_fit_distance()`).
  8. 위 줌 전체 보기 + 좌표 중앙 정렬 동작을 ISO뿐 아니라 XY/XZ/YZ 4개 투영 버튼 모두에 동일하게 적용한다(요청: "투영 아이콘 4가지 전부 같은 기능으로").
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **다크모드 아이콘 색 고정(`nc_viewer_widget.py`, `_refresh_dark_mode_button`):** `icon_color = "#e4e8f0" if self._dark_mode else "#1f2937"` -> 고정값 `"#f2f5fa"`.
  - **큐브 UI 축소(`nc_viewer_widget.py`, `NCViewerWidget._build_ui`):** `cube_font`를 `QFont("맑은 고딕", 14)`에서 `setPointSizeF(14 * CONTROL_SHRINK)`로, `view_cube_size_slider`/`view_cube_size_label` 고정폭을 `shrink(135)`/`shrink(57)`로 변경. `view_cube_size_slider`의 `range(60, 240)`과 `self._initial_cube_size` 초기값은 그대로.
  - **좌표 오버레이(`nc_viewer_widget.py`):** 새 `CoordOverlayWidget` 클래스(투명 배경, `QLabel { color: white }`, 값 라벨만 축별 인라인 색상). `OrthographicGLViewWidget.top_left_widget`(단일 위젯)을 `top_left_widgets`(목록)로 리팩터링해 좌표(위)·투영(아래) 오버레이를 위→아래로 쌓는다(`_reposition_top_left`, `TOP_LEFT_OVERLAY_STACK_GAP_PX=6`). `NCViewerWidget._build_coord_overlay()`가 실패해도 뷰어 전체를 잃지 않도록 try/except로 감쌌고, `self.coord_labels`가 비어 있어도 `_set_coordinate_labels()`가 안전하게 동작하도록 `.get(axis)` 가드를 추가했다.
  - **투영 버튼 간격(`nc_viewer_widget.py`, `ProjectionOverlayWidget`):** `row.setSpacing(4)` -> `10`, "투영" 라벨과 첫 버튼 사이에 `addSpacing(4)` 추가.
  - **재생 체크박스 스타일(`NC_Tool_List.py`):** 새 상수 `PLAYBACK_CHECKBOX_STYLE`(`QCheckBox::indicator:checked { background: #2ecc71; ... }`, `QCheckBox:checked { color: #1e9e5a; font-weight: 700; }`)을 `stop_text_check`/`stop_m00_check`/`stop_m01_check`/`pg_match_check`에 적용.
  - **공구 리스트 표 반응형(`NC_Tool_List.py`):** 새 `ToolTableWidget(QTableWidget)` 서브클래스(`resized` 시그널을 `resizeEvent`에서 emit — `QSplitter.splitterMoved`는 `setSizes()` 같은 프로그램적 크기 변경에는 발생하지 않아 이 경로가 필요했다). 새 `App._relayout_tool_table()`이 `table.viewport().width()`와 `_COL_WIDTH_TOTAL`(모든 COL_WIDTH의 합, 새 모듈 상수)의 비율로 스케일(`TOOL_TABLE_MIN_SCALE=0.45` ~ `1.0`으로 클램프)을 구해 폰트(`TABLE_FONT_PT * scale`)와 각 열 폭(`int(COL_WIDTH[key] * scale)`, 반올림이 아니라 내림 — 합계가 available을 넘지 않도록)을 다시 설정하고 `resizeRowsToContents()`로 행 높이도 갱신한다. `self.table.resized`와 `App.resizeEvent`(신규 오버라이드) 양쪽에서 호출하고, `run()` 끝에서도 한 번 호출한다.
  - **줌 전체 보기(`nc_viewer_widget.py`, `NCViewerWidget`):** 새 `_zoom_to_fit_distance()`가 `gl_view.scene_radius`(경로 전체를 감싸는 구 반지름)와 현재 뷰포트 종횡비·FOV로부터, 두 방향(가로/세로) 모두 경로가 잘리지 않는 최소 거리에 여유 배율(`_ZOOM_TO_FIT_MARGIN=1.25`)을 곱해 반환한다(경로가 없으면 `None` -> 기존 고정값 200 사용). `set_camera_projection()`이 이제 4개 뷰 타입 모두에서 이 거리와 `recenter=True`를 함께 쓴다(v1.6.2에서는 ISO만 recenter했다).
- Verification: 98 unit tests passed (기존 91개 + v1.6.3 신규 7개: 다크모드 아이콘 색 고정, 큐브 UI 축소, 투영 버튼 간격, 좌표 오버레이 투명·흰색 축 글자, 4개 투영 버튼 리센터+줌 전체 보기, 재생 체크박스 스타일, 표 반응형 축소). `pytest tests/test_nc_tool_list.py` 98/98 통과. 1920x1080으로 실제 창을 띄워 라이트/다크 테마 모두에서 스크린샷으로 다크모드 아이콘·좌표 오버레이·체크박스 스타일을 육안 확인했고(라이트 테마에서 기존에는 아이콘이 상단 바와 거의 같은 색이라 사실상 안 보였던 것을 확인 후 수정), 카메라를 팬(pan)한 뒤 ISO/XY/XZ/YZ 각각을 눌러 `gl_view.opts['center']`가 매번 원점으로 돌아오고 `distance * tan(fov/2) >= scene_radius`(경로 전체가 화면 안에 들어옴)를 만족하는 것을 스크립트로 검증했다. 표 반응형도 뷰포트 폭을 좁혔다 넓혔다 하며 가로 스크롤바가 한 번도 나타나지 않는 것을 확인했다. 프리즈된 exe도 직접 실행해 `startup.log`에 트레이스백 없이 `Starting Sum Path v1.6.3 frozen=True`가 찍히는 것을 확인한 뒤 정상 종료시켰다.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.6.3.exe` and `installer/NC_Tool_List_Portable_v1.6.3.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec; `version_info.txt` and `NC_Tool_List.iss`'s `MyAppVersion` bumped to 1.6.3 so the built exe's version resource reads `1.6.3.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.6.2 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 87A03423C834B5CE84E0790176A7055951ED0AA44297445133CD73B0E759B58B
- Portable ZIP SHA-256: 00D422E0F133E549FD8192414EB658531916585A565265042ADEEE654957ED89
- App SHA-256: CAF739E94726BAEF491318C7BD63C0D07B151953306530CC6E0770A79CE5EC4F
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; merging into `agent/drag-drop-installer`; the exe filename/install directory/Start-Menu display name/file-association ProgId (still "NC Tool List"/"NC_Tool_List"); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support; the `ViewerFallbackWidget` fallback screen; the magnifier lens (still fixed 220px/3x); the "큐브" 슬라이더 범위(60~240)와 3D 큐브 위젯 자체의 기본 크기(사용자가 명시적으로 손대지 말라고 요청). **v1.6.2's installer/ZIP should be treated as superseded and not distributed** — the 8 fixes above are not in it.

### 2026-09-05 (v1.6.2)

- Version: 1.6.2
- Release/build date: 2026-09-05
- Summary: 1920x1080 실사용 피드백 8건:
  1. **Bug fix**: 프로그램 입력 패널을 최소 폭까지 좁히면 '지우기'~'Tool List' 버튼 줄(합계 필요폭 506px)이 다 들어가지 못해 'Tool List' 버튼이 가려지던 문제 — `PROGRAM_PANE_MIN_WIDTH`를 430 -> 520px로 늘려 고쳤다.
  2. 다크/라이트 모드 토글 버튼을 뷰어의 감도/큐브 바에서 앱 상단 바(모드 전환 버튼들 뒤, 창 오른쪽 끝에서 한 칸 띄운 위치)로 옮겼다. `NCViewerWidget.take_dark_mode_button()`으로 버튼을 재부모화하되 시그널 연결과 다크모드 상태는 그대로 유지한다.
  3. 재생바(속도바/재생·되감기·이전툴·다음툴 버튼)와 감도 슬라이더/라벨, 다크모드 아이콘을 기존 대비 40% 축소(`CONTROL_SHRINK=0.6`) — 1920x1080 모니터에서 컨트롤이 지나치게 크다는 피드백 반영. **큐브 슬라이더/라벨과 3D 오리엔테이션 큐브 자체는 사용자가 명시적으로 손대지 말라고 요청해 그대로 두었다.**
  4. 투영(ISO/XY/XZ/YZ) 표기부를 뷰어 상단의 별도 행에서 3D 화면 왼쪽 위의 반투명 오버레이(`ProjectionOverlayWidget`)로 옮겨, 그 자리에 있던 공구 경로가 버튼 사이로 비쳐 보이게 했다.
  5. ISO 버튼을 클릭하면 카메라 방향뿐 아니라 카메라 중심(pos)도 원점으로 되돌려, 드래그로 치우쳐 있던 좌표가 화면 정중앙으로 다시 오게 했다(`set_camera_angles(recenter=True)`, ISO 클릭에만 적용).
  6. "툴리스트 산출 모드"/"Viewer 모드" 버튼의 패딩을 "도움말"/"About" 버튼과 같은 4px 8px로 맞췄다(기존 7px 12px로 더 컸다).
  7. "텍스트 정지"~"공정별 경로 필터 선택"~"PG 매칭/전체/해제" 구간의 레이아웃과 폰트를 15% 키웠다(`FILTER_SECTION_SCALE=1.15`).
  8. 공구 리스트(복사용 표기) 표의 폰트 크기와 셀 폭을 15% 줄였다(`COPY_TABLE_SCALE=0.85`) — v1.5.9에서 1.6배로 키운 값 기준.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **최소 폭(`NC_Tool_List.py`):** `PROGRAM_PANE_MIN_WIDTH = 520`(계산 근거: 버튼 합 468px + 간격 24px + 좌우 여백 14px = 506px, 여기에 여유를 둠). `MAIN_SPLITTER_INITIAL_SIZES`가 이 상수를 그대로 참조하므로 초기 창 폭도 함께 90px 늘었다.
  - **다크모드 버튼 이동(`nc_viewer_widget.py`, `NCViewerWidget`):** 새 `take_dark_mode_button(new_parent)`가 버튼을 `setParent()`로 옮기고 `show()`한다 — 뷰어 쪽 `view_bar` 레이아웃에는 더 이상 추가하지 않고 `hide()` 상태로만 만들어 둔다. (`NC_Tool_List.py`, `App._build_ui`): `self.viewer = self._create_viewer()` 직후 `hasattr(self.viewer, 'take_dark_mode_button')`를 확인해 상단 바 `top_layout`에 `addStretch()` 다음으로 추가하고, 새 상수 `TOP_BAR_EDGE_GAP_PX=8`만큼 오른쪽 가장자리에서 띄운다.
  - **컨트롤 40% 축소(`nc_viewer_widget.py`):** 새 `CONTROL_SHRINK=0.6`과 헬퍼 `shrink(value)`. `PlaybackBarWidget`의 스타일시트(패딩/폰트/슬라이더 두께/버튼 아이콘)와 바 폭 비율(`_BOTTOM_BAR_WIDTH_RATIO`: 0.7 -> 0.42, 버튼이 가로로 늘어나는 위젯이라 폭도 같은 비율로 줄여야 실제 버튼 크기가 줄어든다), 감도 슬라이더/라벨 폭·폰트, `DARK_MODE_BUTTON_PX = round(52 * 0.6) = 31`에 모두 적용. "큐브" 라벨/슬라이더는 별도 `cube_font`/고정폭(135/57px, 14pt)으로 분리해 손대지 않았다.
  - **투영 오버레이(`nc_viewer_widget.py`):** 새 `ProjectionOverlayWidget`(반투명 배경, 버튼만 옅은 배경) — `gl_view.top_left_widget`으로 등록하고 `_reposition_top_left()`가 화면 왼쪽 위 모서리(10px 여백)에 고정한다. `NCViewerWidget._build_projection_overlay()`가 실패해도 뷰어 전체를 잃지 않도록 try/except로 감쌌다(다른 오버레이들과 같은 패턴).
  - **ISO 리센터(`nc_viewer_widget.py`):** `set_camera_angles(elevation, azimuth, distance=None, recenter=False)`에 `recenter=True`면 `pos=Vector(0,0,0)`을 `setCameraPosition()`에 함께 넘기는 분기 추가. `set_camera_projection()`이 `view_type == "ISO"`일 때만 `recenter=True`로 호출한다.
  - **모드 버튼 패딩(`NC_Tool_List.py`, `App._style_mode_buttons`):** `padding: 7px 12px` -> `4px 8px`(전역 QPushButton 기본값과 동일, `_build_global_stylesheet` 참고).
  - **필터 섹션 15% 확대(`NC_Tool_List.py`):** 새 상수 `FILTER_SECTION_SCALE=1.15`와 헬퍼 `scaled(value)`. `filter_layout`의 margin/spacing, `stop_bar`/`filter_bar`의 spacing, 새 `filter_kfont`(kfont 10pt * 1.15)를 텍스트 정지/정지/옵션정지/Reset/PG 매칭/전체/해제 체크박스·버튼에, `filter_label_font`(9pt * 1.15, Bold)를 "공정별 경로 필터 선택" 라벨에, `stop_text_input`의 고정폭(120 -> 138)에 적용했다. `tool_filter` 리스트 자체 폰트(10pt Bold)는 대상 범위 밖이라 그대로 뒀다.
  - **공구 리스트 표 15% 축소(`NC_Tool_List.py`):** 새 상수 `COPY_TABLE_SCALE=0.85`, `TABLE_FONT_PT = 14 * 0.85`, `TABLE_CELL_PADDING_PX = round(8 * 0.85) = 7`(패딩도 같은 비율로 줄여 칸 폭이 정확히 15% 작아지게 함). `COL_WIDTH = {key: round(width * 0.85) + TABLE_CELL_PADDING_PX * 2 ...}`. `self.table`/헤더 폰트를 `setPointSizeF(TABLE_FONT_PT)`로 설정.
- Verification: 91 unit tests passed (기존 90개 중 1개를 새 동작에 맞게 갱신 — `test_dark_mode_button_and_icon_enlarged`를 `test_dark_mode_button_size_matches_v162_shrink`/`test_dark_mode_button_moves_to_app_top_bar`로 분리, `test_tool_list_table_cells_and_font_scaled_1_6x`를 `..._then_shrunk_15pct`로 갱신; 신규 1개 순증). `pytest tests/test_nc_tool_list.py` 91/91 통과. 실제 창을 1920x1080으로 띄워 툴리스트 모드/뷰어 모드를 스크린샷으로 육안 확인했고, 카메라를 팬(pan)으로 원점에서 치우친 뒤 ISO 버튼을 눌러 `gl_view.opts['center']`가 `(400, 250, 0)` -> `(0, 0, 0)`으로 정확히 복귀하는 것을 스크립트로 검증했다. 프리즈된 exe(`dist/NC_Tool_List/NC_Tool_List.exe`)도 직접 실행해 `startup.log`에 트레이스백 없이 `Starting Sum Path v1.6.2 frozen=True`가 찍히는 것을 확인한 뒤 정상 종료(`taskkill`)시켰다.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.6.2.exe` and `installer/NC_Tool_List_Portable_v1.6.2.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec; `version_info.txt` and `NC_Tool_List.iss`'s `MyAppVersion` bumped to 1.6.2 so the built exe's version resource reads `1.6.2.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.6.1 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 2D26B37CF8C986AF1F70C63608E9983AA6C6BEE75BF7352BCFBACF7E12FDF601
- Portable ZIP SHA-256: BF313368605B588E27560A08E38C3F268FB28FC1D3C5CE933C2454A71FB049E2
- App SHA-256: 0BB515843414835272A901C0C0B31BF3308449C29FB865DEEA94773B6435BBFF
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; git commit/push for this release step itself (the UI-change commit from the prior turn was already pushed to `feat/pg-match-mode` at the user's request; this version-bump + installer commit follows the same branch); merging into `agent/drag-drop-installer`; the exe filename/install directory/Start-Menu display name/file-association ProgId (still "NC Tool List"/"NC_Tool_List"); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support; the `ViewerFallbackWidget` fallback screen; the magnifier lens (still fixed 220px/3x); the "큐브" orientation-cube slider/label and the 3D cube widget itself (explicitly excluded from the 40% shrink per user request). **v1.6.1's installer/ZIP should be treated as superseded and not distributed** — the 8 fixes above are not in it.

### 2026-09-05 (v1.6.1)

- Version: 1.6.1
- Release/build date: 2026-09-05
- Summary: 5 fixes/additions found after actually using v1.6.0:
  1. **Bug fix**: in light mode the playback (speed) bar and its text were invisible — the app-wide theme stylesheet's `QWidget { background: ... }` rule (a Qt type selector matches subclasses) was painting an opaque light background over the bar's child `QLabel`/`QSlider` widgets, while the bar's own sheet still forced `color: white` — white text on a near-white background. Fixed by giving the bar's own stylesheet explicit `background: transparent` rules for its children plus a full `QSlider` groove/handle style, so the bar always renders with its dark design regardless of app theme (it always floats over the always-dark 3D canvas anyway).
  2. The origin's +X/+Y/+Z arrows now render at a **screen-fixed size equal to the orientation cube's pixel size** (previously scaled with the cube but in world units, so zooming in/out changed their apparent size) — computed via the orthographic projection's world-units-per-pixel; resizing the cube slider resizes the arrows identically. Line thickness doubled (2.0 -> 4.0). Each arrow tip now shows its axis letter (X/Y/Z) via `pyqtgraph.opengl.GLTextItem`, sized with the same ratio the view cube uses for its own face labels, so both stay visually consistent and both scale together with the cube-size slider.
  3. New global shortcuts: **F5** Reset (cursor to line 0), **F6** previous tool, **F7** play/pause toggle, **F8** next tool — work regardless of which widget has focus; F6/F8 do nothing outside Viewer + PG 매칭 mode (matching the existing playback-bar behavior).
  4. A new **도움말** (Help) button next to About opens a separate scrollable popup listing shortcuts and every notable interactive feature actually implemented in the app (drag ring, magnifier, PG 매칭 auto-playback, filters, etc.).
  5. The dark/light mode toggle icon doubled again, this time to exactly 2x (26px -> 52px button/icon); the toolbar row's top/bottom margins were trimmed (5px -> 0px) to limit the resulting row-height growth to +6px (46 -> 52px) instead of the full +16px.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Playback bar theme fix (`nc_viewer_widget.py`, `PlaybackBarWidget.__init__`):** added `QLabel { background: transparent; ... }`, a new `QSlider { background: transparent; }` block plus `QSlider::groove/sub-page/handle:horizontal` rules (translucent white groove, blue sub-page, light handle sized for the bar's 68px-tall slider), and `background: transparent` on `speed_value_label`'s instance stylesheet (instance styles win outright, so this was the one place the app-theme leak couldn't be blocked by the bar's own class-level rules alone).
  - **Screen-fixed origin arrows (`nc_viewer_widget.py`, `NCViewerWidget`):** `_AXIS_ARROW_BASE_LENGTH` (a fixed 500.0 world-unit constant) removed; new `_screen_units_per_pixel()` derives `2 * opts['distance'] * tan(radians(opts['fov'])/2) / gl_view.height()` (the same formula `OrthographicGLViewWidget.projectionMatrix()` uses internally) and `_axis_arrow_length()` returns `cube_size_px * units_per_pixel`. New `_axis_label_font()` mirrors `ViewCubeWidget._paint()`'s label ratio (`half * 7.2/26.0`, `half = (cube_px/2) * 0.65`) so cube and axis-letter fonts move together. `_add_axis_lines()` now also creates one `gl.GLTextItem` per axis (color converted from the existing 0–1 float RGBA to 0–255 ints, since `GLTextItem` requires that or a `QColor`); a new `_update_axis_lines_live()` is connected to `gl_view.camera_changed` and updates existing items' `pos`/`font` via `setData(...)` (no add/remove per frame) so the fixed-size effect tracks zooming smoothly. `_remove_axis_lines()` also clears the new `_axis_label_items` list.
  - **Shortcuts (`NC_Tool_List.py`):** `QShortcut`/`QKeySequence` added to the existing try/except Qt import block; new `App._install_shortcuts()` (called right after `_build_ui()`) wires F5/F6/F7/F8 with the default `Qt.WindowShortcut` context (not `ApplicationShortcut`, so they don't fire behind a modal About/Help dialog the way the viewer's Escape shortcut intentionally does). New `App.toggle_playback()` checks `self.play_timer.isActive()` — the same single source of truth existing tests already assert on — rather than adding a separate boolean flag. `_jump_relative_tool()` (backing F6/F8 and the playback-bar's prev/next-tool buttons) gained the same `current_mode != 'viewer' or not pg_match_mode` guard `start_playback()` already had, since it previously moved the cursor even in 툴리스트 모드. Reset/재생/이전툴/다음툴 tooltips now mention their shortcut keys.
  - **Help dialog (`NC_Tool_List.py`):** new `self.btn_help` in the top bar (same font as About/모드 buttons, placed between About and the mode-button gap). New `show_help()` copies `show_type_list()`'s resizable-dialog pattern (`resize(560, 640)`, a stretch-1 content widget, a plain Close button) with a read-only `QTextEdit` (scrollbars left on, unlike the About box) filled from a new `HELP_TEXT` constant — written strictly from the actually-implemented feature set (verified against the code, nothing invented).
  - **2x dark-mode icon (`nc_viewer_widget.py`):** `dark_mode_button.setFixedSize(36,36)` -> `(52,52)`; `_refresh_dark_mode_button()`'s `sun_icon`/`moon_icon(..., size=26)` -> `size=52`, `setIconSize` -> `QSize(52,52)`; `view_bar.setContentsMargins(6,5,6,5)` -> `(6,0,6,0)` to cap the row-height increase at +6px.
- Verification: 90 unit tests passed (88 pre-existing + 2 updated: the dark-mode button/icon size assertions now expect 52px, and the top-bar widget-order test now expects `[btn_about, btn_help, btn_tool_mode, btn_viewer_mode]`). A real bug was caught and fixed during this verification pass itself — the first `_update_axis_lines_live()` implementation had an off-by-one in its flat index into `_axis_items` (it never advanced past each axis's trailing `GLTextItem` slot before moving to the next axis's shaft), which surfaced as a `ValueError` from `GLTextItem.setData` during the existing `test_top_caption_removed_and_top_bar_buttons_left_aligned` test's teardown (a queued camera-changed signal firing during `processEvents()`); fixed by adding the missing `index += 1` after each axis's label update. Ran `pytest tests/test_nc_tool_list.py` to a clean 90/90 afterward. Also ran the app directly (`python NC_Tool_List.py`) and the freshly built frozen exe separately: both `startup.log` entries showed a clean `Starting Sum Path v1.6.1 frozen=False/True` line with no traceback, and both processes stayed running until explicitly stopped. As with v1.6.0, this was a headless/no-display session — visual confirmation of the light-mode playback bar's readability, the arrows' on-screen size matching the cube across zoom levels, the X/Y/Z label legibility, and the toolbar's new row height is left for the user to spot-check.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.6.1.exe` and `installer/NC_Tool_List_Portable_v1.6.1.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec; `version_info.txt` and `NC_Tool_List.iss`'s `MyAppVersion` bumped to 1.6.1 so the built exe's version resource reads `1.6.1.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.6.0 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 632D127D7B32B9660D7039035E2E661D23768D7AE5958389B1A7B23C473E2022
- Portable ZIP SHA-256: A48DF257E9457992668256AD5D1B9E57D79FCB79AAB703A2C3268E8602FE7F95
- App SHA-256: 54F5E0A38F7DD5757549E2FDE2DC277BC4B2B01872006D855B5FEB0C8C1A91CB
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; git commit/push/merge for this release (deferred until the user asks, matching the v1.6.0 pattern — changes exist only in this worktree pending review); the exe filename/install directory/Start-Menu display name/file-association ProgId (still "NC Tool List"/"NC_Tool_List"); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support; the `ViewerFallbackWidget` fallback screen (intentionally light-only); the magnifier lens (still fixed 220px/3x); giving the play/pause button's tooltip/icon a live "지금 재생 중" vs "정지" state (it still always shows "재생 (F7)" — out of scope, not asked for); code-level i18n of the new Help text (Korean only, matching the rest of the UI). **v1.6.0's installer/ZIP should be treated as superseded and not distributed** — the light-mode playback-bar fix, screen-fixed labeled origin arrows, F5–F8 shortcuts, Help popup, and 2x dark-mode icon described above are not in it.

### 2026-09-05 (v1.6.0)

- Version: 1.6.0
- Release/build date: 2026-09-05
- Summary: 11 UI/UX refinements requested together, split across the tool-list panel and the 3D viewer:
  1. In the copy-list row ("② 공구 리스트 (복사용)"), the buttons up through 표 복사 (삭제/수정/＋ 행 추가/이름 경우의 수/머리글 포함/PDF 출력/표 복사) got a 1.3x font and larger padding.
  2. The 툴리스트 산출 모드/Viewer 모드 buttons in the top bar now sit ~5cm (96DPI-assumed) further from the About button, keeping visual distance from the machine-panel's ▶/▼ collapse toggle lower in the layout.
  3. The copy-list table's cell width was widened by a half-character's worth of padding on each side (via a new `QTableWidget::item` padding rule) so text is no longer flush against the cell edge.
  4. The "장비 타입 및 스펙 설정" panel and the "다음공구검색" row swapped vertical order (machine settings now above the search row).
  5. Dark mode is now the default theme for a fresh install (previously light); existing users' saved choice is unaffected.
  6. The About dialog's 용도/오픈소스 description box no longer shows a vertical scrollbar — its height is computed from actual content instead of a fixed 150px cap.
  7. The viewer's ISO/XY/XZ/YZ projection buttons and the orientation cube's own XY/-XY/XZ/-XZ/YZ/-YZ face labels got their font shrunk 0.8x; borders/outlines are unchanged.
  8. The "좌표" coordinate box keeps its existing font and text position but gained extra empty space below it (height 70 -> 92, via a `QVBoxLayout` + trailing stretch instead of vertical centering).
  9. The orientation cube's drag ring got thicker (width ratio 0.22 -> 0.36, tick marks 0.14 -> 0.22) and the cube itself is now 50% translucent by default, becoming fully opaque while the ring is being dragged.
  10. The playback speed bar doubled in thickness (34px -> 68px) and its speed value label's font grew 1.7x (15px -> 26px, isolated to that one label).
  11. Alt+wheel over the 3D viewer now adjusts the 감도 (sensitivity) slider directly; Ctrl+wheel's existing FOV-zoom behavior is untouched.
  - Also: the 3D scene's origin marker changed from two infinite bidirectional lines per axis to short +X/+Y/+Z arrows (with a simple 4-line chevron head), whose length now scales with the orientation cube's size slider instead of being a fixed huge constant.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Copy-row buttons 1.3x (`NC_Tool_List.py`):** new `_style_accent_button_large`/`_style_success_button_large` wrap the existing `_style_accent_button`/`_style_success_button` (used elsewhere by `run_button`, left untouched) and append `padding: 7px 12px`; a local `row_button_font = QFont('맑은 고딕', 13)` and `row_button_style = 'padding: 5px 10px;'` are applied to the plain buttons/checkbox in the same row.
  - **Mode-button gap (`NC_Tool_List.py`):** `MODE_BUTTON_GAP_PX = round(5 * 96.0 / 2.54)` inserted via `top_layout.addSpacing(...)` between `btn_about` and `btn_tool_mode`.
  - **Table cell padding (`NC_Tool_List.py`):** new `TABLE_CELL_PADDING_PX = 8` constant; `COL_WIDTH` is now derived from a renamed `_COL_WIDTH_BASE` dict plus `TABLE_CELL_PADDING_PX * 2` per column (so the padding doesn't shrink the visible text area); `_build_global_stylesheet` adds `QTableWidget::item { padding: 0 8px; }`.
  - **Search/machine-panel swap (`NC_Tool_List.py`):** the two `left_layout.addWidget/addLayout` calls for `machine_settings_panel` and `search_bar` were reordered (no other logic changed).
  - **Dark mode default (`NC_Tool_List.py`):** `_load_dark_mode`'s `QSettings.value('dark_mode', False)` default changed to `True`.
  - **About dialog auto-height (`NC_Tool_List.py`):** `viewer.setMaximumHeight(150)` removed; the box's scrollbars are explicitly turned off and its height is computed via `viewer.document().setTextWidth(480)` + `document().size().height()`. `dialog.resize(520, 600)` was replaced with `dialog.setFixedWidth(520)`, letting the dialog's height follow its layout's `sizeHint()`.
  - **Projection/cube-label font 0.8x (`nc_viewer_widget.py`):** toolbar `projection_font` 13pt -> 10pt; `ViewCubeWidget`'s face-label point-size ratio `9.0/26.0` -> `7.2/26.0` (border/outline `pen_width` untouched).
  - **Coordinate box bottom margin (`nc_viewer_widget.py`):** `coord_group`'s layout changed from a bare `QHBoxLayout` to an outer `QVBoxLayout` holding the original `coord_layout` row plus a trailing `addStretch()`; `setFixedHeight` 70 -> 92.
  - **Cube ring/translucency (`nc_viewer_widget.py`, `ViewCubeWidget`):** ring pen-width ratio 0.22 -> 0.36, tick ratio 0.14 -> 0.22; face `QColor` brushes gained an alpha channel driven by a new `face_alpha = 255 if self._ring_dragging else 128` (the existing `_ring_dragging` flag, previously only used for ring/tick color, now also gates cube opacity).
  - **Playback bar size (`nc_viewer_widget.py`, `PlaybackBarWidget`):** `speed_slider.setFixedHeight` 34 -> 68; `speed_value_label` now carries its own instance-level stylesheet (`font-size: 26px`) instead of inheriting the bar's shared `QLabel { font-size: 15px }` rule, so only that label grew; its fixed width grew 72 -> 122 to fit the larger "5000x" text.
  - **Alt+wheel sensitivity (`nc_viewer_widget.py`):** `OrthographicGLViewWidget` gained `self.alt_wheel_callback` (set by `NCViewerWidget` to a new `_on_alt_wheel_sensitivity` method); `wheelEvent` checks `Qt.AltModifier` first and, if the callback is set, delegates to it and returns before touching `distance`/`fov` — Ctrl+wheel's branch is unmodified. The callback nudges `sensitivity_slider`'s value by ±5 per notch, clamped to its existing 5–200 range; the slider's own `valueChanged` -> `_on_sensitivity_changed` still does the actual `navigation_sensitivity`/`QSettings` update, so no logic was duplicated.
  - **Origin arrows (`nc_viewer_widget.py`):** `_add_axis_lines` was rewritten to draw one `GLLinePlotItem` shaft per +X/+Y/+Z direction (length = `_AXIS_ARROW_BASE_LENGTH (500.0) * (cube_size_px / 160.0)`) plus 4 short chevron-wing segments per axis at the tip; all created items are tracked in `self._axis_items` and cleared by a new `_remove_axis_lines()` before each rebuild. `_on_view_cube_size_changed` now also calls `_add_axis_lines()` so dragging the 큐브 크기 slider live-resizes the arrows.
- Verification: 90 unit tests passed (87 pre-existing + 3 updated for the new intended behavior: `test_tool_list_table_cells_and_font_scaled_1_6x` now expects `COL_WIDTH` values plus `TABLE_CELL_PADDING_PX * 2`; `test_dark_mode_toggle_switches_theme_and_persists` and `test_viewer_dark_mode_button_click_notifies_app` now start from the new `'dark'` default and toggle to `'light'` instead of the old light-default/toggle-to-dark direction — the toggle/persistence mechanism itself is unchanged and still covered). Ran `pytest tests/test_nc_tool_list.py` once green (90/90) after the fixes (pytest was not previously installed for this Python interpreter and was added via `pip install --user pytest` to run the suite; no project dependency was added). Also ran the app directly (`python NC_Tool_List.py`) and separately launched the freshly built frozen exe: both `startup.log` entries showed a clean `Starting Sum Path v1.6.0 frozen=False/True` line with no traceback, and both processes stayed running (not a crash-exit) until explicitly stopped. Visual/behavioral confirmation of each of the 11 items beyond the automated tests was not done in an interactive session (no display attached to this run) — the app was only confirmed to start and stay up without errors; the user should spot-check the visual sizing/spacing values (font points, pixel gaps, ring thickness) against their own screen/DPI and report any that need further adjustment.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.6.0.exe` and `installer/NC_Tool_List_Portable_v1.6.0.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec; `version_info.txt` and `NC_Tool_List.iss`'s `MyAppVersion` were also bumped to 1.6.0 so the built exe's version resource reads `1.6.0.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.10 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 897AB63DDCC283546FAB16FC572BEDB91EAB1E3901047DDA0755E3785712DA03
- Portable ZIP SHA-256: 3D418F168365A1C3B5CCCD5926CDD60E002D8062526562268771C5CF583D91BE
- App SHA-256: 0B3750620B31B2D44F496422948FBC82B2D69C8284F7EED861B5FC6E5946FE6A
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; git commit/push for this release (explicitly deferred by the user's request — changes exist only in this worktree pending review); the exe filename/install directory/Start-Menu display name/file-association ProgId (still "NC Tool List"/"NC_Tool_List"); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support; the `ViewerFallbackWidget` fallback screen (intentionally light-only); the magnifier lens (still fixed 220px/3x); an actual 3D cone/mesh arrowhead for the origin marker (used a simple 4-line chevron instead, drawn with the same `GLLinePlotItem` primitive already used elsewhere in this file); exact real-world scaling of the origin arrow's length (it's tied to the cube-size slider's pixel value via an arbitrary constant, not to the loaded program's actual physical dimensions). **v1.5.10's installer/ZIP should be treated as superseded and not distributed** — the 11 UI refinements and origin-arrow change described above are not in it.

### 2026-09-05 (v1.5.10)

- Version: 1.5.10
- Release/build date: 2026-09-05
- Summary: Implements v1.5.9's deferred item 3 — a draggable ring around the 3D viewer's orientation cube (ViewCubeWidget), confirmed by the user (after an AskUserQuestion clarification) to be a ring that can be dragged for smooth camera rotation, as opposed to the cube's existing instant-snap-on-click faces.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Drag ring (`nc_viewer_widget.py`, `ViewCubeWidget`):** a circular ring (with four small cross-shaped tick marks at 0°/90°/180°/270° for grip affordance) is now painted in the annulus between the cube's outer radius (`half`) and the widget's own bounding radius (`raw_half`), recomputed every `_paint()` call and stored as `_ring_inner_radius`/`_ring_outer_radius`. `mousePressEvent()` still checks cube face polygons first (unchanged snap-on-click behavior); a miss that lands within the ring band (`_ring_hit()`) now starts a drag (`_ring_dragging=True`) instead of falling through to a no-op. New `mouseMoveEvent()`/`mouseReleaseEvent()` overrides: while dragging, each mouse move calls `gl_view.orbit(-dx * sensitivity, dy * sensitivity)` — the same sign convention and `navigation_sensitivity` scaling pyqtgraph's own `GLViewWidget.mouseMoveEvent()` uses for a plain viewport drag, so the ring feels identical in direction/speed to dragging the 3D view itself — and manually emits `gl_view.camera_changed` (since `orbit()` mutates `opts` directly without going through `setCameraPosition()`, which is what normally fires that signal), so other camera-reactive overlays (the magnifier lens) keep working correctly during a ring drag. The ring is drawn slightly brighter/highlighted while actively being dragged. The widget's tooltip was updated from "드래그: 회전 | 면 클릭: 해당 뷰로 전환" to "고리 드래그: 부드럽게 회전 | 큐브 면 클릭: 해당 뷰로 즉시 전환" to describe the actual two distinct interactions.
- Verification: 91 unit tests passed (90 existing from v1.5.9 + 1 new: a synthetic press/move/release sequence on a point inside the ring band confirms `_ring_dragging` toggles correctly, `face_clicked` never fires during the drag, and `gl_view.opts['azimuth']`/`['elevation']` change by a bounded, non-snapping amount). Ran the full suite twice in a row (both 91/91 green) to rule out interaction with the earlier splitter-test flake fix. Also built and launched the actual frozen exe: `startup.log` showed a clean `Starting Sum Path v1.5.10 frozen=True` line with no traceback, and the process stayed running (not a crash-exit) for several seconds until explicitly stopped.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.10.exe` and `installer/NC_Tool_List_Portable_v1.5.10.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`upx=False` in the spec, built exe's version resource reads `1.5.10.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.9 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: DDA60AC1FF2DB9C4B9F4AC8D28EB99F8B39C677B3F9F91ED227F6AA39B33F1DA
- Portable ZIP SHA-256: 885C94E4E7605F70B4807D3A340FB2B5CC517DAB8D1DCE12D0575640014D846A
- App SHA-256: 70BBC116817A72EC8B36BA9E5CAA09805CD540644883EF5855F2F7A0D0576B4B
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; the exe filename/install directory/Start-Menu display name/file-association ProgId (still "NC Tool List"/"NC_Tool_List"); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support; a settings UI for cube face labels/colors or ring size/color; the `ViewerFallbackWidget` fallback screen (intentionally light-only); the magnifier lens (still fixed 220px/3x); the ring doesn't currently support Ctrl-modified pan the way the main viewport drag does (out of scope — the ring is orbit-only, matching what was asked). **v1.5.9's installer/ZIP should be treated as superseded and not distributed** — the drag-ring described above is not in it.

### 2026-09-04 (v1.5.9)

- Version: 1.5.9
- Release/build date: 2026-09-04
- Summary: Six of seven items the user requested after confirming v1.5.8's install (numbered 1/2/3/5/6/6/7 in the request, with two items both labeled "6"); item 3 (a proposed ring/compass control around the ViewCube) is deliberately **not** implemented this round — it's a substantial new interactive widget and the request text supports multiple designs, so it needs a quick confirmation before being built rather than a guess. Everything else:
  1. The program-input buttons (지우기/예제/파일 열기/PG ADD/Tool List), previously split across two rows, are now on one row.
  2. The "NC 프로그램을 넣고 공구 리스트를 생성하세요" caption next to the title was removed.
  3. *(reserved — see above; not implemented this round)*
  4. In the 3D viewer's toolbar: extra spacing was added between the 감도 and 큐브 slider groups (they were crowding together at the enlarged v1.5.8 sizes); the whole 감도+큐브+다크모드 button group was shifted left by ~2cm (a fixed trailing spacer, rather than sitting flush against the panel's right edge); the dark/light-mode toggle button and its icon were enlarged.
  5. The top bar's About/툴리스트 산출 모드/Viewer 모드 buttons moved from the far right (past a stretch) to sit right next to the title, and their font+padding were enlarged 1.3x.
  6. In the tool-list panel, the control buttons (삭제/수정/＋ 행 추가/이름 경우의 수/머리글 포함/PDF 출력/표 복사) moved from the panel's right edge to sit left, right after the count label.
  7. The tool-list table's column widths and font were enlarged 1.6x.
  - (Also addressed via a separate mid-turn request in the same session): auto-playback max speed raised again, 2000x → 5000x.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Program buttons merged to one row (`NC_Tool_List.py`):** `program_button_row1`/`program_button_row2` collapsed into a single `program_button_row` holding all five buttons in original left-to-right order, followed by one `addStretch()`.
  - **Caption removed (`NC_Tool_List.py`):** `self.top_caption` `QLabel` and its construction/`addWidget()` call deleted from the top bar; the now-unused `_style_header_caption()` helper and its call in `_apply_widget_themes()` were removed too (the `header_caption` theme tokens are left in `THEMES` as harmless unused entries).
  - **Top bar left-aligned + 1.3x (`NC_Tool_List.py`):** `top_layout.addStretch()` moved from before the About/mode buttons to after them; all three now share a new `top_bar_button_font = QFont('맑은 고딕', 12, QFont.Bold)` (was 9pt); `_style_mode_buttons()`'s inline padding raised `5px 9px` → `7px 12px` (same 1.3x ratio).
  - **Tool-panel controls left-aligned (`NC_Tool_List.py`):** in `_build_tool_panel()`'s `rbar`, `addStretch()` moved from right after the count label to after the last button (표 복사), so 삭제/수정/추가/이름경우의수/머리글/PDF/복사 now sit packed on the left.
  - **감도/큐브 spacing + 2cm left shift + dark-icon enlarge (`nc_viewer_widget.py`):** `view_bar.addSpacing(18)` inserted both between the 감도 value label and the 큐브 label, and between the 큐브 value label and the dark-mode button; a trailing `view_bar.addSpacing(round(2 * PX_PER_CM))` (reusing the existing `PX_PER_CM` constant) added after the dark-mode button so the whole 감도~큐브~다크모드 group sits ~2cm in from the panel's right edge instead of flush against it. `dark_mode_button` grew 26px → 36px, its icon 18px → 26px (`sun_icon`/`moon_icon` called with `size=26` so the source pixmap doesn't get blurrily upscaled).
  - **Tool-list table 1.6x (`NC_Tool_List.py`):** `COL_WIDTH` values all multiplied by 1.6 (e.g. `NO` 45→72, `HOLDER` 120→192); `self.table.setFont(QFont('맑은 고딕', 14))` and `self.table.horizontalHeader().setFont(QFont('맑은 고딕', 14, QFont.Bold))` added (row height grows automatically with Qt's font-driven default section size — no explicit row-height override needed).
  - **5000x speed cap:** both `MAX_PLAYBACK_SPEED` constants (in `NC_Tool_List.py` and `nc_viewer_widget.py`) bumped 2000 → 5000, matching the v1.5.7/v1.5.8 pattern.
  - **Test-suite flake fixed (`tests/test_nc_tool_list.py`):** `test_main_splitter_keeps_program_panel_minimum_width` intermittently failed depending on test execution order — `App.__init__`'s `QTimer.singleShot(0, self.showMaximized)` (queued whenever `restore_layout_settings()` finds no saved geometry, which is every test using a fresh settings dir) is not reliably cancelled by `deleteLater()`, and firing during a *different* test's `processEvents()` call maximizes that window onto the `QT_QPA_PLATFORM=offscreen` test platform's small fixed 800x600 virtual screen — smaller than the splitter's combined minimum widths, so `QSplitter` can't honor `PROGRAM_PANE_MIN_WIDTH` (430px) and falls back to an even split (396/396). Root-caused by direct reproduction (bisecting the exact 89-test alphabetical order down to a 2-test pair, then confirming the mechanism with `isMaximized()`/`availableGeometry()` prints). Fixed at the test level (the shipped app's behavior is unchanged) by flushing pending events and explicitly restoring the window to `showNormal()` + its intended `resize()` before asserting.
- Verification: 89 unit tests passed (85 existing from v1.5.8, 1 updated for the merged single-row buttons, + 4 new: caption removed / top-bar buttons ordered left of the trailing stretch; tool-panel control buttons packed left with only a trailing stretch; table column widths match the new `COL_WIDTH` 1.6x values and the table font is 14pt; the dark-mode button and its icon report the enlarged sizes). Ran the full suite twice in a row to confirm the splitter-test fix holds (both 89/89 green, no flake). Also built and launched the actual frozen exe: `startup.log` showed a clean `Starting Sum Path v1.5.9 frozen=True` line with no traceback, and the process stayed running (not a crash-exit) for several seconds until explicitly stopped.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.9.exe` and `installer/NC_Tool_List_Portable_v1.5.9.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`upx=False` in the spec, built exe's version resource reads `1.5.9.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.8 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 5558C35EB34F0A2C6B0360BD455B2436A1F17FFC26869A63F98BD92A1844843A
- Portable ZIP SHA-256: 6027AEC9D64ADA14126A3242374FE2E4EF48E1B046E71A93AD0C8B7B6D7188BB
- App SHA-256: 67EBC77AB3292229E09047B67ADE152909CCBBD2F7EEC4BFCE8B3E4155E1F1EB
- Signature status: still unsigned.
- Out of scope (left untouched this round, pending confirmation): **item 3 — a ring/compass-shaped control wrapped around the 3D-viewer's orientation cube, so that dragging/clicking the ring (not the cube itself) sets the camera direction without the abrupt "click near the cube and the render angle jumps" behavior the user described.** Also left untouched: actual code-signing; the exe filename/install directory/Start-Menu display name/file-association ProgId (still "NC Tool List"/"NC_Tool_List"); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support; a settings UI for cube face labels/colors; the `ViewerFallbackWidget` fallback screen (intentionally light-only); the magnifier lens (still fixed 220px/3x). **v1.5.8's installer/ZIP should be treated as superseded and not distributed** — the single-row program buttons, removed caption, left-aligned top-bar/tool-panel buttons with enlarged top-bar font, spaced-out and left-shifted 감도/큐브/다크모드 group with a bigger dark-mode icon, 1.6x tool-list table, and 5000x speed cap described above are not in it.

### 2026-09-04 (v1.5.8)

- Version: 1.5.8
- Release/build date: 2026-09-04
- Summary: Six follow-up requests on top of v1.5.7:
  1. The "투영"/"좌표" font+icon sizes from v1.5.7 (18pt/30px) felt too large — scaled down to 0.7x (13pt/21px); the "좌표" group's fixed height was reduced 100→70px to match.
  2. The "감도"/"큐브" labels and their slider bars, previously at the unset default font and 110px/90px widths, were scaled up 1.5x (14pt font; 165px/135px slider widths; value-label widths 38→57px).
  3. The app's main title (window title bar, in-app header label, About dialog heading, startup-log line) changed from "NC 공구 리스트 생성기" to "Sum Path" (`APP_NAME` constant) — the app's purpose text, exe filename, install folder, and file-association ProgId are unchanged (out of scope, see below).
  4. In the program-input row, "프로그램 추가" was renamed to "PG ADD" and "공구 리스트 생성" was renamed to "Tool List" ("지우기"/"예제"/"파일 열기" were left as-is — only these two were requested).
  5. Auto-playback max speed raised again, 2000x → 5000x.
  6. A new "Reset" button was added to the filter bar, immediately before the "PG 매칭" checkbox — it moves the program cursor straight to the top of the program (line 0), reusing the existing `jump_to_process_line(0)`.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **투영/좌표 0.7x (`nc_viewer_widget.py`):** `projection_font`/`coord_font` changed from `QFont('맑은 고딕', 18)` to `QFont('맑은 고딕', 13)`; ISO/XY/XZ/YZ icon size 30→21px; `coord_group.setFixedHeight()` 100→70.
  - **감도/큐브 1.5x (`nc_viewer_widget.py`):** new `sensitivity_cube_font = QFont('맑은 고딕', 14)` applied to the "감도"/"큐브" `QLabel`s and their value labels (previously unset/inherited default font, ~9pt); `sensitivity_slider`/`view_cube_size_slider` fixed widths 110→165 / 90→135; `sensitivity_value_label`/`view_cube_size_label` fixed widths 38→57.
  - **App rename (`NC_Tool_List.py`):** `APP_NAME = 'NC 공구 리스트 생성기'` → `'Sum Path'`. This alone drives the window title (`setWindowTitle`), the in-app header `QLabel`, the About dialog's title `QLabel`, and `write_startup_log`'s first line, since all four format off the same constant. Left untouched: `APP_PURPOSE` description text, the PyInstaller/Inno Setup exe filename (`NC_Tool_List.exe`), the install directory (`C:\NC_Tool_List`, the documented TSERP-style path), `version_info.txt`'s `FileDescription`/`ProductName`, and `NC_Tool_List.iss`'s `MyAppName`/Start-Menu/shortcut strings — none of these were named as "메인제목" and changing them would ripple into existing shortcuts/registry entries/plant deployment conventions that weren't part of this request.
  - **Button renames (`NC_Tool_List.py`):** the `'프로그램 추가'`/`'공구 리스트 생성'` string literals passed to `_add_button()` changed to `'PG ADD'`/`'Tool List'`; `self.run_button` still refers to the same button (its handler/`open_add_program_files` wiring unchanged).
  - **2000x → 5000x (`NC_Tool_List.py` + `nc_viewer_widget.py`):** both `MAX_PLAYBACK_SPEED` constants bumped to 5000 (kept in sync, as before). No label-width change needed — `"5000x"` is the same character count as `"2000x"`.
  - **Reset button (`NC_Tool_List.py`):** `self.reset_program_button = self._add_button(filter_bar, 'Reset', lambda: self.jump_to_process_line(0), kfont)` added to `filter_bar` right before `self.pg_match_check` is constructed, so it renders immediately to its left.
- Verification: 85 unit tests passed (84 existing from v1.5.7, with 2 updated for the renamed buttons/5000x cap and one v1.5.7 magnifier-gated-click test's target point moved off a segment-junction vertex to fix a corner-tie flake the tighter 4px pick radius exposed, + 1 new: a real button click moves the program cursor to line 0 from elsewhere, and the Reset button is confirmed to render before the PG-매칭 checkbox in the filter bar). Also built and launched the actual frozen exe: `startup.log` showed a clean `Starting Sum Path v1.5.8 frozen=True` line with no traceback, and the process stayed running (not a crash-exit) for several seconds until explicitly stopped.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.8.exe` and `installer/NC_Tool_List_Portable_v1.5.8.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`upx=False` in the spec, built exe's version resource reads `1.5.8.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.7 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 75451E23C75DD46A381858A8A593E43F70F58282A8C53754A88340EAD6F523D0
- Portable ZIP SHA-256: 228F0470F61CDB89605E997E10BA7178E8973D6098744FE2F6116C524CEEAC68
- App SHA-256: D55739C55E07BBEE9A9723962892A45D38DCC3FD7053380EBFB61FC6A89C4675
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine; the exe filename/install directory/Start-Menu display name/file-association ProgId (all still say "NC Tool List"/"NC_Tool_List" — only the in-app "메인제목" was renamed, see above); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors; the `ViewerFallbackWidget` (no-viewer fallback screen) is intentionally left light-only; the magnifier lens is still a fixed 220px/3x; 다크모드 button size was left as-is (not requested this round). **v1.5.7's installer/ZIP should be treated as superseded and not distributed** — the resized 투영/좌표/감도/큐브 UI, "Sum Path" rename, PG ADD/Tool List button labels, 5000x speed cap, and the Reset button described above are not in it.

### 2026-09-04 (v1.5.7)

- Version: 1.5.7
- Release/build date: 2026-09-04
- Summary: Three requested fixes/changes to the v1.5.6 viewer, all follow-up corrections to that release's dark-mode/line-picking/magnifier work:
  1. The 3D canvas (and the magnifier lens, which is just a screenshot of it) now stays on a dark background at all times, regardless of the app's light/dark theme — in light mode the previously-white canvas made the (mostly bright-colored) path lines hard to see.
  2. Line picking is now gated behind the magnifier: a plain left-click no longer jumps the program cursor to a nearby path line (only orbits the camera as before); picking only fires while the magnifier is open, and the magnifier itself now opens centered on the exact point that was right-clicked (previously it appeared at the last tracked mouse position instead). The picking cache was also rescoped: in PG-matching mode only the *progressed* segment of the *current cursor's* tool/process is eligible to be picked — previously the cache still held the entire selected-tools' path data regardless of PG-matching or cursor position, so clicking could jump to a different process's line or to a not-yet-reached part of the current one.
  3. The "투영" (projection) row's label/ISO-XY-XZ-YZ buttons and the "좌표" (coordinate) group's label/axis values got their font size and icon size doubled for legibility (both were using the small default/unset font).
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Dark canvas always-on (`nc_viewer_widget.py`):** `NCViewerWidget._VIEWER_BG_LIGHT`/`_VIEWER_BG_DARK` collapsed into a single `_VIEWER_BG` constant, used both at initial `gl_view.setBackgroundColor()` and never touched again by `set_dark_mode()` (which now only refreshes the sun/moon toggle-button icon). The dead `viewer_bg` entries in `NC_Tool_List.py`'s `THEMES['light']`/`THEMES['dark']` dicts were removed since nothing reads them anymore.
  - **Click-to-pick gated behind the magnifier (`nc_viewer_widget.py`):** `NCViewerWidget._on_gl_left_clicked()` now returns immediately unless `self._magnifier_active` is true, so `pick_source_line()`/`line_activated` only fire while the lens is open.
  - **Magnifier opens at the click point:** `OrthographicGLViewWidget.right_clicked` now carries `(float, float)` local coordinates (previously a bare signal), set from the press event's position; `NCViewerWidget._on_gl_right_clicked(x, y)` (renamed from `_toggle_magnifier`) calls `magnifier.move_center_to(x, y)` before showing it. Added a small red crosshair at the lens's exact center (`MagnifierLensWidget.paintEvent`) marking where a click actually lands, since `WA_TransparentForMouseEvents` means the lens is purely visual. `_PICK_RADIUS_PX` tightened 12→4px since picking is now always aimed through the 3x lens.
  - **Pick cache scoped to what's actually drawn (`nc_viewer_widget.py`):** `_build_pick_cache()` now branches on `pg_match_mode` — off, it behaves as before (all selected tools' full static paths); in PG-matching mode it collects segments from only `line_to_tool_map[current_cursor_line]`'s path, cut off at `current_cursor_line` via the same `line_limit`-break logic `_render_segments()` already uses for the drawn trace (factored into the shared `_collect_pick_segments()` helper), and returns nothing if that tool isn't itself selected. The cache key (`_pick_cache_scope_key()`) now also includes the PG-matching flag and, while in that mode, the current cursor line, so it invalidates itself as the trace grows/shrinks or the tool filter changes.
  - **Projection/coordinate font & icon size doubled (`nc_viewer_widget.py`):** the "투영" `QLabel` and ISO/XY/XZ/YZ `QPushButton`s now get an explicit `QFont('맑은 고딕', 18)` (icon size 15→30px); the "좌표" `QGroupBox` and its axis-letter/value `QLabel`s get the same 18pt font (title bolded), with the group's fixed height raised 54→100px so the larger text fits. The 감도/큐브/다크모드 controls in the same row were left untouched (out of the requested scope).
- Verification: 84 unit tests passed (80 existing from v1.5.6 unchanged + 4 new: a real `QTest` right-click centers the magnifier lens on the click position; a real `QTest` left-click does not activate a line while the magnifier is closed but does once it's opened by right-click; in PG-matching mode, `pick_source_line()` finds the progressed segment of the cursor's tool but returns `None` for both the not-yet-progressed rest of that same tool and for the other (unreached) tool/process; the viewer's `gl_view.opts['bgcolor']` stays the same dark value across `set_dark_mode(True)`/`set_dark_mode(False)`). Also built and launched the actual frozen exe: `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.7 frozen=True` line with no traceback, and the process stayed running (not a crash-exit) for 10+ seconds until explicitly stopped.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.7.exe` and `installer/NC_Tool_List_Portable_v1.5.7.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`upx=False` in the spec, built exe's version resource reads `1.5.7.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.6 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: D248D5F8B2AE6044B2A0033DE1B939CDA354E658F7C5A8B4C980CC586B500FC3
- Portable ZIP SHA-256: 0FA808F83A250DF364418F4743577147D4E409AD2B818E420F9141D9B29D2EED
- App SHA-256: D1984AC41D22C8F77604FA45074163554DCE69585184A0E62A3B43ED98E7FB2B
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged since v1.5.0); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors; the `ViewerFallbackWidget` (no-viewer fallback screen) is intentionally left light-only; the magnifier lens is still a fixed 220px/3x (no size/zoom control); dark-mode icon colors on the ISO/XY/XZ/YZ projection buttons are fixed rather than re-drawn per theme; 감도/큐브/다크모드 button sizes were left as-is (not requested). **v1.5.6's installer/ZIP should be treated as superseded and not distributed** — the always-dark canvas, magnifier-gated picking with correct centering/scoping, and the larger 투영/좌표 fonts described above are not in it.

### 2026-09-04 (v1.5.6)

- Version: 1.5.6
- Release/build date: 2026-09-04
- Summary: Seven requested changes across the program panel and 3D viewer:
  1. "텍스트 정지" now has its own dedicated input field next to the checkbox, instead of sharing the "문자 검색" box — searching no longer changes what the auto-playback stops on.
  2. The "장비 타입 및 스펙 설정" collapsible header (added in v1.5.5) is now a filled color block (accent-colored, white text) instead of transparent text, so it's easy to spot.
  3. Auto-playback max speed raised from 500x to 2000x.
  4. The 3D viewer's grid plane was removed (it obscured long programs), and the orthographic projection's near/far clipping — previously tied only to camera distance, so it shrank when zooming in and cut off long paths mid-screen — is now sized from the actual rendered path extent, so nothing gets clipped regardless of zoom.
  5. Clicking a drawn path segment jumps the program editor's cursor to that line (reusing the same jump used by process-filter clicks); right-click toggles a magnifier lens near the cursor for precise aiming before clicking; Escape closes it.
  6. App-wide dark mode, toggled by a sun/moon icon button next to the view-cube size slider; the choice persists and applies on next launch.
  7. Playback-bar and viewer-bar buttons got hand-drawn (QPainter) icons in place of unicode glyphs (◀◀/▶/❚❚ etc.) for legibility, plus small axis/plane glyphs on the ISO/XY/XZ/YZ projection buttons.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Dedicated text-stop input (`NC_Tool_List.py`):** new `self.stop_text_input` (`QLineEdit`, placeholder "정지 문자") next to the `텍스트 정지` checkbox, enabled only while that checkbox is checked. `_playback_tick()` now reads `self.stop_text_input.text()` instead of `self.search_text.text()`. Persisted under a new `stop_text_value` `QSettings` key via `_load_playback_stop_options`/`_save_playback_stop_options` (same pattern as the `stop_at_*` keys from v1.5.5).
  - **Machine panel header as a color block:** `set_machine_panel_expanded()` now sets `self.machine_panel_toggle`'s stylesheet to a filled `accent`/`accent_hover` background with white text and rounded corners (previously transparent-background text), refreshed on every expand/collapse and on theme change.
  - **500x → 2000x speed cap:** `MAX_PLAYBACK_SPEED` bumped in both `NC_Tool_List.py` and `nc_viewer_widget.py`; `PlaybackBarWidget`'s speed-label width grew 64px → 72px so "2000x" doesn't clip.
  - **Grid removal + clipping fix (`nc_viewer_widget.py`):** the `gl.GLGridItem()` creation/add was deleted from `NCViewerWidget._build_ui()` (axis lines remain for orientation). `OrthographicGLViewWidget.projectionMatrix()`'s depth range was `near = distance*0.001` / `far = distance*1000` — both shrink together as the camera zooms in (small `distance`), so a long path whose depth extent along the view axis exceeded the shrunk `far` got clipped mid-screen. Fixed by adding `OrthographicGLViewWidget.scene_radius` (updated by `NCViewerWidget._compute_scene_radius()`, called from `_build_path_items()`/reset in `clear()`, as the farthest rendered point's distance from the origin) and using `depth = max(distance, scene_radius) * 20 + 1000` with `transform.ortho(left, right, bottom, top, -depth, depth)` — a depth range that never shrinks below the actual scene size regardless of zoom.
  - **Line picking (`nc_viewer_widget.py`):** `OrthographicGLViewWidget` gained `left_clicked`/`right_clicked`/`mouse_moved` signals and press/move/release overrides that distinguish a genuine click (≤4px movement) from an orbit-drag, so left-drag camera rotation is never misread as a line click. `NCViewerWidget.pick_source_line(view_x, view_y, radius_px=12)` projects cached world-space path segments (built once per render+filter-selection in `_build_pick_cache()`, keyed off `last_render_signature` + selected tools, reusing each node's existing `pt`/`src_line`) through the current `projectionMatrix() * viewMatrix()` with NumPy, and returns the nearest segment's destination `src_line` within `radius_px` screen pixels (or `None`). A hit emits `line_activated(int)` (App connects it to the existing `jump_to_process_line`, same as `process_activated`) and briefly shows a dedicated flash sphere (`_pick_flash_sphere`, separate from the PG-matching `cursor_sphere` so the two don't fight over visibility) at the picked point for 700ms.
  - **Magnifier lens (`nc_viewer_widget.py`, new `MagnifierLensWidget`):** a circular overlay (220px, 3x zoom) parented to `gl_view` like the view cube/playback bar, toggled by right-click and closed by right-click again or Escape (`QShortcut` with `Qt.ApplicationShortcut` context so it works regardless of focus). It sets `Qt.WA_TransparentForMouseEvents` so it never intercepts clicks — real picking always happens against `gl_view`'s own raw (unmagnified) coordinates; the lens is purely a visual aiming aid, painted from a `gl_view.grabFramebuffer()` snapshot re-captured whenever the camera moves (hidden mid-move to avoid showing a stale frame).
  - **Dark mode (`NC_Tool_List.py` + `nc_viewer_widget.py`):** new `THEMES` dict (`light`/`dark`) with semantic color tokens. `App.apply_theme(name)` sets a `QApplication`-wide stylesheet (`_build_global_stylesheet`, covering `QPlainTextEdit`/`QLineEdit`/`QPushButton`/`QComboBox`/`QTableWidget`/`QHeaderView`/`QListWidget`/etc. — instance-level `setStyleSheet()` calls still win for the properties they set) and re-applies the ~19 previously-hardcoded inline styles (top bar, buttons, status labels, the tool-filter list, the machine-panel header/border) via small `_style_*` helper methods shared between initial construction and theme refresh. Persisted under `dark_mode` in `App.layout_settings` (the single source of truth — the viewer widget doesn't store its own copy). The toggle button itself (`NCViewerWidget.dark_mode_button`, next to `view_cube_size_label`) emits `dark_mode_toggled(bool)`; `App.toggle_dark_mode()` calls `apply_theme()`, which calls back into `viewer.set_dark_mode()` to swap `gl_view`'s background color and refresh the button's icon. `ViewerFallbackWidget.set_dark_mode()` is a no-op stub (matching its other stubs) since the fallback screen never renders 3D.
  - **Hand-drawn icons (`nc_viewer_widget.py`, new `_make_icon` + `moon_icon`/`sun_icon`/`play_icon`/`pause_icon`/`rewind_icon`/`skip_icon`/`plane_icon`/`iso_icon`):** each renders into a transparent `QPixmap` via `QPainter` and returns a `QIcon` — no image assets added to the PyInstaller build, and icons stay crisp at any DPI/theme unlike the font-dependent unicode glyphs they replace. Playback-bar buttons (previously `◀툴`/`◀◀`/`▶`/`❚❚`/`툴▶`) now show icon-only with tooltips; `set_playing()` swaps the play/pause icon. Projection buttons (ISO/XY/XZ/YZ) keep their text and gain a small prepended glyph (a 3-axis gizmo for ISO, two axis-colored perpendicular strokes for the plane buttons).
- Verification: 80 unit tests passed (68 existing pre-v1.5.6, with 2 updated for the new stop-text-input/2000x-speed changes, + 12 new: text-stop input isolation from "문자 검색" during actual playback and via settings round-trip; the machine-panel header's filled-block stylesheet; dark-mode toggle switching `App.theme_name`/persisting/restoring on a fresh `App`, and the viewer button's click reaching `App` through `dark_mode_toggled`; playback-bar buttons carry non-null icons; `viewer.grid` no longer exists; the projection matrix's depth range provably grows with `scene_radius` even at a small camera distance; `scene_radius` is computed from a loaded path and reset by `clear()`; `pick_source_line()` round-trips a known 3D point through the real projection/view matrices back to its source line and returns `None` outside the pick radius; a real `QTest` click activates a line while a real drag does not; the magnifier opens on right-click and closes on the `Escape` shortcut). Also built and launched the actual frozen exe: `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.6 frozen=True` line with no traceback, and the process stayed running (not a crash-exit) until explicitly stopped.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.6.exe` and `installer/NC_Tool_List_Portable_v1.5.6.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec, built exe's version resource reads `1.5.6.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.5 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: 98C3866CEF04C3A5263F17490D1A8400486E7454EE55572FDCF2C990BDA6B30A
- Portable ZIP SHA-256: 70BF0BBFD3C78F2C6F91681F76FA75C8933ADE7F80CC461B70A349648415FAB0
- App SHA-256: E2DF8825BD2056C2259244291016AC4405C3C64BB8836C702A41CCE20B1DD401
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged since v1.5.0); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors; the `ViewerFallbackWidget` (no-viewer fallback screen) is intentionally left light-only — it's a rare error screen, not the normal themed UI; the magnifier lens is a fixed 220px/3x (no size/zoom control); dark-mode icon colors on the ISO/XY/XZ/YZ projection buttons are fixed rather than re-drawn per theme. **v1.5.5's installer/ZIP should be treated as superseded and not distributed** — the dedicated text-stop input, color-block header, 2000x speed, grid removal/clipping fix, line picking/magnifier, dark mode, and icon changes described above are not in it.

### 2026-09-04 (v1.5.5)

- Version: 1.5.5
- Release/build date: 2026-09-04
- Summary: Three requested UI changes to the program-input/viewer panel:
  1. The "장비 타입 및 스펙 설정" (machine type/spec settings) panel is now collapsible — a clickable header (▶/▼ + title) shows/hides the type combo, spec form, and save button, so the program input pane can be wider when the panel isn't in use. Collapsed by default; auto-collapses after "현재 장비 스펙 기록/저장" is clicked and whenever the program input editor gains keyboard focus. Expand/collapse state persists via `QSettings`.
  2. The now-redundant top-bar "장비 설정" button and its separate dialog (duplicating the same settings panel) were removed — the collapsible panel is the only entry point.
  3. A new row was added directly above "공정별 경로 필터 선택": three checkboxes — 텍스트 정지 / 정지 / 옵션정지 (label text only, no parenthetical codes; the M0/M00 and M1/M01 detail is in each checkbox's tooltip) — that independently control what the PG-matching auto-playback stops on. 텍스트 정지 reuses the existing "문자 검색" input as its match string (case-insensitive substring). Defaults: 정지 and 옵션정지 checked, 텍스트 정지 unchecked (matches pre-v1.5.5 behavior). Checkbox state persists via `QSettings`.
  4. Auto-playback max speed raised from 200x to 500x (`MAX_PLAYBACK_SPEED` constant in both `NC_Tool_List.py` and `nc_viewer_widget.py`); the speed slider range and its value-label width were updated to match.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Collapsible machine settings panel (`NC_Tool_List.py`, `_build_machine_settings_panel`):** the previous static title `QLabel` was replaced with a checkable, flat `QPushButton` header (`self.machine_panel_toggle`) whose text toggles between `▶ 장비 타입 및 스펙 설정` / `▼ 장비 타입 및 스펙 설정`. The combo/spec-form/save-button now live in a `self.machine_settings_body` container whose visibility follows the header's checked state via `set_machine_panel_expanded()`. The status label (`machine_settings_status`) stays in the panel's outer layout (not inside the collapsible body) so the "저장되었습니다" message remains visible even after the panel auto-collapses. Expanded/collapsed state is read/written under the `machine_panel_expanded` `QSettings` key (`_load_machine_panel_expanded`), defaulting to collapsed. Auto-collapse triggers: end of `save_visible_machine_settings()`, and a new `ProgramTextEdit.focusGained` signal (emitted from an added `focusInEvent` override) wired to `self.src.focusGained.connect(lambda: self.set_machine_panel_expanded(False))`.
  - **Removed duplicate entry point:** the top-bar `장비 설정` `QPushButton` (and its `_style_mode_buttons` styling line) and the `open_machine_settings()` method (a separate `QDialog` with its own combo/form/save, functionally identical to the panel) were deleted in full; `QDialog`/`QFormLayout`/`QComboBox`/`QLineEdit` imports remain in use elsewhere (About dialog, row editor, type-list editor) so no import changes were needed.
  - **Stop-option row and playback logic (`NC_Tool_List.py`):** `PROGRAM_STOP_RE` was split into `M00_STOP_RE` (`M0?0(?!\d)`) and `M01_STOP_RE` (`M0?1(?!\d)`); new pure functions `line_has_m00_stop`/`line_has_m01_stop` back a reworked `line_has_program_stop` (kept as their OR, so its existing test/behavior are unchanged) plus a new `line_stops_playback(line, needle, stop_text, stop_m00, stop_m01)` that combines all three conditions (returns `False` for all three unchecked, rather than falling back to any default). `_playback_tick()` now calls `line_stops_playback()` with the three checkbox states and the current `search_text` value instead of the old hardcoded `line_has_program_stop()` call. New checkboxes `stop_text_check`/`stop_m00_check`/`stop_m01_check` sit in a new row inserted above the existing filter-header row inside `filter_layout`; their checked state is persisted via `_load_playback_stop_options()`/`_save_playback_stop_options()` under `stop_at_text`/`stop_at_m00`/`stop_at_m01` `QSettings` keys.
  - **500x speed cap:** new `MAX_PLAYBACK_SPEED = 500` module constant added to both `NC_Tool_List.py` (used by `_load_playback_speed`/`set_playback_speed`, replacing the hardcoded `200` clamp) and `nc_viewer_widget.py` (used by `PlaybackBarWidget`'s `speed_slider.setRange(1, MAX_PLAYBACK_SPEED)`, replacing `setRange(1, 200)`); the slider's value label width grew from 56px to 64px so "500x" doesn't clip. The two constants are independent (the viewer module is optionally imported and must not depend on the main module) but kept numerically in sync intentionally.
- Verification: 68 unit tests passed (60 existing pre-v1.5.5 + 8 new: `line_stops_playback()` behavior for each option independently including the all-off and empty-search-text cases; `_playback_tick()` skips past M01 when 옵션정지 is unchecked and runs to end of document instead; `_playback_tick()` stops on a 텍스트 정지 match when only that option is checked; the collapsible panel's default-collapsed state, expand/collapse toggling, auto-collapse after save, and auto-collapse when the program editor gains real keyboard focus (via `window.show()` + `QTest`-style `setFocus()`/`processEvents()`, matching the existing focus-test pattern); the speed slider's 1–500 range and `set_playback_speed()` clamping 1000→500 and 0→1). Also built and launched the actual frozen exe twice: `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.5 frozen=True` line both times with no traceback, and the process stayed running (not a crash-exit) until explicitly stopped.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.5.exe` and `installer/NC_Tool_List_Portable_v1.5.5.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec, built exe's version resource reads `1.5.5.0`/`S M.HWANG`). Portable ZIP matches the v1.5.0–v1.5.4 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries).
- Installer SHA-256: C48C7C2EB3E84C772EBAB7DE804FD4D1F200D697428BC8BF167D6CE1C61EB1DB
- Portable ZIP SHA-256: 9AA4F4EA38D020310D581A42597C6BE925DAAEAE4FBA6B1A154D71254E1BF8B0
- App SHA-256: CC059AF33DF7FF78CA5FF4E2AD312691B7310FEE65FCF7D3DB75A91388B900EB
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged since v1.5.0); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors. **v1.5.4's installer/ZIP should be treated as superseded and not distributed** — the collapsible machine-settings panel, stop-option row, and 500x speed cap described above are not in it.

### 2026-09-04 (v1.5.4)

- Version: 1.5.4
- Release/build date: 2026-09-04
- Summary: Three requested additions to the "PG 매칭" (PG matching) mode, plus one focus-theft fix:
  1. Auto-playback: a control bar (prev-tool / rewind / pause / play / next-tool, plus a 1x–200x speed slider) that steps the program cursor automatically instead of requiring arrow-key presses. 1x = 1 line/second. Auto-pauses on M00/M01 (must press play again to continue), auto-pauses at end of document, and on leaving PG matching mode or viewer mode. Only enabled while PG matching is checked.
  2. The view cube (added in v1.5.2) doubled from 80px to 160px by default, with a 60–240px slider (next to the existing sensitivity slider) to resize and persist it via `QSettings`.
  3. Clicking inside the 3D viewer no longer breaks arrow-key program stepping.
  4. Follow-up sizing pass (same day, user watched the live-built exe and asked for adjustments): playback bar enlarged to ~2.75x overall height with buttons at exactly 2.5x size, and both the playback bar and view cube repositioned to float ~2cm from the viewer's edges (bottom-center for the bar, top-right for the cube) instead of the initial fixed 10–16px margins.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Details:
  - **Auto-playback engine (`NC_Tool_List.py`):** new `App.play_timer` (`QTimer`, 50ms/20Hz fixed interval, not scaled by speed) plus a fractional accumulator (`_play_carry`) absorb the requested speed — at 1x the accumulator crosses 1.0 once every 20 ticks (1 line/sec), at 200x it crosses 10.0 every tick (200 lines/sec) — so the UI always repaints at a steady 20Hz regardless of speed, and `NCViewerWidget.set_cursor_line()`'s per-call cost (it re-walks the whole current process's path from scratch, `nc_viewer_widget.py`) never has to run faster than that. Each tick moves the *editor* cursor via the existing `App.jump_to_process_line()` (keeping `self.src` as the single source of truth the viewer already follows via `cursorPositionChanged`), scanning every intervening line for `PROGRAM_STOP_RE` (`M0?[01](?!\d)`, comments stripped first) so a multi-line skip at high speed still stops exactly on the first M00/M01 it would have crossed, never past it. New `App` methods: `start_playback`/`pause_playback`/`_playback_tick`/`set_playback_speed`/`playback_rewind`/`playback_prev_tool`/`playback_next_tool`/`_jump_relative_tool`. `playback_prev_tool`/`playback_next_tool` jump between entries of the existing `NCViewerWidget.process_first_line` map, skipping processes deselected in the filter (same pattern `toggle_pg_match_mode` already used). `playback_rewind` returns to the current process's first line (matching PG matching's existing per-process trace baseline) rather than the program start. Playback is force-stopped from `set_mode()` (leaving viewer mode) and from `toggle_pg_match_mode(False)`.
  - **Playback bar widget (`nc_viewer_widget.py`, new `PlaybackBarWidget`):** a `QWidget` overlay (not OpenGL) parented to `gl_view`, floating bottom-center at 70% of the viewer's width, `QWidget.WA_TranslucentBackground` with a semi-transparent rounded panel, matching the `ViewCubeWidget` overlay precedent. Disabled by default; `NCViewerWidget.set_pg_match_mode()` enables/disables it alongside the existing trace-visibility toggle. `OrthographicGLViewWidget` gained a second overlay slot (`bottom_bar_widget`, alongside the pre-existing single-slot `overlay_widget` used by the cube) and `_reposition_bottom_bar()`, called from the same `resizeEvent` as the cube's `_reposition_overlay()`.
  - **View cube resizing:** `_load_view_cube_size()` mirrors the existing `_load_navigation_sensitivity()` pattern (read from the same `QSettings("NC Tool List", "EmbeddedViewer")`, clamp, tolerate bad values), default 160, persisted under `view_cube_size`. `ViewCubeWidget._paint()`'s previously-hardcoded 80px-derived constants (14px inset, 36×16 label box, 1px pen) were changed to scale proportionally with the cube's actual half-extent, so the cube stays legible at any configured size instead of the label shrinking in relative terms as the cube grows.
  - **Viewer focus fix (`nc_viewer_widget.py`):** root cause was pyqtgraph's `GLViewWidget.__init__` setting `Qt.FocusPolicy.ClickFocus` and its own `keyPressEvent` capturing Left/Right/Up/Down/PageUp/PageDown for camera-orbit key-repeat — a single click into the 3D view was silently redirecting all subsequent arrow-key presses from the program editor to camera rotation. Fixed by `self.gl_view.setFocusPolicy(Qt.NoFocus)` right after construction; since a widget with no focus policy never receives keyboard focus, its `keyPressEvent` is never invoked and arrow keys always reach `self.src`. The same `Qt.NoFocus` was applied to the pre-existing ISO/XY/XZ/YZ projection buttons and the sensitivity slider (which had the identical latent bug — dragging the slider then pressing an arrow key moved the slider instead of the cursor) and to every playback-bar control.
  - **~2cm-from-edge overlay spacing (follow-up, same day):** a `PX_PER_CM = 96.0 / 2.54` constant (96 DPI / 100% Windows scaling assumption — approximate by nature, since actual display DPI varies) replaces the cube's and bar's previous fixed-pixel margins (10px / 16px). `_reposition_bottom_bar()`'s original "midpoint between view-center and bottom" placement was simplified to a fixed ~2cm gap above the bottom edge, per direct user feedback after watching the freshly built exe.
- Verification: 64 unit tests passed (51 existing pre-v1.5.4 + 13 new: `line_has_program_stop()` M00/M0/M01/M1 detection including the `G54M01` and commented-`(M01 STOP)` edge cases; tick-to-line-count math at 20x and 100x; a tick that skips several lines still stops exactly on an M01 crossed mid-skip; auto-stop at end of document; playback force-stopped when PG matching is unchecked or viewer mode is left; prev/next-tool and rewind jump to the correct `process_first_line` entries; `gl_view` and every playback-bar control report `Qt.NoFocus`; the view cube's default size is 160 and the slider round-trips through a faked `QSettings`; and — the most direct regression test for the reported bug — a real `QTest.mouseClick` on `window.viewer.gl_view` followed by `QTest.keyClick(window.src, Qt.Key_Down)` still moves the program cursor). Also built and ran the actual frozen exe twice (before and after the same-day sizing follow-up): `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.4 frozen=True` line both times with no traceback and successful `OpenGL vendor/renderer` initialization (grid, axis lines, and the view cube all rendered); loaded the built-in 예제 program, switched to Viewer mode, and checked PG 매칭 — confirmed via full-resolution screenshots (captured with the PowerShell host process explicitly set to per-monitor-v2 DPI awareness, since the first capture attempt was silently downscaled by Windows' DPI virtualization and read the wrong physical coordinates) and UI Automation `BoundingRectangle` measurements that: the playback bar and its four buttons render and are enabled once PG 매칭 is on; button height measured 55px (exactly 2.5x the pre-follow-up ~22px) and the bar's total height measured 165px (~2.75x the pre-follow-up ~60px); both the bar's bottom margin and the cube's top-right margin visually and numerically match the requested ~2cm spacing. (Note: a first verification attempt used a synthetic global mouse click to press the 예제 button; it landed on an unrelated foreground window instead of the target exe due to the same DPI-coordinate mismatch, so all further interaction was redone through UI Automation's Invoke/Toggle patterns, which target the exe's window directly without moving the real system cursor.)
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.4.exe` and `installer/NC_Tool_List_Portable_v1.5.4.zip` from the same PyInstaller onedir `dist/NC_Tool_List` build used for the exe verification above (rebuilt fresh after the sizing follow-up commit; `dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec). Exe version resource confirmed `1.5.4.0` (`FileVersion`/`ProductVersion`, `CompanyName` "S M.HWANG"). Portable ZIP built with `_internal` and `NC_Tool_List.exe` at the archive root (294 entries — the exact count drifts release to release with dependency contents, e.g. pyqtgraph's bundled colormap/icon files, and isn't itself meaningful). Launched the packaged exe directly from `dist/NC_Tool_List/`; `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.4 frozen=True` line with no traceback, closed normally.
- Installer SHA-256: AB4DD5F12072836C7583DF6C1DB90F79DEFD6E1070EF99DD0794D7A18FACB2C1
- Portable ZIP SHA-256: 209BF1BAA5CCA527FF49E0D53C1CBF51F167901EF7BF066892440A6ED6562CEA
- App SHA-256: 15D006F686FC01B573FBDD03B95972D4F6F9F01B9D2A9FDBD377F571EC9D5EB0
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged since v1.5.0); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors; exact-cm accuracy of the new overlay spacing across different monitor DPI settings (the 96-DPI assumption is approximate by design, per the user's "약 2cm/정도" phrasing). **v1.5.3's installer/ZIP should be treated as superseded and not distributed** — the auto-playback, larger view cube, and click-focus fixes described above are not in it.

### 2026-09-04 (v1.5.3)

- Version: 1.5.3
- Release/build date: 2026-09-04
- Summary: Critical fix — loading a real-size NC program (`ncdata.nc`, 32,903 lines) into the program editor would hang the app (user report: "파일 불러오기중 멈춤" / freezes while loading a file). Traced this directly to v1.5.2's current-line highlight feature.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged — no dependency added or removed).
- Root cause and fix (`NC_Tool_List.py`): `ProgramTextEdit` was a `QTextEdit` (rich-text widget). v1.5.2 added `_highlight_current_line()`, called right after every `setPlainText`, which calls `setExtraSelections([...FullWidthSelection...])`. On a `QTextEdit` in `NoWrap` mode that's actually embedded in a live layout (here, `self.input_splitter`, a `QSplitter`), that single call forces `QTextDocument`'s rich-text layout engine to lay out the *entire* ~33K-line document to resolve scrollbar/geometry — and this became so slow it read as a total hang (20+ seconds observed via a `faulthandler.dump_traceback_later` stack dump pinned to that exact line; a bare, unparented `ProgramTextEdit` with the identical document completed in 0.24s, isolating the layout-in-a-live-container combination as the trigger). Fix: switched `ProgramTextEdit`'s base class from `QTextEdit` to `QPlainTextEdit` — Qt's purpose-built widget for large plain-text documents (this app never used rich-text features; `toPlainText`/`setPlainText` only). The same splitter-embedded, `NoWrap`, 33K-line, `setExtraSelections` scenario now completes in 0.14s. `QPlainTextEdit` shares essentially the whole API surface used elsewhere on `self.src` (`textCursor`, `setTextCursor`, `document()`, `ensureCursorVisible`, `cursorPositionChanged`, `setTextInteractionFlags`, `extraSelections`/`setExtraSelections`), so no other call site needed to change beyond the `NoWrap` enum reference (`QPlainTextEdit.NoWrap` instead of `QTextEdit.NoWrap` — same underlying value, correct class going forward). `QTextEdit.ExtraSelection()` is still used to build the selection object, since PyQt5 doesn't expose a separate `QPlainTextEdit.ExtraSelection` alias (confirmed — Qt's C++ header defines `QPlainTextEdit::ExtraSelection` as a typedef of `QTextEdit::ExtraSelection`, and `setExtraSelections()` accepts it either way).
- Verification: 53 unit tests passed (51 existing + 2 new: `test_loading_large_real_program_does_not_hang` loads the real `ncdata.nc` into a real `App()` and asserts it completes in under 5 seconds — generous margin against the pre-fix ≥20s/effectively-unbounded hang, tight enough to catch a regression; `test_program_editor_is_plain_text_edit_not_rich_text_edit` pins `ProgramTextEdit`'s base class so a future revert can't silently reintroduce this). This is also a coverage-gap fix in its own right: every prior interactive test used the tiny synthetic `REAL_NC_SAMPLE` (~42 lines), which never reproduced the problem — only a real, large document embedded in the live splitter layout triggers it. Reproduced and confirmed the fix end-to-end in three ways: (1) headless with fine-grained `faulthandler`-timestamped steps — hang pinpointed to `NC_Tool_List.py`'s `setExtraSelections()` line before the fix, 0.15s to clear that same line after; (2) a real (non-offscreen) windowed run loading `ncdata.nc` and switching to viewer mode — went from "never returns" to a full 2.88s end-to-end including 3D path build; (3) full test suite green.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.3.exe` and `installer/NC_Tool_List_Portable_v1.5.3.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec, built exe's version resource reads 1.5.3.0). Portable ZIP matches the v1.5.0–v1.5.2 layout (`_internal` + `NC_Tool_List.exe` at the archive root, 311 entries). Launched the built exe directly; `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.3 frozen=True` line with no traceback, exited cleanly.
- Installer SHA-256: 77EDCF7A2D406A99866D9AB7125D4AEF6BB8E7DCB1B9D71350BB45234753855D
- Portable ZIP SHA-256: 6B98E0274531D3CD897B83619E00931094E403678C7D5E1D463CD1D1430084ED
- App SHA-256: 3D5893765415FA3E6BDD64C0EC5DEEC8425B68AEE8D5AE07FCD0ABFCB7EFFD7D
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged since v1.5.0); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors. **v1.5.2's installer/ZIP should be treated as superseded and not distributed** — they contain the hang described above.

### 2026-09-04 (v1.5.2)

- Version: 1.5.2
- Release/build date: 2026-09-04
- Summary: Two field-test fixes reported after v1.5.1's PG 매칭 mode:
  1. The program editor's cursor could only move by clicking — arrow keys/PgUp/PgDn did nothing, which broke PG 매칭's whole point (scrubbing the toolpath with the keyboard). Root cause: Qt's `QTextEdit.setReadOnly(True)` overwrites the interaction flags down to `TextSelectableByMouse` only, silently dropping `TextSelectableByKeyboard`. Fixed, and the current line is now highlighted as a full-width block so the cursor's position reads clearly even off-screen to the right.
  2. 3D view mouse sensitivity was too high — added an adjustable sensitivity slider, plus a CAD-style orientation cube overlaid in the viewer's top-right corner (click a face to snap to that view).
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged from v1.5.1 — no dependency added or removed; the view cube is drawn with QPainter, not a second GL surface).
- Details:
  - **Keyboard cursor + line highlight (`NC_Tool_List.py`):** `ProgramTextEdit.setReadOnly` (already the sole entry point for toggling read-only, since it also re-enables drag/drop there) now re-applies `Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard` whenever switching to read-only. New `App._highlight_current_line` builds a `QTextEdit.ExtraSelection` with `QTextFormat.FullWidthSelection` set, wired to `src.cursorPositionChanged` (in addition to the existing `source_cursor_changed`, which stays scoped to viewer mode) so it applies in both modes, and refreshed explicitly after `load_file`/`add_program_files` (they mutate the document inside `QSignalBlocker`, which would otherwise leave the highlight pointing at a stale cursor). `jump_to_process_line` (used by the process filter's click-to-jump and by PG 매칭's auto-jump) no longer does `KeepAnchor` to end-of-line — placing the cursor without a text selection avoids double-highlighting against the new full-width block and stops the first arrow-key press after a jump from being consumed by clearing the old selection instead of moving.
  - **Navigation sensitivity (`nc_viewer_widget.py`):** `OrthographicGLViewWidget` gained `navigation_sensitivity` (default 0.4, persisted per-PC in the existing `QSettings("NC Tool List", "EmbeddedViewer")`, unlike PG 매칭's deliberately-not-persisted mode) and a `camera_changed` signal. Rather than reimplementing pyqtgraph's orbit/pan math (which would drift out of sync on a pyqtgraph upgrade), `mouseMoveEvent` pulls the stored `mousePos` toward the new position by `(1 - sensitivity)` *before* calling `super().mouseMoveEvent()` — the library then computes a proportionally smaller `diff` internally and everything else (orbit/pan formulas, `rotationMethod` branching) stays untouched. `wheelEvent` multiplies `delta` by the same sensitivity before pyqtgraph's `0.999**delta` zoom formula. A slider (5–200%, default 40%) sits in the existing 투영 bar, right of a stretch so it reads "투영 [ISO][XY][XZ][YZ]　　감도 ──●─── 40%".
  - **View cube (`nc_viewer_widget.py`, new `ViewCubeWidget`):** a plain `QWidget` (not `QOpenGLWidget`) child of `gl_view`, painted with `QPainter` by projecting a unit cube's 8 corners through the exact same rotation `GLViewWidget.viewMatrix()` applies (`rotate(elevation-90, 1,0,0)` then `rotate(azimuth+90, 0,0,-1)`), so it always agrees with the real 3D view. Deliberately avoids a second GL surface — this app has a field history of OpenGL init failures on some plant PCs (v1.4.3→v1.4.4's black-viewer fix), and `_build_view_cube` wraps the whole thing in try/except so a failure here degrades to "no cube" rather than losing the 3D viewer. 80×80px, pinned to the top-right corner via `OrthographicGLViewWidget.resizeEvent`/`_reposition_overlay`, repainted on every `camera_changed` emission so it tracks drags/zooms/button clicks live. Clicking a face emits `face_clicked(elevation, azimuth)`, connected to new `NCViewerWidget.set_camera_angles(elevation, azimuth, distance=None)` — omitting `distance` keeps the current zoom (unlike the ISO/XY/XZ/YZ toolbar buttons, refactored to call the same method with `distance=200`, which still reset zoom as before). All six faces are mapped (existing buttons only exposed four), using the same angle convention so a face click and its equivalent toolbar button (where one exists) land on the identical view.
- Verification: 51 unit tests passed (43 existing + 8 new: read-only editor keeps `TextSelectableByKeyboard`; a real `App` instance actually moves the cursor via `QTest.keyClick` for Down/PageDown/Up and keeps the 3D cursor line in sync; the current-line highlight is a single `FullWidthSelection` extra-selection that follows `jump_to_process_line` without leaving a text selection behind; mouse-drag rotation and wheel-zoom scale linearly with `navigation_sensitivity`, exact ratio checked; the sensitivity slider round-trips through a faked `QSettings`; a view-cube face click sets the exact expected `elevation`/`azimuth` without touching `distance`; the cube paints to an offscreen `QPixmap` and handles a click without raising). Also headless-smoke-tested against the real `ncdata.nc`: arrow/PageDown/Up cursor movement and the live line highlight all confirmed on the fully-loaded app; on a live `NCViewerWidget`, the sensitivity slider (40%→80%) updated the label and stored ratio, a synthetic 100px drag rotated the camera exactly 100.0°/40.0° at 100%/40% sensitivity (ratio 0.4 to 5 decimal places), the cube painted all 6 faces and sat pinned at `gl_view.width() - 90` (80px cube + 10px margin), a simulated top-face click set `elevation=90.0, azimuth=-90.0` while leaving `distance` at its prior 200, and the ISO button still worked afterward.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.2.exe` and `installer/NC_Tool_List_Portable_v1.5.2.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec, built exe's version resource reads 1.5.2.0). Portable ZIP matches the v1.5.0/v1.5.1 layout — `_internal` and `NC_Tool_List.exe` at the archive root, 311 entries. Launched the built exe directly; `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.2 frozen=True` line with no traceback, and it closed normally with exit code 0.
- Installer SHA-256: AE1315C50F52C697F57E50AC94EA1396D0F3FB26A56E81EB77CDF979A9E8A7C4
- Portable ZIP SHA-256: B8329DF101F44954E4EE1DDE57F61BEA0974281CCB4994E2468EB50EA2A834D6
- App SHA-256: BDE3A39E0F2A481D38BEF0C7C969DE2149869583EBB1A71063FE81CE894563CD
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged since v1.5.0, so plant-PC install verification carries over); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves; a settings UI for cube face labels/colors.

### 2026-09-04 (v1.5.1)

- Version: 1.5.1
- Release/build date: 2026-09-04
- Summary: One requested feature for the next version — a "PG 매칭" checkbox next to 전체 in the process path filter bar. When checked, the viewer clears the drawn static paths and draws only the cursor's process, growing and erasing in real time as the program cursor moves with the arrow keys, so a program line can be matched 1:1 against the actual tool path.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged from v1.5.0 — no dependency added or removed).
- Details:
  - **PG 매칭 mode (`nc_viewer_widget.py`):** the dynamic-trace machinery already drew "from the process's first line up to the cursor line" (`_render_segment_buckets(path_data, line_limit)` + `update_trace_item`), but it was invisible underneath the always-on static paths. So the feature is just a mode flag: new `pg_match_mode` state (deliberately NOT persisted to `QSettings` — a temporary inspection mode should always start off) and `set_pg_match_mode()`, with `update_visible_paths()` changed to `visible = (not self.pg_match_mode) and (tool in selected_items)`. `set_cursor_line` is untouched: it already resolves the cursor's process via `line_to_tool_map` (populated for *every* line including blanks/comments, so arrow-keying past a comment doesn't make the line flicker away) and honors the filter selection via `_tool_selected`. Because `process_nc_lines` → `_refresh_tool_filter` → `update_visible_paths` is the load path, opening a new file while the mode is on does not make static paths reappear.
  - **Checkbox + handler (`NC_Tool_List.py`):** `QCheckBox('PG 매칭')` added to `filter_bar` immediately left of the 전체 button, with a tooltip explaining the behavior. New `toggle_pg_match_mode` forwards to the viewer; when switching on it also focuses the program editor so the arrow keys work immediately, and — if the cursor happens to sit on a process that is *not* selected in the filter, which would draw nothing and read as a malfunction — jumps the cursor to the first selected process's start line by reusing the existing `jump_to_process_line`. With no process selected at all it leaves the cursor alone. `ViewerFallbackWidget` gained a no-op `set_pg_match_mode` so a PC where the 3D viewer fails to initialize does not die with `AttributeError`.
  - **Confirmed behaviors (user-approved during planning):** only the cursor's process is drawn even when several processes are selected; the trace baseline is that process's first line (not cumulative from the top of the program); the checkbox never persists across restarts.
  - **Version-sync test hardening:** `test_installer_uses_c_drive_onedir_package_without_direct_taskkill` had the version string hardcoded as `1.5.0`, so it broke on every version bump. It now asserts the `.iss` version equals `app.APP_VERSION`, and additionally covers `version_info.txt` (`filevers`/`prodvers`/`FileVersion`/`ProductVersion`) against the same source of truth — `version_info.txt` previously had no test at all.
- Verification: 43 unit tests passed (39 existing + 4 new: static paths all hidden when the mode is on and restored when off; only the cursor's process is traced and nothing is drawn once that process is deselected; the trace grows when the cursor moves down and returns to exactly its former size when moved back up; and an App-level test that the checkbox toggles `viewer.pg_match_mode` and hides the static items, starting unchecked). Also headless-smoke-tested against the real `ncdata.nc` (11 processes): static items 20 visible → 0 on check → 20 on uncheck; simulated arrow-key travel of 30 lines took the trace from 2 to 62 points and back to 2; and the auto-jump path was exercised by selecting only the last process while parking the cursor on `Initial`, confirming the cursor moved to that process's start line (30823) with focus on the program editor, and that a zero-selection state leaves the cursor untouched.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.1.exe` and `installer/NC_Tool_List_Portable_v1.5.1.zip` from a fresh PyInstaller onedir rebuild after deleting `build/` and `dist/` (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, no `freeglut`/`gle32`/`gle64` DLLs present, `upx=False` in the spec, built exe's version resource reads 1.5.1.0). Portable ZIP was rebuilt to match the v1.5.0 layout exactly — `_internal` and `NC_Tool_List.exe` at the archive root, 311 entries — after a first attempt wrapped everything in an extra `NC_Tool_List` folder. Launched the built exe directly; `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.1 frozen=True` line with no traceback, and it closed normally with exit code 0.
- Installer SHA-256: A5E47ACB0514DF59629551FC1079572A489528F0D80FE3C84754B10A8D5C28CC
- Portable ZIP SHA-256: F3910516400B88BC83C66A200FB4F4A6A0FE20F59D64AC7C334CA0C39DE5B373
- App SHA-256: E661E6B654EBE9CC21B7945FFDB78A32D17C5DBE6612A3C52F8D3155F33743C2
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; running the installer elevated on this dev machine (the `[Registry]` association behavior is unchanged from v1.5.0, so plant-PC install verification carries over); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves.

### 2026-09-04 (v1.5.0)

- Version: 1.5.0
- Release/build date: 2026-09-04
- Summary: Three requested features for the next version:
  1. User-configurable update root path + manual update from the About popup (default `\\192.168.0.210\생산부서\05. 생산자료\Update_Files`).
  2. `.nc`/`.mpf`/`.tap` registered as this app's default program.
  3. Clicking a process-filter entry now jumps the program editor's cursor to that process's start line.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Details:
  - **Update root + manual update (`NC_Tool_List.py`):** new `%APPDATA%\NC Tool List\app_settings.json` stores a per-PC `update_root` override (`load_app_settings`/`save_app_settings`/`update_root_setting`/`save_update_root_setting`); falls back to the default UNC share when unset. About popup gained an "업데이트" group: path field + 찾아보기/기본값 복원/경로 저장/업데이트 확인/지금 설치 buttons. `find_latest_installer` scans the root for `NC_Tool_List_Setup_v<major>.<minor>.<patch>.exe`, picks the highest version via `parse_installer_version`, and only enables install when it's newer than `APP_VERSION`. Install copies the network exe to `%TEMP%` first (`copy_installer_to_temp`, avoids share/lock issues), confirms with the user that the app will close, launches it via the existing `open_file_with_default_app` (`os.startfile`), then quits.
  - **File association (`NC_Tool_List.py` + `NC_Tool_List.iss`):** installer now writes HKCR entries at install time (admin, already required) registering `.nc`/`.mpf`/`.tap` under ProgId `NCToolList.NCProgram` pointing at the installed exe, all under `uninsdeletekey`/`uninsdeletevalue` so uninstall removes them. `ChangesAssociations` flipped from `no` to `yes`. About popup adds a "확장자 기본 프로그램 등록" group with 등록/해제 buttons that write/remove the same ProgId under `HKCU\Software\Classes` (no admin required, works even for a portable/no-installer deployment) via `register_file_associations`/`unregister_file_associations`, and a status label (`file_associations_status`, checked through the merged `HKEY_CLASSES_ROOT` view so it reports true regardless of which of HKCU/HKLM made the association) refreshed after each action; `SHChangeNotify(SHCNE_ASSOCCHANGED)` tells Explorer to pick up the change immediately. File-open/add dialogs' filter also gained `*.mpf`.
  - **Process filter → program cursor jump (`nc_viewer_widget.py` + `NC_Tool_List.py`):** `NCViewerWidget.process_nc_lines` now records each process key's first source line in `process_first_line` (including the `"Initial"` pre-M6 segment at line 0). A new `process_activated(int)` Qt signal fires from a new `itemClicked`-driven handler (`_on_tool_filter_item_clicked`) on the filter list — deliberately using `itemClicked` rather than `itemSelectionChanged` so 전체/해제 and multi-select don't also yank the cursor, only an explicit click on one entry does. The main window connects it (`hasattr` guarded, since the OpenGL-less `ViewerFallbackWidget` doesn't define the signal) to a new `jump_to_process_line`, which moves/selects that line in the program editor and scrolls it into view.
- Verification: 39 unit tests passed (28 existing + 11 new: update-root settings round-trip, installer filename/version parsing, latest-version selection incl. ignoring lower/invalid names, `copy_installer_to_temp`, file-association constants/command string, a real HKCU register→verify→unregister→verify round trip with cleanup confirmed afterward via a separate registry read, a viewer-level test that a filter-item click emits the correct first line, an App-level integration test that the click actually moves `QTextEdit` cursor to that line, and an updated `.iss` test asserting the `[Registry]`/`ChangesAssociations=yes` associations exist). Also manually smoke-tested that `show_about()` builds and opens without raising (via a monkeypatched non-blocking `QDialog.exec_`), and confirmed the HKCU test round trip left no `NCToolList.NCProgram` key and no leftover `.nc`/`.mpf`/`.tap` default values behind on the dev machine.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.5.0.exe` and `installer/NC_Tool_List_Portable_v1.5.0.zip` from a fresh PyInstaller onedir rebuild (`dist/NC_Tool_List/_internal/OpenGL` confirmed absent, `upx=False` confirmed in the built spec). Launched the built exe directly; `startup.log` showed a clean `Starting NC 공구 리스트 생성기 v1.5.0 frozen=True` line with no traceback, then closed normally.
- Installer SHA-256: 91A9AA47D75CF8C6EA64DB61F4AFFDE06C744511912F8F9AEC9BB685951FBE67
- Portable ZIP SHA-256: BE4F4C1258F8716C9FBE05F48DA47EB588515DACA71EE7BCC8EE71CBF144722B
- App SHA-256: 3AE3C5CE2D0832D37E5A4A2FD890A65C2BCFD17E1B7AB07DDACD254758025023
- Signature status: still unsigned.
- Out of scope (left untouched): actual code-signing; testing the update flow against the real `\\192.168.0.210` share from this dev machine (verified instead against a local temp directory standing in for the share; real share access and an actual admin-elevated install exercising the new `[Registry]` associations remain plant-PC verification items); lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves.

### 2026-09-04 (v1.4.5)

- Version: 1.4.5
- Release/build date: 2026-09-04
- Summary: Fixed G02/G03 circular interpolation defects across 3/4/5-axis, and improved the process filter list's readability.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Context: G2/G3 arc code already existed in `nc_viewer_widget.py` (`_arc_points`), but had several defects reported by the user as "arcs not rendering correctly" across 3/4/5-axis programs. User confirmed 3-axis I/J/R arcs were already fine, which matched the root-cause analysis (the 4/5-axis rotation matrix is only non-identity for 4/5-axis machines, so the coordinate-frame bug below was invisible on 3-axis).
- Arc fixes in `nc_viewer_widget.py`:
  - **4/5-axis coordinate-frame bug (the actual reported defect):** the arc's start point was captured pre-rotation while its end point was already rotated by the active 4/5-axis matrix, so the two endpoints lived in different coordinate spaces and the interpolated arc was garbled. Fixed by building the whole arc in the pre-rotation ("local") frame — matching `start_pt` — and rotating every generated arc point as one batch with `active_matrix`, the same pattern the existing canned-cycle code already used. Verified empirically: the pre-fix code produced a ~14-unit discontinuity jump between a rapid move's endpoint and the following arc's first point once a G68.2/G53.1 tilt was active; the fix reduces this to a normal small interpolation step. Lathe arcs were left untouched (no rotation matrix involved there).
  - Full-circle arcs (`G02 I.. J..` with no X/Y/Z word) previously never entered the motion-parsing block at all and were silently dropped; now detected via the presence of I/J/K parameters (guarded against colliding with the unrelated G68.2 I/J/K tilt-vector usage).
  - G17/G18/G19 plane selection is now tracked and honored — arcs on G18 (ZX, using I/K) and G19 (YZ, using J/K) planes are computed in their own plane instead of always assuming XY.
  - Segment count switched from a fixed angle-based formula (which turned very short arcs, e.g. small corner fillets, into a single straight line) to chord-error-based adaptive resolution with a minimum segment floor, so short arcs stay curved and long arcs don't over-generate points.
  - The arc's final point is snapped exactly to the commanded end coordinate rather than the parametric circle formula, so small I/J rounding no longer leaves a visible gap to the next segment.
- Filter list readability (`nc_viewer_widget.py` + `NC_Tool_List.py`): per-tool color moved from the list item's text color (low contrast against the default light background) to a small color-swatch icon (`color_chip_icon`) next to the label; the list now uses a larger bold font and a high-contrast selected-row style (blue background, white text) matching the app's existing button color scheme.
- Verification: 28 unit tests passed (22 existing + 6 new arc regression tests covering G02/G03 direction, short-arc minimum segments, full circles, G18/G19 planes, helical Z interpolation, and the 4/5-axis coordinate-frame fix specifically). Offscreen-rendered screenshot confirmed arcs draw as curves (including a complete circle from a single I/J-only line) and the filter list shows color chips with readable bold selected rows. Rebuilt frozen exe launched and logged a healthy GL context.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.4.5.exe` and `installer/NC_Tool_List_Portable_v1.4.5.zip`.
- Installer SHA-256: 31C8DAD8C5EE5A51CA20F032F4BF46754EA7C791AEADCE50242D5DDFCEF88BF5
- Portable ZIP SHA-256: 66EBE6DD72BD287D3153EC75EB2DD25292E630EAD756EBB41982887C36AA1857
- App SHA-256: B93CEE89C8E73A5DEC401A9CC6206F3AD72E77189E1970AD8481406F1F501DA9
- Signature status: still unsigned.
- Out of scope (left untouched): lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves.
- User field confirmation (2026-09-04): user installed v1.4.5 and confirmed the fix works correctly.

### 2026-09-04 (v1.4.4)

- Version: 1.4.4
- Release/build date: 2026-09-04
- Summary: Fixed the v1.4.3 regression that made the 3D viewer render a fully black screen with no toolpath lines on a normally working PC.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Root cause (measured, not guessed): v1.4.3 added `os.environ.setdefault('QT_OPENGL', 'software')` and `QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)` as secured-PC hardening. That makes Qt build its context on `opengl32sw.dll` (Mesa llvmpipe) while pyqtgraph's PyOpenGL keeps dispatching into the system `opengl32.dll`. PyOpenGL therefore has no current context and every GL call fails — `GLError 1282 (GL_INVALID_OPERATION)` starting at `glClearColor`, so even the configured background never paints. Qt's `paintGL` swallows the exception, leaving a black viewport instead of a crash. `nc_viewer_widget.py` was unchanged since v1.4.2, confirming the regression came from these two lines.
- A/B measurement on the affected PC (offscreen `grabFramebuffer` pixel sampling of the real viewer widget):
  - Fixed build: 23 distinct colors, background `#21252B` 89.1%, pure black 0.0% → lines rendered.
  - v1.4.3 setting: 1 distinct color, background 0.0%, pure black 100.0% → blank black screen.
- Fix:
  - Removed both software-OpenGL lines from `NC_Tool_List.py`. This forcing never delivered its intended benefit either — the secured PC still crashed with it in place — so there is no trade-off in removing it.
  - Restored `collect_submodules('OpenGL')` in `NC_Tool_List.spec` and dropped the `OpenGL.raw.GLX` / `OpenGL.raw.GLES1-3` / `OpenGL.raw.GLUT` excludes added in v1.4.3. PyOpenGL resolves submodules dynamically, so these only break the frozen build — source runs would not reveal it. `OpenGL.Tk` / `OpenGL.GLUT` excludes and the `OpenGL\DLLS` folder exclusion are kept (genuinely unused).
  - Inverted the unit test that previously asserted `QT_OPENGL == 'software'` — it was locking the bug in. It now guards against software-OpenGL forcing ever returning.
- New diagnostic: the app logs `OpenGL vendor=... renderer=... version=...` to `startup.log` the first time Viewer mode opens. The packaged app has no console, which is why this class of GL failure was invisible until a user reported it; the log line now makes it checkable on any PC.
- Kept from v1.4.3: onedir + `upx=False`, exe version resource (`version_info.txt`), installer `VersionInfo*`/icon settings, startup logging, viewer fallback screen.
- Verification: 22 unit tests passed; offscreen render check confirmed lines draw; rebuilt frozen exe launched and logged a healthy hardware context (`vendor=Intel renderer=Intel(R) Iris(R) Plus Graphics version=4.6.0`), which also validates the `.spec` restoration in the packaged build.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.4.4.exe` and `installer/NC_Tool_List_Portable_v1.4.4.zip`.
- Installer SHA-256: 5BB4B17D426C0293AC563568850F1E5F713DA40FD7DDC5557019B8DF4F595608
- Portable ZIP SHA-256: 94ED0500413368DF1E67957A590AC4F826FE5EE42DECB6E4A685B6593EB9D07F
- App SHA-256: EE12403F94A075AB334946EB9B3389D1033ED12BE61A49AC0AEBC2F9B53104CB
- Signature status: still unsigned.

### 2026-09-04

- Version: 1.4.3
- Release/build date: 2026-09-04
- Summary: Version bump only; hardened installer/build configuration against Windows security software false positives.
- Creator displayed: Hwang.seonmun
- Scope: About popup version/date fields, `.iss`, `.spec` only. No unrelated feature changes.
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Packaging hardening:
  - Excluded leftover `OpenGL\DLLS` license/README text files from `a.datas` (previously only `a.binaries` was filtered), completing the cleanup noted as outstanding after v1.4.2.
  - Embedded a Windows version-info resource (`version_info.txt`: CompanyName, FileDescription, FileVersion, ProductName, ProductVersion, LegalCopyright) into `NC_Tool_List.exe` via PyInstaller's `version=` option, since an unsigned executable with no version metadata is a common heuristic AV/SmartScreen flag.
  - Installer (`NC_Tool_List.iss`): added `SetupIconFile`, `UninstallDisplayIcon`, and explicit `VersionInfoVersion`/`VersionInfoCompany`/`VersionInfoDescription`/`VersionInfoProductName`/`VersionInfoProductVersion` so the setup EXE also carries legitimate-looking metadata.
- Verification: All 22 unit tests passed. Rebuilt with PyInstaller onedir; confirmed `dist/NC_Tool_List/_internal/OpenGL` no longer exists (freeglut/gle DLLs and their license/README text are fully gone). Launched the built exe; `startup.log` showed a clean start (`Starting NC 공구 리스트 생성기 v1.4.3`, frozen=True) with no traceback, and the process was closed normally.
- Installer/package: Recreated `installer/NC_Tool_List_Setup_v1.4.3.exe` from PyInstaller onedir output `dist/NC_Tool_List/NC_Tool_List.exe`. Also recreated `installer/NC_Tool_List_Portable_v1.4.3.zip`.
- Installer SHA-256: 587ED5C5A195A917EB9C3080738BBFE0D6FE0A038F2334686DB8E3B48DFF5FA5
- Portable ZIP SHA-256: DF6BDAF97CFD26B349C0CB245A76710C25CE8FFCC219AD04755A937B8526F4F0
- App SHA-256: A40B176D5B3B98C2A1E829163F960DA35AB89EA9A6F812EAD8477E532304965F
- Not yet done for 1.4.3: an actual admin-elevated install/uninstall pass to `C:\NC_Tool_List` (skipped here to avoid making a system-level change to this machine without confirmation).
- Signature status: still unsigned; code signing remains the real fix for SmartScreen/"Unknown Publisher" — see "보안 PC 대응 판단" 근본 해결책.

### Field test on one secured plant PC (2026-09-04)

- Install succeeded via `NC_Tool_List_Setup_v1.4.3.exe`; the window flashed and closed immediately on launch, but only on this one PC — other PCs tested fine.
- `startup.log` on the affected PC showed only the `Starting NC 공구 리스트 생성기 v1.4.3` line with no exception/traceback recorded, meaning the process died before or during Qt/window init, not from a caught Python exception.
- Windows Event Viewer (`Application` log, exported as evtx) showed:
  - `Application Error` (Id 1000): Faulting application `NC_Tool_List.exe` 1.4.3.0, faulting module `ntdll.dll`, exception code `0xC0000409` (STATUS_STACK_BUFFER_OVERRUN / __fastfail).
  - `Windows Error Reporting` (Id 1001): Fault bucket type 5, Event Name `BEX64`.
- AhnLab V3 was installed on the affected PC but showed no threat/detection record. Tested with the app path excluded from AhnLab, and again with AhnLab real-time protection fully disabled — the exact same crash still occurred both times.
- Conclusion: ruled out AhnLab as the cause. The crash is treated as specific to that one PC's environment (background hooking agent other than AhnLab, or a GPU/graphics driver incompatibility with the bundled software-OpenGL fallback) rather than a defect introduced in v1.4.3 — the app starts cleanly (per `startup.log`) and only this one PC, among those tested, reproduces it.
- Follow-up if this recurs: identify any other security/monitoring agent (keyboard-security, document DRM, asset-management) on the affected PC, and/or test the app in Windows Safe Mode there to isolate a background hook vs. a graphics-driver cause.

### 2026-09-03

- Version: 1.4.2
- Release/build date: 2026-09-03
- Summary: Added a lightweight About popup viewer with application purpose, version, build/creation date, creator, and open source usage.
- Creator displayed: Hwang.seonmun
- Scope: About UI and installer/package only. No unrelated feature changes.
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup.
- Installer/package: Recreated `installer/NC_Tool_List_Setup_v1.4.2.exe` from PyInstaller onedir output `dist/NC_Tool_List/NC_Tool_List.exe`.
- Packaging note: Changed from single-file PyInstaller output to onedir output with UPX disabled, matching the TSERP-style deployment structure more closely.
- Installer hardening: Switched installer target to TSERP-style `C:\NC_Tool_List` with no HKLM file association registry writes after security software still removed files during installation.
- C:\\NC_Tool_List install verification: Silent install completed, `C:\NC_Tool_List\NC_Tool_List.exe` and `C:\NC_Tool_List\_internal` were created, and installed app launch passed.
- Verification: Unit tests passed, built app launch passed, installer install/run/uninstall/reinstall passed.
- Installer SHA-256: 4969694A2761CE838AE33D131127FED9B41DAF792ACF574E42C809D62881B18F
- Portable ZIP: Created `installer/NC_Tool_List_Portable_v1.4.2.zip` for no-installer deployment.
- Portable ZIP SHA-256: F13AC4E04F1D4D912B53B9B92D667893DF829924B9CEC1ED8B9AC6F478A9779B
- App SHA-256: 0769E952A85CF2321133FD78F1A0BA5154749FEDA1F016816684A205463AB8D4
- Runtime hardening: Added startup logging, software OpenGL preference, OpenGL viewer fallback, and reduced bundled OpenGL submodules after installed app was reported to exit immediately on secured PCs.
- OpenGL fallback log path: `%LOCALAPPDATA%\NC_Tool_List\startup.log`.
- Signature status: Installer and app executable are unsigned; code signing is still required for maximum SmartScreen/endpoint trust.
