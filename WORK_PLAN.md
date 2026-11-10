# Sum Path Android — 실행 작업 플랜 (P1 ~ P7)

- 작성일: 2026-11-10 · 현재 상태: **P0 완료, P1 진행 중 (v1.0.0)**
- 버전: 원본과 별도 프로그램이므로 **1.0.0**에서 새로 시작한다(2026-11-10 결정, 처음 계획의 0.x 번호를 아래처럼 바꿈). 단계가 끝날 때마다 MINOR +1.
- 상위 문서: `ANDROID_PLAN.md`(무엇을, 왜). 이 문서는 **어떻게, 어떤 순서로**를 적는다.
- 원본 기준: `smhwang1984-lab/tool_list` `master` @ `0a1d5a3` (골든은 실행 시점의 원본 HEAD를 `tests/golden/SOURCE_REV`에 기록)
- 원칙
  1. **원본 Python = 정답.** 옮긴 로직은 원본과 출력이 같아야 끝난 것으로 본다.
  2. **작업 단위(T) 하나 = 커밋 하나 이상**, 단계(P)가 끝날 때마다 버전을 올리고 `master`에 병합한다.
  3. 라이선스는 넣지 않는다. 원본의 Windows 전용 기능은 Android 방식으로 바꾸거나 뺀다(ANDROID_PLAN §4).

---

## 0. 한눈에 보기

| 단계 | 버전 | 결과물 | 선행 단계 | 규모(작업일) |
|---|---|---|---|---|
| P0 앱 뼈대 | 1.0.0 | ✅ 완료 | — | — |
| **P1 핵심 로직 이식** | 1.1.0 | 공구 리스트 산출 엔진(TS) + 골든 테스트 | P0 | 5~7 |
| **P2 화면** | 1.2.0 | 입력창·공구표·대화상자·설정 (원본과 같은 구성) | P1 | 5~7 |
| **P3 파일·출력** | 1.3.0 | 열기/공유 받기/저장/편집 모드/PDF/표 복사 | P2 | 3~4 |
| **P4 3D 뷰어** | 1.4.0 | 툴패스·뷰 전환·방향 큐브·공정 필터·위치 찍기·PG 매칭 재생 | P1 (P2와 병행 가능) | 7~10 |
| **P5 제스처** | 1.5.0 | 마우스 → 터치 대응 전부 | P4 | 3~4 |
| **1차 테스트 배포** | 1.6.0 | 현장 테스트용 debug APK | P1~P5 | 1~2 |
| **P6 형상 시뮬레이션** | 1.7.x | 밀링 Z-map → 3D 복셀 → 선반 → 턴밀 | P4 | 10~15 |
| **P7 정식 배포** | 1.8.0 | 서명 키, release APK, **AAB** | 전부 | 2 |

진행 순서: `P1 → (P2 ∥ P4) → P3 → P5 → 1.6.0 테스트 배포 → P6 → P7`

---

## 1. 공통 작업 방식

### 1.1 브랜치·커밋·병합 (CLAUDE.md 1절)
- **클라우드 세션:** 지정된 작업 브랜치에서 작업 → push → PR → `master`에 병합. 병합한 뒤 Windows PC에서 `git_sync.bat`을 실행하도록 안내한다.
- **Windows PC:** 작업 시작 전에 `git_sync.bat`, 끝날 때 `git_publish.bat "메시지"`.
- 커밋 메시지는 `vX.Y.Z Pn-Tm: 요약` 형식으로 쓴다(예: `v1.1.0 P1-T3: 밀링 parse_program 이식`).

### 1.2 버전 올리기
- 단계가 끝날 때 다음 세 곳을 함께 바꾼다. **P1-T0에서 `bump_version.mjs`를 만들어 한 번에 바꾸게 한다.**
  - `package.json` → `version`
  - `src/version.ts` → `APP_VERSION`
  - `android/app/build.gradle` → `versionName`, `versionCode`(= M×100 + m×10 + p)
  - 실행: 단계 끝 `npm run bump -- --minor`, 중간 수정 `npm run bump`, 직접 지정 `npm run bump -- --set X.Y.Z`
- `ANDROID_PLAN.md` §10 진행 기록에 한 줄을 추가한다.

### 1.3 단계마다 끝내기 전 점검 (공통 완료 조건)
1. `npm run build`가 통과한다(타입 검사 포함).
2. `npm test`가 통과한다(골든 비교 포함).
3. Playwright로 가로 화면(태블릿 1280×800, 폰 800×360)을 캡처해 확인하고(세로는 지원하지 않는다), 콘솔 오류가 없어야 한다.
4. **Windows PC:** `build_apk.bat install` → 실기기에서 그 단계의 점검표를 확인한다.

