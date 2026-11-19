# tool_list_android (Sum Path Android) 작업 규칙

원본 데스크톱 앱(PyQt5, 상위 폴더 `tool_list`)을 Android APK로 옮긴 앱이다.
**2026-11-19부터 별도 저장소가 아니라 `tool_list` 저장소의 `tool_list_android/` 폴더다**(`git subtree add`로 이력 포함 이관,
예전 저장소 마지막 커밋 7bf2448 v2.0.1). 예전 폴더 `C:\dev\tool_list_android`와 GitHub 예전 저장소 `tool_list_android`는 쓰지 않는다.
전환 계획은 `ANDROID_PLAN.md`(2026-11-10 승인됨), 단계별 실행 작업은 `WORK_PLAN.md`에 있다. 작업 ID(Pn-Tm) 순서대로 진행하고, 진행 기록은 `ANDROID_PLAN.md` 10절에 적는다.

## 1. Git 동기화 규칙 (상위 `tool_list/CLAUDE.md` 1절을 따른다)

1. Git 저장소는 `tool_list` 하나다. 메인 브랜치는 **`master`**.
2. 작업이 끝나면 매번 commit → push → `master`에 병합 → push 까지 한 번에 끝낸다. 상위 폴더의 `git_sync.bat` / `git_publish.bat`을 쓴다
   (이 폴더의 예전 git_*.bat은 지웠다).
3. 강제 push, 이력 다시 쓰기, 남의 브랜치 삭제는 하지 않는다.
4. 클라우드 세션에서는 지정된 작업 브랜치에 push → PR → `master`로 병합한다. 병합한 뒤에는 Windows PC에서 `git_sync.bat`을 실행하라고 안내한다.

## 2. 버전 규칙

- 이 앱은 원본 데스크톱 앱과 **별도 프로그램**이다. 버전은 원본과 따로 매긴다(원본 버전을 About에 표시하지 않는다).
- `MAJOR.MINOR.PATCH`, 각 자리 0~9. **1.0.0**에서 시작했다(2026-11-10). 단계(P)가 끝날 때마다 MINOR를 올린다(`npm run bump -- --minor`).
- 로직 정답 비교에 쓴 원본 커밋은 `tests/golden/SOURCE_REV`에만 기록한다.

## 3. 기타

- 라이선스 기능은 보류한다(넣지 않는다).
- 서명 키스토어(`*.jks`, `*.keystore`, `keystore.properties`)는 절대 커밋하지 않는다.
- 빌드·서명·기기 테스트는 Windows 11 Home PC에서 한다.
- 이식한 로직은 원본 Python 결과(골든 JSON)와 같아야 한다.

## 4. 원본(데스크톱 tool_list)과 병행 작업 규칙 (항상 적용, 2026-11-17 지정 / 2026-11-19 단일 저장소)

**원본 데스크톱 앱(상위 폴더 `C:\dev\tool_list`)과 이 앱은 항상 같은 결과로 동작해야 한다.**

1. 원본의 로직(경로 계산·G코드 해석·소재 시뮬레이션·공구 리스트 등)이 바뀌면 같은 작업 안에서 이 폴더에도 옮긴다. 한쪽만 고치고 끝내지 않는다.
2. 옮긴 뒤 이 폴더에서 `..\..\nc_build_venv\Scripts\python.exe tools\golden\export_golden.py ..`
   (export_toolpath / export_zmap / export_lathe도 같은 방식, 원본 = 상위 폴더 `..`)로 골든을 다시 뽑고,
   `tests/golden/SOURCE_REV`를 골든을 뽑은 시점의 커밋으로 갱신하고, `npm test`를 통과시킨다.
3. 이 앱에서 먼저 로직을 고친 경우에도 원본에 같은 수정을 넣는다.
4. 버전은 따로 올린다(원본 `bump_version.py`, 이 앱 `npm run bump`). `ANDROID_PLAN.md` 버전 기록에 "원본 vX.Y.Z 따라가기"로 적는다.
5. 두 앱의 변경은 같은 저장소에서 함께 commit → push → `master` 병합 → push까지 끝낸다. 빌드본을 만들 때는 둘 다 만든다(원본 설치본 + 이 앱 release APK).
6. UI처럼 플랫폼에 따라 다를 수밖에 없는 부분은 같은 기능·같은 동작을 목표로 하고, 다르게 둔 부분은 이유를 기록한다.
