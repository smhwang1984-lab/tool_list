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