### 1.4 소스 폴더 구조 (P1부터 채움)

```
src/
├─ core/        원본 순수 로직 이식 (DOM·Capacitor 사용 금지 → Node 테스트 가능)
├─ sim/         형상 시뮬레이션 (P6, Web Worker)
├─ viewer/      Three.js 뷰어, 오버레이, 제스처 (P4·P5)
├─ ui/          화면 구성 요소·대화상자 (P2)
├─ platform/    파일·공유·PDF·클립보드·설정 저장 (P3, Capacitor)
└─ main.ts
tests/
├─ golden/      원본 Python이 만든 정답 JSON (커밋함)
├─ fixtures/    샘플 NC (커밋함, 저장소는 Private)
└─ *.test.ts
tools/golden/   정답 생성 스크립트 (Python, 원본 저장소를 읽음)
```

---

## P1. 핵심 로직 이식 (v1.1.0)

**목표:** NC 텍스트를 넣으면 원본과 **똑같은** 공구 리스트(밀링 16열 / 선반 14열), 경고, 메타데이터, 코드 색, 검색 결과가 나온다. 화면은 없다.

### 원본 → TS 대응표

| TS 모듈 (`src/core/`) | 원본 (NC_Tool_List.py 줄 번호 / 파일) | 내용 |
|---|---|---|
| `columns.ts` | `COLUMNS` 646, `LATHE_COLUMNS` 215, 칸 폭 상수 | 표 열 정의 |
| `text.ts` | `code_without_comments` 493, `fmt_num` 1172, `normalize_metadata_key` 719 | 공통 문자열 처리 |
| `metadata.ts` | `parse_program_metadata` 723, `program_header_text` 753, 메타 키 표 | 출력 정보(프로그램/시간/날짜) |
| `nameTypes.ts` | `clean_name_types` 1216, `derive_type` 1616, `derive_d` 1625, 기본 변환표 | 이름 → TYPE / D |
| `radiusComp.ts` | `_subprogram_bodies` 518 ~ `_format_remark` 592 | G41/G42 → REMARK |
| `alerts.ts` | `spindle_alert_text` 1652, `h_number_alert_text` 1673, `so_alert_text` 1683, `_collect_mill_block_checks` 1817 | 스핀들·H번호·SO 경고 |
| `millParser.ts` | `parse_program` 1692, `tool_name_map_from_rows` 1830, `tool_shape_map_from_rows` 1855 | **밀링 공구 리스트** |
| `latheParser.ts` | `LatheRow` 224, `_lathe_*` 233~283, `parse_lathe_program` 290, `lathe_tool_name_map_from_rows` 470, `is_lathe_machine` 485 | **선반 공구 리스트** |
| `latheInsertSpec.ts` | `lathe_insert_spec.py` 전체(855줄). 단 `LatheSpecStore`는 P3의 `platform/`로 | ISO 인서트·홀더 해석, 자동 추천 |
| `ncColor.ts` | `nc_color_line` 1388 | 코드 색 구간 계산(입력창 색칠에 사용) |
| `search.ts` | `find_next/prev_regex_span` 1071~, `find_next/prev_tool_change_span` 1111~, `line_has_m00/m01/program_stop` 1131~, `line_stops_playback` 1146, `find_next_literal_span` 1157 | 공구 이동, 문자 검색, 재생 정지 판정 |
| `programText.ts` | `program_text_digest` 1332, `decode_program_bytes` 1345, `save_program_text`의 인코딩 부분 1363 | 인코딩 판별·저장, 변경 감지용 다이제스트 (**PG ADD 이어붙이기 `compose_program_texts`·`append_nc_programs`는 Android 버전에서 제외** — 2026-11-10 결정) |
| `password.ts` | `_edit_password_hash` 1287, `verify_edit_password` 1291, `set_edit_password` 1307 | 편집 모드 비밀번호(PBKDF2) |
| `machineSpecs.ts` | `nc_viewer_widget.py` `DEFAULT_MACHINE_SPECS` 179, `RENAMED_MACHINE_TYPES` 167 | 장비 타입·스펙 기본값 |

> 줄 번호는 원본 `0a1d5a3` 기준이다. 원본이 바뀌면 `tools/golden/SOURCE_REV`의 커밋과 비교해 차이를 다시 옮긴다.

### 작업 순서

