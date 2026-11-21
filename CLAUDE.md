# tool_list (Sum Path / NC Tool List) 작업 규칙

이 파일은 Claude Code가 세션 시작 때 읽는 저장소 규칙이다. 사람이 읽을 때도 같은 규칙이다.

## 1. Git 동기화 규칙 (항상 적용, 2026-11-05 사용자 지정)

**목표: GitHub와 Windows PC 로컬 저장소의 Git 데이터가 항상 같다.**

1. 메인 브랜치는 **`master`** 다. 릴리스·작업 결과는 모두 `master`에 모인다.
2. 작업이 끝나면 매번 **commit → push → `master`에 병합(merge) → push** 까지 한 번에 끝낸다.
   병합하지 않은 채로 작업 브랜치에만 남겨 두지 않는다.
3. GitHub 기본 브랜치 `agent/drag-drop-installer`는 `master`와 **같은 커밋**으로 맞춘다
   (병합 후 `git push origin master:agent/drag-drop-installer`, 빨리감기만 허용).
   기본 브랜치를 `master`로 바꾸면 이 단계는 필요 없다(GitHub → Settings → Branches → Default branch).
4. Windows PC에서 작업을 시작하기 전에 **`git_sync.bat`** 로 GitHub와 맞춘다. 끝낼 때는
   **`git_publish.bat "커밋 메시지"`** 로 2번을 한 번에 한다.
5. 강제 push(`--force`), 이력 다시 쓰기(rebase 후 force push), 남의 브랜치 삭제는 하지 않는다.
   로컬과 GitHub가 서로 갈라졌으면 `GIT_SYNC_PLAN.md` 순서대로 병합해서 맞춘다.
6. 클라우드(Claude Code) 세션에서는 지정된 작업 브랜치에 push → PR → `master`로 병합 →
   기본 브랜치 빨리감기까지 한다. 병합 후 Windows PC에서 `git_sync.bat`을 실행하라고 안내한다.

## 2. 버전 규칙

- `MAJOR.MINOR.PATCH`, 각 자리 0~9. 10이 되면 윗자리로(2.2.9 → 2.3.0, 2.9.9 → 3.0.0).
- `python bump_version.py`로 올린다(NC_Tool_List.py / NC_Tool_List.iss / version_info.txt 동시 갱신).
- 새 버전마다 `ABOUT_RELEASE_INSTRUCTIONS.md`의 Version history에 기록을 추가한다.

## 3. 기타

- 라이선스 서명 개인키(`*.pem`)와 발급한 `*.lic`, `license_server/data/`는 절대 커밋하지 않는다.
- `license_server/sumpath_license.py`는 루트 `sumpath_license.py`와 바이트 단위로 같게 유지한다.
- 설치본 빌드(PyInstaller onedir + Inno Setup)는 Windows 빌드 PC에서 한다.
- 2026-11-19 정리: 옛 계획 문서(`v1.6.7_PLAN.md`~`v2.3.4_PLAN.md`)와 `_archive/`를 저장소에서 지웠다. 코드 주석에 나오는
  `vX.Y.Z_PLAN.md`는 `git show fbcc0df:v1.8.0_PLAN.md`처럼 정리 전 커밋 `fbcc0df`에서 볼 수 있다.
- 로컬 `installer\`와 `tool_list_android\out\`에는 최신 빌드본만 남긴다(이전 버전 설치본·APK는 지운다).

## 4. 안드로이드 앱(tool_list_android)과 병행 작업 규칙 (항상 적용, 2026-11-17 지정 / 2026-11-19 단일 저장소로 이관)

**이 앱(데스크톱)과 하위 폴더 `tool_list_android/`(Sum Path Android)는 항상 같은 결과로 동작해야 한다.**

- 2026-11-19: 별도 저장소였던 `tool_list_android`를 이 저장소의 `tool_list_android/` 폴더로 옮겼다
  (`git subtree add`, 안드로이드 이력 포함, 원본 마지막 커밋 7bf2448 v2.0.1). 예전 폴더 `C:\dev\tool_list_android`는 지웠고,
  GitHub의 예전 저장소 `tool_list_android`는 더 이상 쓰지 않는다(push하지 않는다).
- 안드로이드 쪽 세부 규칙은 `tool_list_android/CLAUDE.md`를 따른다.

1. 로직(경로 계산·G코드 해석·소재 시뮬레이션·공구 리스트 등)을 바꾸면 **같은 작업·같은 커밋 묶음 안에서** 데스크톱(루트 `*.py`)과
   안드로이드(`tool_list_android/src/`)를 함께 고친다. 안드로이드에서 먼저 고친 경우도 데스크톱에 넣는다. 한쪽만 고치고 끝내지 않는다.
2. 안드로이드 골든 갱신: `tool_list_android` 폴더에서
   `..\..\nc_build_venv\Scripts\python.exe tools\golden\export_golden.py ..` (export_toolpath / export_zmap / export_lathe도 같은 방식, 원본 = 상위 폴더)로
   다시 뽑고, `tests/golden/SOURCE_REV`를 골든을 뽑은 시점의 커밋으로 갱신하고, `npm test`를 통과시킨다.
   데스크톱 쪽은 `python -m pytest tests`를 통과시킨다.
3. 버전은 각자 올린다(루트 `python bump_version.py` / `tool_list_android`에서 `npm run bump`). 양쪽 버전 기록
   (`ABOUT_RELEASE_INSTRUCTIONS.md` / `tool_list_android/ANDROID_PLAN.md`)에 상대 버전을 적는다.
4. Git은 이 저장소 하나다. 루트의 `git_sync.bat` / `git_publish.bat`으로 두 앱을 함께 commit → push → `master` 병합 → push 한다(1절).
5. 빌드본은 둘 다 만든다: 이 앱 설치본(PyInstaller + Inno Setup) + 안드로이드 release APK(`tool_list_android\build_release.bat`).
6. 안드로이드 서명 키스토어(`tool_list_android/sumpath-upload.jks`, `keystore.properties`)와 `node_modules/`는 Git에 없다.
   PC를 옮기면 따로 복사하고 `npm install`을 한다. 절대 커밋하지 않는다.

## 5. 화면(UI) 작업 규칙 — unslop (항상 적용, 2026-11-21 지정)

화면·스타일을 바꾸는 작업은 `unslop` 스킬 기준으로 점검하고 고친다. 데스크톱과 안드로이드는 같은 기준을 쓴다.

1. 색은 흑연 회색 + 강조색 하나. 바탕·패널·글자·테두리는 회색, 파랑은 선택·주 동작에만 쓴다. 그라디언트·글로우·색 그림자 금지.
2. 보더 투명도는 세 단계만(구분선 .10 / 컨트롤 .18 / 활성·호버 .32). 간격은 4px 격자, 글자 굵기 400/500/600.
3. 이모지·글자 기호(⚠ 등)를 아이콘으로 쓰지 않는다. 선 아이콘 한 세트(16px, 두께 1.5)를 쓴다.
4. 화면당 채운(진한) 버튼은 하나. 나머지는 테두리 버튼 또는 투명 버튼. 새 색은 `THEMES`(데스크톱)·`theme.ts`(안드로이드) 토큰으로만 추가한다.
5. 큰 화면 변경은 시안(지금/제안 비교)을 먼저 보여 주고 승인받은 뒤 고친다.
