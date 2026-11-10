# tool_list_android (Sum Path Android) 작업 규칙

원본 데스크톱 앱 `smhwang1984-lab/tool_list`(PyQt5)를 Android APK로 옮기는 저장소다.
전환 계획은 `ANDROID_PLAN.md`(2026-11-10 승인됨), 단계별 실행 작업은 `WORK_PLAN.md`에 있다. 작업 ID(Pn-Tm) 순서대로 진행하고, 진행 기록은 `ANDROID_PLAN.md` 10절에 적는다.

## 1. Git 동기화 규칙 (tool_list와 같다)

1. 메인 브랜치는 **`master`** 다.
2. 작업이 끝나면 매번 commit → push → `master`에 병합 → push 까지 한 번에 끝낸다.
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