| ID | 작업 | 완료 기준 |
|---|---|---|
| **T0** | `tools/bump_version.mjs`(3곳 동시 갱신 + 0~9 자리올림), `npm run bump`. 테스트 추가 | `node tools/bump_version.mjs`를 실행하면 PATCH가 오르고(자리올림 포함) 테스트가 통과한다. ✅ 이 도구로 1.0.0 설정 |
| **T1** | **골든 생성기** `tools/golden/export_golden.py` 작성 (아래 1.1) | Windows에서 실행하면 `tests/golden/*.json`이 생긴다 ✅ (함수 72개·호출 8,880건, 샘플 NC 11개) |
| **T2** | `text` · `columns` · `metadata` · `nameTypes` (+ Python 동작 맞추기 `py.ts`) | 해당 골든 100% 일치 ✅ |
| **T3** | `radiusComp` · `alerts` · **`millParser`** (+ 공용 정규식 `patterns.ts`) | 밀링 골든(원본 테스트 입력 + `O3210_excerpt.nc` + `ncdata.nc`) 100% 일치 ✅ (샘플 NC 11개 전부 일치) |
| **T4** | **`latheInsertSpec`** (원본 테스트 67개 → 골든) + 직접 입력 저장소 `latheSpecStore`(메모리 부분) | 100% 일치 ✅ (함수 28개 약 1,400건 + 저장소 6사례·갱신 2건; 파일 입출력은 P3-T9) |
| **T5** | **`latheParser`** | 선반 골든 100% 일치 ✅ (샘플 선반 NC 7개 행·값 출처, 저장소 포함 6사례, 원본 호출 기록) |
| **T6** | `ncColor` · `search` | 골든 100% 일치 ✅ (색 3,000줄 + 샘플 11개×4,000줄, 검색·정지 판정 약 500건) |
| **T7** | `programText`(CP949는 원본 Python 표를 `cp949Table.ts`로 내장 — WebView·Node `euc-kr`은 표가 달라 못 씀) · `password`(WebCrypto PBKDF2, 원본 해시 형식과 호환) | 100% 일치 ✅ (읽기 33·저장 108·비밀번호 확인 125건, CP949 2바이트 17,048글자 전체). PG ADD는 제외 |
| **T8** | 성능 확인: `ncdata.nc`(600KB) 산출 시간 측정 | PC Node 기준 200ms 이하 ✅ (65ms, `tests/perf.test.ts`). 폰은 느릴 수 있어 P2에서 실기기 확인 |
| **T9** | 버전 1.1.0, 진행 기록, 병합 | 공통 완료 조건 ✅ |

### 1.1 골든 생성 방식 (T1)

원본 저장소에는 이미 **pytest 테스트가 약 660개**(라이선스 제외) 있다(그중 `test_nc_tool_list.py` 266개, `test_lathe_insert_spec.py` 67개). 이 입력을 그대로 재사용한다.

1. **함수 호출 기록:** `export_golden.py`가 원본 pytest를 **기록 모드**로 실행한다. 대상 함수(위 대응표의 함수들)를 감싸서 `(함수 이름, 인자, 결과)`를 JSON으로 남긴다.
   → 원본 테스트를 하나하나 손으로 옮기지 않아도 같은 입력·정답 쌍이 생긴다.
2. **샘플 NC 전체 산출:** `tests/fixtures/*.nc`마다 밀링·선반 모드로 `parse_program` / `parse_lathe_program`을 돌린 결과를 저장한다.
3. 결과는 `tests/golden/<모듈>.json`에 쓰고, 기준 원본 커밋을 `tests/golden/SOURCE_REV`에 적는다.
4. TS 쪽 `tests/golden.test.ts`는 JSON을 읽어 같은 이름의 TS 함수로 다시 계산하고 비교한다.

- 실행 위치는 Windows PC다. 원본 `tool_list`를 같은 상위 폴더에 받아 두고 `..\nc_build_venv\Scripts\python.exe tools\golden\export_golden.py ..\tool_list`로 실행한다(원본 데스크톱 빌드용 Python 환경, 약 4~5분). 클라우드 세션에서도 원본을 클론해 실행할 수 있다.
- 원본 pytest 중 1건(`test_switching_to_lathe_changes_table_schema_and_machine`)은 이 PC에 저장된 장비 선택값 때문에 실패한다. 골든 내용과는 무관하다.
- 원본 테스트가 거의 부르지 않는 함수와 경계값(`fmt_num('1e-05')`, `clean_name_types` 등)은 `extra_calls()`에서 직접 불러 기록한다.
- Python과 JS의 차이 대응:
  - 숫자 포맷: `fmt_num`과 `'%g'` 계열은 TS 쪽에 같은 규칙의 함수를 만든다.
  - dict 순서: Python 3.7 이상의 삽입 순서를 그대로 따른다.
  - 정규식: Python `re`와 JS `RegExp`는 lookbehind와 `\d` 범위가 다르다. 정규식마다 골든으로 확인한다.
  - 반올림: Python `round`는 은행가 반올림이다. TS에 같은 반올림 함수를 둔다.
- 샘플 NC: 원본 `tests/data/O3210_excerpt.nc`, `ncdata.nc`, `test files/`의 밀링(O3210, 5ax A To C)과 선반(O1699, O2222, O4006, O4811, O4812, TurnMill Test, sub_pg test)을 `tests/fixtures/`로 복사했다(이 저장소는 Private, 바이트를 그대로 두도록 `.gitattributes`에 `-text`).

---

## P2. 화면 (v1.2.0)

**목표:** 원본과 같은 화면 구성으로 **산출까지** 된다. 파일 열기 대신 예제와 붙여넣기를 쓴다.

| ID | 작업 | 원본 근거 | 완료 기준 |
|---|---|---|---|
| **T1** | `ui/` 기본 부품: 버튼, 체크, 입력칸, 콤보, 대화상자(모달/비모달), 토스트, 길게 누르면 설명(툴팁 대체) | `_make_tool_button` 3499, 테마 | 라이트·다크 모두 원본 색과 같다 — 대화상자·확인창·토스트·길게 눌러 설명 ✅ (버튼·체크·콤보는 쓰이는 T4~T7에서 추가) |
| **T2** | **프로그램 입력창** = CodeMirror 6: 줄 번호, `ncColor` 색칠, 현재 줄 강조, 읽기 전용/편집 전환, 핀치 폰트 크기(저장), 큰 파일 성능 | `src` QPlainTextEdit, `nc_color_line`, 폰트 저장 4612 | `ncdata.nc`가 1초 안에 열리고 스크롤이 끊기지 않는다 ✅ (CodeMirror 6, 보이는 줄만 색칠, 핀치 글자 크기 저장. 편집 전환 UI는 P3 편집 모드에서 연결) |
| **T3** | **검색 줄**: 이전 공구 / 다음 공구 / 문자 검색 / 상태 표시, F5~F8 버튼 | search_bar, 단축키 3577 | 원본과 같은 줄로 이동한다(골든 `search` 재사용) ✅ (F6/F8 포함) |
| **T4** | **장비 타입·스펙 패널**: ▶/▼ 접기, 입력창을 탭하면 자동으로 접힘, 장비 타입 콤보(밀링/선반), 스펙 폼, "현재 장비 스펙 기록/저장" | 4085~4230 | 저장한 값이 앱을 다시 켜도 남는다 ✅ (Viewer 모드에서 표시, 산출 모드에서는 표 위 콤보로 전환. 입력창 탭 시 자동 접힘은 읽기 전용 입력창이 키보드를 띄우지 않으므로 P3 편집 모드와 함께 정리) |
| **T5** | **공구 리스트 표**("② 공구 리스트 (복사용)"): 16열/14열, 화면 폭에 맞춰 줄이기(하한 0.45) 후 가로 스크롤, 선택, 두 번 탭 또는 길게 누르면 수정, `공구 N개`, 출력 정보 | 4320~4400, `TOOL_TABLE_MIN_SCALE` | 원본 캡처와 열 순서·문구가 같다 ✅ (밀링 16열/선반 14열, 폭 맞춤·가로 스크롤, 경고 붉은 칸, (G41) 굵게, 선택, 두 번 탭/길게 누르기 → 수정 호출은 T7에서 연결) |
| **T6** | 표 버튼: 삭제 / 수정 / 행 추가 / 이름 경우의 수 / 머리글 포함 (PDF·표 복사는 P3) | 4360~4380 | 동작이 원본과 같다 ✅ (삭제 확인·수정·행 추가(T번호 자동)·이름 경우의 수·머리글 포함 체크. 머리글 포함은 P3 표 복사에서 사용) |
| **T7** | **대화상자**: 공구 행 수정·추가(+선반 "자동 추천"), 이름→TYPE 경우의 수 목록·수정, 저장 확인, 도움말(제스처 기준으로 다시 씀), About | 5127, 5165, 5978, 6017, 3592 | 원본과 같은 칸과 순서 ✅ 행 수정·추가(선반 자동 추천·저장값 전파·출처 규칙), 이름 경우의 수 목록·수정·기본값 복원. 도움말·About은 제스처가 정해지는 P5에서 다시 쓴다. 이름표·선반 직접 입력 값은 기기 설정에 저장 (파일 저장은 P3-T9) |
| **T8** | **설정 창**(비모달): 툴패스 선 굵기 10~100%, 감도, 큐브 크기, FOV(추가), 기본값으로 | `SettingsDialog` 2629 | 값을 바꾸면 바로 반영되고 저장된다 ✅ (선 굵기 10~100%·감도·큐브·FOV, 기본값으로. 값은 `platform/viewerSettings`가 저장·알림, 3D 반영은 P4) |
| **T9** | **필터 영역**(Viewer 모드에서 입력창 아래): 텍스트 정지+입력, 정지(M00), 옵션정지(M01), 실시간 형상(P6 전까지 비활성), 공정 필터 목록, 전체/해제, PG 매칭. 뷰어 연결은 P4 | 3360~3440 | 화면 배치가 원본과 같다 ✅ (정지 옵션 저장, 공정 목록·PG 매칭·Reset은 P4에서 연결, 실시간 형상·소재는 P6) |
| **T10** | **가로 전용 정리** (세로·탭 제거): 앱을 가로로 고정(`sensorLandscape`), 낮은 화면(폰 가로)용 압축 배치, 분할선 2개(좌우·입력/필터 상하), 안전 영역. 툴바는 가로 스크롤로 충분해 `⋯` 메뉴는 만들지 않음 | QSplitter 2개 | 폰 가로(800×360, 740×340)·태블릿(1280×800)에서 확인 ✅ |
| **T11** | 설정 저장소 `platform/prefs.ts` (`@capacitor/preferences`, 웹에서는 localStorage) | QSettings, `app_settings.json` | 테마·폰트·장비·이름표가 유지된다 ✅ 테마·글자 크기 (장비·이름표는 T4·T7에서 같은 저장소 사용) |
| **T12** | 1.2.0, 병합 | | 공통 완료 조건 + 실기기 확인 |

---

## P3. 파일·출력 (v1.3.0)

| ID | 작업 | Android 구현 | 완료 기준 |
|---|---|---|---|
| **T1** | 파일 열기 | `@capawesome/capacitor-file-picker`(SAF), 바이트 → `decode_program_bytes` | UTF-8 / CP949 / UTF-16 파일이 모두 열린다 |
| **T2** | ~~PG ADD~~ **제외** (2026-11-10 결정, Android 버전에는 넣지 않는다) | — | — |
| **T3** | **다른 앱에서 열기** | `AndroidManifest.xml` intent-filter(VIEW/SEND, `.nc .mpf .tap`, `text/plain`, `application/octet-stream`) + 앱 시작/재개 시 받기 | 파일 앱·카카오톡·메일 첨부에서 "Sum Path로 열기"가 된다 |
| **T4** | 편집 모드·비밀번호 | `password.ts`, 기본 1234, "✎ 편집 중" 표시, 입력창 테두리 강조 | 원본과 같은 흐름 |
| **T5** | 저장 | 원래 인코딩·줄바꿈을 유지하고 `.bak`를 남긴다. 쓰기 권한이 없으면 "다른 이름으로 저장"(SAF CreateDocument) | 저장한 파일을 PC 원본 앱에서 열어도 같다 |
| **T6** | 외부 변경 감지 | 앱 재개(resume) 때 파일 스탬프·다이제스트를 비교 → 새로고침/무시 창 | 원본 `파일 변경` 창과 같다 |
| **T7** | **PDF 출력** | `pdfmake` + Noto Sans KR 서브셋. 원본 표 스타일·열 폭·REMARK 굵게·SO 경고색·메타 행·파일명 규칙(`default_pdf_filename`)을 그대로. 만든 뒤 `@capacitor/share` 또는 PDF 뷰어로 열기 | 원본 PDF와 나란히 놓고 비교했을 때 같은 배치(밀링·선반 각 1건) |
| **T8** | 표 복사 | 클립보드에 TSV, 머리글 포함 옵션. "복사됨! 엑셀에서 붙여넣기" | 모바일 엑셀·구글 시트에 붙여넣으면 칸이 맞는다 |
| **T9** | 선반 스펙 저장소 | `LatheSpecStore` → `platform/latheSpecStore.ts` | 직접 입력한 스펙이 유지된다 |
| **T10** | 1.3.0, 병합 | | 실기기: 열기 → 산출 → PDF 공유 → 편집·저장 |

---

## P4. 3D 뷰어 (v1.4.0)

**핵심 위험:** 원본의 경로 계산 `NCViewerWidget.process_nc_lines`(nc_viewer_widget.py 4956~5959, 약 1,000줄)가 Qt 위젯 안에 있다.
→ **먼저 순수 로직으로 떼어 내고 골든으로 맞춘 뒤** 그리기를 붙인다.

### 원본 → TS 대응표

| TS 모듈 | 원본 (nc_viewer_widget.py) | 내용 |
|---|---|---|
| `core/toolpath.ts` | `process_nc_lines` 4956, `_expand_subprograms` 4711(M98 P L), `_lathe_n_blocks` 4654, `_arc_points` 6058, `ARC_PLANE_AXES` 134, 원호 허용오차 153~155, `get_rotation_matrix` 4922·`tool_axis_from_rotary` 4932·`get_5axis_rotation_matrix` 4945(G68.2/G43.4) | NC → 선분 목록(seq, 원본 줄, 공구, 이송/급속, 좌표) |
| `core/latheGeom.ts` | `lathe_local_point` 210 ~ `lathe_world_point` 267, C축 원호 | 선반 좌표계 |
| `core/timing.ts` | `effective_feed_mm_per_min` 298, `parse_dwell` 328, `lathe_spindle_rpm` 360, `_compute_machining_times` 5959, `format_duration` 401 | 가공 시간, 경과/총 시간 표시 |
| `core/playback.ts` | `sequence_length` 6336, `line_at_seq` 6341, `resolve_seq_for_line` 6350, `elapsed_seconds_at_*` 6461~, 정지 조건 | PG 매칭 재생 위치 계산 |
| `viewer/scene.ts` | `_build_path_items` 6137, `_render_segments` 6178, `TOOL_COLOR_MAPS` 85, 급속 색 92, 선 굵기 99~120 | Three.js `LineSegments2`, 공구별 색 |
| `viewer/camera.ts` | `OrthographicGLViewWidget` 569(원근/직교, orbit pivot, `_pan_to_keep_point`, `zoom_about_point`), `set_camera_angles` 4481, `_zoom_to_fit_distance` 4518 | 카메라 수식(원본 그대로) |
| `viewer/viewCube.ts` | `ViewCubeWidget` 1105, `_cube_face_corners` 1086 | 방향 큐브(면 탭·고리 드래그) |
| `viewer/overlays.ts` | `ProjectionOverlayWidget` 1349, `CoordOverlayWidget` 1495, `ZoomCenterMarker` 1317, 축 화살표 3175 | ISO/XY/XZ/YZ 버튼, 좌표, 노란 십자 |
| `viewer/playbackBar.ts` | `PlaybackBarWidget` 1546, 아이콘 481~531 | 이전 툴/되감기/재생·정지/다음 툴, 1x~5000x |
| `viewer/pick.ts` | `_build_pick_cache` 2934, `_nearest_pick_segment` 2993, `pick_source_line` 2969 | 위치 찍기 → 프로그램 줄 |

### 작업 순서

| ID | 작업 | 완료 기준 |
|---|---|---|
| **T1** | 골든 생성기 확장: 원본 `NCViewerWidget`을 `QT_QPA_PLATFORM=offscreen`으로 띄워 `process_nc_lines` 결과(선분·seq·줄 대응·시간)를 JSON으로 내보낸다. 원본 `test_nc_sim_viewer.py`, `test_nc_lathe_viewer.py`, `test_dwell.py`, `test_v233_live_reload.py`의 입력을 재사용한다 | 골든 JSON 생성 |
| **T2** | `core/toolpath.ts` · `latheGeom.ts` (밀링 → 선반 → 5축/G68.2 순서) | 좌표 오차 1e-6 이하, seq·줄 대응 100% |
| **T3** | `core/timing.ts` · `playback.ts` | 시간 오차 0.01초 이하 |
| **T4** | `viewer/scene.ts`: 경로 그리기, 공구별 색, 급속 빨강, 선 굵기 설정, 공정 필터 표시/숨김, 진행된 경로(trace) 강조 | 원본 캡처와 같은 색·모양 |
| **T5** | `viewer/camera.ts`: 원근/직교, ISO/XY/XZ/YZ, 전체 맞춤, 선반 평면 뷰 orbit 잠금 | 원본 `test_v234_mouse_zoom.py`, `test_v235_orbit_pivot.py` 기대값을 TS 테스트로 옮겨 통과 |
| **T6** | 방향 큐브·좌표 표시·투영 버튼·원점 화살표(큐브 크기 연동) | 원본과 같은 배치 |
| **T7** | **공정 필터 연결**: 다중 선택, 항목 탭 → 첫 줄 이동, 전체/해제, 공구 표시 문구(`_tool_display_text` 4876) | 원본과 같다 |
| **T8** | **PG 매칭 재생**: 입력창 커서 ↔ 경로 위치 양방향, 속도 1x~5000x, 텍스트 정지/M00/M01 정지, 이전/다음 툴, 되감기, 시간 표시 `00:00 / 00:00` | 원본과 같은 줄에서 멈춘다(골든) |
| **T9** | 위치 찍기 모드(우선 버튼으로 켬, 제스처는 P5) → 가장 가까운 선분 → 프로그램 줄로 이동, 깜빡임 표시 | 원본과 같은 줄 |
| **T10** | 성능: `ncdata.nc`를 Worker에서 파싱하고 BufferGeometry 한 덩어리로 그린다. 중급 폰에서 60fps 목표, 최소 30fps | 실기기 측정 기록 |
| **T11** | WebGL 실패 시 안내 + 2D(Canvas) XY 평면 보기로 대체 | 강제로 실패시켜 확인 |
| **T12** | 1.4.0, 병합 | 공통 완료 조건 |

---

## P5. 제스처 (v1.5.0)

`viewer/gestures.ts` 하나에 모은다. Pointer Events로 직접 구현하고, 카메라 조작은 `camera.ts` 함수만 부른다.

| ID | 제스처 | 동작 | 원본 대응 |
|---|---|---|---|
| **T1** | 한 손가락 드래그 | 처음 닿은 점 기준 회전(노란 십자 유지). 선반 평면 뷰에서는 이동 | 좌드래그 / orbit 잠금 |
| **T2** | 두 손가락 드래그 | 이동(pan) | Ctrl+좌드래그 |
| **T3** | 핀치 | 두 손가락 가운데 점 기준 확대·축소 + 십자 | 휠 |
| **T4** | 두 번 탭 | 전체 맞춤(Fit) | (신규, 승인됨) |
| **T5** | 두 번 탭한 뒤 누른 채 위아래로 끌기 | 한 손 연속 줌 | 휠 누르고 끌기 |
| **T6** | 세 손가락 위아래 드래그 | 원근감(FOV) | Ctrl+휠 (신규, 승인됨) |
| **T7** | 길게 누른 뒤(0.4초) 끌기 | 사각형 영역 확대 + 위치 찍기 모드 켜기 | 우드래그 |
| **T8** | 위치 찍기 모드에서 탭 | 프로그램 줄로 이동 / ✕ 칩·뒤로 버튼·뷰 전환으로 종료 | 좌클릭 / Esc·우클릭 |
| **T9** | 방향 큐브 | 면 탭 = 뷰 전환, 고리 드래그 = 부드러운 회전(터치 영역 넓힘) | 클릭/드래그 |
| **T10** | 입력창 핀치 | 글꼴 크기(저장) | Ctrl+휠 |
| **T11** | 표 | 탭 = 선택, 두 번 탭·길게 누르기 = 수정 | 클릭 / 더블클릭 |
| **T12** | 블루투스 키보드 | F5~F8, Ctrl+S, Esc 동작 | 단축키 |

공통 규칙과 테스트:
- 탭과 드래그를 가르는 기준은 8dp다.
- 손가락 수가 바뀌는 순간에는 기준점을 다시 잡아 화면이 튀지 않게 한다.
- 감도는 회전·이동·줌 모두에 곱한다.
- Android 뒤로 버튼은 다음 순서로 동작한다: 위치 찍기 종료 → 열린 대화상자 닫기 → 탭 이동 → 앱 종료 확인.
- 테스트는 Playwright 터치 시뮬레이션(CDP `Input.dispatchTouchEvent`)으로 시나리오마다 카메라 값을 비교한다. 실기기에서는 폰 1대와 태블릿 1대로 손 테스트를 하고 점검표를 남긴다.

---

## 1차 테스트 배포 (v1.6.0)

1. 도움말을 제스처 기준으로 다시 쓴다.
2. 원본과 Android로 **같은 NC 10건**(밀링 7, 선반 3)을 산출해 비교표를 만든다(`docs/compare_1.6.0.md`).
3. Windows에서 `build_apk.bat`로 `out\SumPath_v1.6.0_debug.apk`를 만들어 현장 테스트용으로 배포한다.
4. 피드백은 GitHub Issues에 모은다.

---

## P6. 형상 시뮬레이션 (v1.7.x)

| 버전 | ID | 내용 | 원본 |
|---|---|---|---|
| 1.7.0 | T1 | 밀링 공구 형상 `ToolShape`(평/코너R/볼/드릴 원뿔/챔퍼), `parse_stock_size_comment`, `StockSpec`, **소재 창**(STOCK SIZE 주석 읽기) | `nc_sim.py` 앞부분, `StockDialog` 1806 |
| 1.7.0 | T2 | **Z-map 절삭** `ZMapStock` + 메시(`mesh_from_grid`, 깊이 색, 모서리선) — Web Worker, 스냅샷/되감기 | `nc_sim.py`, `nc_sim_numba.py` 루프 |
| 1.7.1 | T3 | **3D 복셀** `VoxelStock` + `surface_nets`(경사면 G68.2·5축 G43.4 구간) | `nc_sim3d.py` |
| 1.7.2 | T4 | **선반** `LatheStock`(반단면 격자, 인서트 다각형, 회전체 메시, 단면 보기) + `LatheStockDialog` | `nc_lathe_sim.py` |
| 1.7.3 | T5 | **턴밀** `TurnMillStock` | `nc_lathe_sim.py` 뒷부분 |
| 1.7.4 | T6 | 실시간 형상 체크, 급속 절삭 경고, STL 내보내기(공유) | `write_stl_binary`, `rapid_cut_warnings` |

- 정답 비교: 원본 numpy 결과(높이맵·점유 격자)를 골든으로 저장한다(압축 바이너리, `.bin.gz`). 칸별 오차 허용치는 0.01mm, 다른 칸 비율은 0.1% 이하를 기준으로 한다.
- 모바일 상한: 격자 칸 수를 원본 자동 해상도의 1/4부터 시작해 실기기에서 조정한다. 설정에 "형상 정밀도(낮음/보통/높음)"를 둔다.
- 느리면: 핵심 루프를 **AssemblyScript → WASM**으로 바꾸는 작업(T7)을 넣는다. 이때 TS 구현은 정답 비교용으로 남긴다.

---

## P7. 정식 배포 (v1.8.0)

| ID | 작업 |
|---|---|
| T1 | 업로드 키스토어 만들기(`keytool`, Windows). 보관 위치·비밀번호 관리 방법을 정한다. **커밋 금지** (`keystore.properties`는 .gitignore) |
| T2 | `android/app/build.gradle` `signingConfigs.release`가 `keystore.properties`를 읽게 한다 |
| T3 | `build_release.bat` → 서명된 release APK (사내 직접 배포용) |
| T4 | `build_aab.bat` → `gradlew bundleRelease` → `out\SumPath_vX.Y.Z.aab` (Play 스토어용) |
| T5 | Play 콘솔 준비 목록(앱 이름, 개인정보처리방침, 스크린샷, 대상 API 36) 문서화 — 실제 등록은 사용자가 결정 |
| T6 | 1.8.0, 최종 점검표, 병합 |

---

## 7. 위험과 대응

| 위험 | 대응 |
|---|---|
| Python ↔ JS 숫자·정규식·반올림 차이 | 골든 테스트로 모든 함수를 비교한다. 차이가 생기면 TS 쪽에 원본과 같은 동작의 함수를 둔다 |
| `process_nc_lines`가 Qt와 얽혀 있음 | P4-T1에서 offscreen으로 원본을 실행해 결과만 뽑는다. 원본 코드는 고치지 않는다 |
| 큰 NC 파일 성능(입력창·뷰어) | CodeMirror 가상 스크롤, Worker 파싱, 한 덩어리 BufferGeometry |
| 형상 시뮬레이션 모바일 성능 | 1차 배포에서 분리, 해상도 상한, 필요 시 WASM |
| 한글 PDF 글꼴 크기 | Noto Sans KR을 쓰는 글자만 서브셋으로 넣는다(목표 1MB 이하) |
| CP949 저장 | `iconv-lite`로 인코딩하고 원본 앱에서 다시 열어 확인한다 |
| 클라우드에서 APK 빌드 불가 | APK 확인은 Windows PC에서 한다. 클라우드는 웹 빌드·테스트·캡처까지 한다 |
| 원본이 계속 바뀜 | `tests/golden/SOURCE_REV`로 기준 커밋을 고정하고, 원본이 새 버전이 되면 차이만 따라간다 |

---

## 8. 시작 전에 사용자에게 받을 것 (확인 사항)

1. **선반 샘플 NC**(가능하면 턴밀 포함) 2~3개, **밀링 샘플 NC** 추가 몇 개 — 비교·성능 기준으로 쓴다. 회사 데이터라면 Private 저장소에만 둔다.
2. **테스트 기기** 모델명(폰·태블릿) — 성능 목표와 화면 크기를 맞춘다.
3. 원본 앱에서 **밀링·선반 PDF 각 1부**와 **화면 캡처**(라이트/다크) — P2·P3에서 나란히 비교할 기준이다.
4. Windows PC에 원본 `tool_list`를 `tool_list_android`와 **같은 상위 폴더**에 받아 둔다(골든 생성용).

이 중 1·3은 없어도 시작할 수 있다. 원본 저장소의 테스트 데이터로 먼저 진행하고, 받으면 추가한다.

---

## 9. 바로 다음 작업

**P1-T0 ~ T2** (버전 스크립트 → 골든 생성기 → 공통 텍스트·메타데이터·이름표 이식).
"P1 시작"이라고 하시면 이 순서대로 진행한다.
