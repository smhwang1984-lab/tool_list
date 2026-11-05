# Windows PC ↔ GitHub 동기화 + v2.2.9 빌드 계획 (2026-11-05)

> 규칙(항상 적용)은 `CLAUDE.md` 1절. 이 문서는 **지금 한 번** 로컬과 GitHub를 맞추고 v2.2.9 설치본을 만드는 순서다.

## 0. 현재 GitHub 상태 (2026-11-05 정리 후)

| 브랜치 | 내용 |
|---|---|
| `master` (메인) | v2.2.9 (서버 라이선스 겸용 + 버전 규칙 + 홍보영상 생성기 + 이 규칙 문서) |
| `agent/drag-drop-installer` (GitHub 기본 브랜치) | `master`와 같은 커밋으로 맞춤 |

어긋났던 원인: 메인(`master`)과 GitHub 기본 브랜치(`agent/drag-drop-installer`)가 따로 있어서,
PR이 어떤 때는 `master`로, 어떤 때는 기본 브랜치로 병합됐다(예: #34 홍보영상은 기본 브랜치에만,
#35는 `master`에만). 앞으로는 모두 `master`로 병합하고 기본 브랜치를 같은 커밋으로 맞춘다.

## 1. Windows PC 상태 확인 (명령 프롬프트, 저장소 폴더에서)

```bat
git remote -v
git status
git branch -vv
git fetch origin --prune
git log --oneline -5 master
git log --oneline -5 origin/master
findstr /b /c:"APP_VERSION = " NC_Tool_List.py
```

- `git remote -v`가 `https://github.com/smhwang1984-lab/tool_list`를 가리키는지 확인한다.
- 결과에 따라 아래 2-A ~ 2-C 중 하나를 한다.

## 2. 한 번만 맞추기

**시작 전 백업**: 저장소 폴더를 통째로 복사해 둔다(예: `tool_list_backup_20261105`).

### 2-A. 커밋 안 한 변경이 있다 (`git status`에 수정 파일이 보임)

로컬에서 따로 2.2.9를 만들었다면 이 경우다. GitHub의 2.2.9와 내용이 다르므로 **버리지 말고 별도 브랜치로 올린다.**

```bat
git checkout -b local/windows-20261105
git add -A
git commit -m "Windows 로컬 작업 보관 (2026-11-05)"
git push -u origin local/windows-20261105
git checkout master
```

그다음 Claude 세션에 "local/windows-20261105 브랜치 내용을 검토해서 master에 병합해 줘"라고 요청한다
(같은 2.2.9라도 GitHub 쪽 변경과 겹치는 부분을 비교해 병합하고, 버전은 규칙대로 2.3.0으로 올린다).
그 뒤 2-B로 간다.

### 2-B. 커밋은 됐는데 GitHub와 다르다 / 그냥 맞추고 싶다

```bat
git_sync.bat
```

- GitHub 쪽만 앞서 있으면 받기(빨리감기), 로컬만 앞서 있으면 올리기, 둘 다 다르면
  `backup/local-master-날짜` 브랜치를 남기고 병합 후 올린다.
- 충돌이 나면 화면에 파일 목록이 나온다. 고친 뒤 `git add .` → `git commit` → `git_sync.bat` 다시 실행.

### 2-C. 저장소가 꼬여서 처음부터 받고 싶다

```bat
cd C:\
git clone https://github.com/smhwang1984-lab/tool_list.git tool_list_new
cd tool_list_new
git checkout master
```

기존 폴더에서 Git에 없는 파일(빌드용 venv, 테스트 NC 파일 등)만 새 폴더로 옮긴다.

**완료 기준**: `git_sync.bat` 마지막 줄이 `OK - 로컬 master 와 GitHub master 가 같습니다`, `APP_VERSION = '2.2.9'`.

## 3. GitHub 기본 브랜치를 master로 바꾸기 (권장, 한 번)

GitHub → tool_list → Settings → General → Default branch → `master`로 변경.
바꾸면 새 PR이 자동으로 `master`를 향해 다시 어긋날 일이 없다. 바꾼 뒤 `agent/drag-drop-installer`는 지워도 된다
(그때는 `git_publish.bat`의 `DEFAULT_BRANCH` 줄을 `master`로 고친다).

## 4. v2.2.9 빌드 (Windows 빌드 PC)

```bat
REM 빌드용 가상환경은 v2.2.8 때 쓰던 것을 그대로 활성화한다(새 패키지 없음)
py -m pip install pytest
py -m pytest tests -q
py -m PyInstaller NC_Tool_List.spec --noconfirm --clean
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" NC_Tool_List.iss
py -m PyInstaller SumPath_License_Maker.spec --noconfirm --clean
```

확인할 것:
1. `tests` 전체 — 특히 Linux에서 못 돌린 `tests/test_license.py::LicenseRegistrationDialogUiTests` 4개.
2. `installer\NC_Tool_List_Setup_v2.2.9.exe` 생성, 설치 후 실행 → About에 v2.2.9, 라이선스 묶음에 [라이선스 서버 설정...] 버튼.
3. 발급 프로그램 창 제목 v1.4.0, '서버 라이선스' 탭.
4. 결과(SHA-256, 크기, 통과/실패 수)를 `ABOUT_RELEASE_INSTRUCTIONS.md`의 v2.2.9 기록 "Installer/package status"에 적는다.
5. `git_publish.bat "v2.2.9 설치본 빌드 기록"` 으로 올린다(규칙: commit → push → master 병합).

## 5. 라이선스 서버(NAS) — 서버 라이선스를 쓸 때만

`license_server/DEPLOY_Synology.md` 순서대로. NAS 폴더 + 빈 `data` 폴더 → Container Manager 프로젝트 →
`http://NAS:8765`에서 서버 ID 확인 → 발급 프로그램 '서버 라이선스' 탭으로 발급 → 관리 화면에 등록 → PC에서 서버 주소 입력.

## 6. 앞으로 매번

| 언제 | 할 일 |
|---|---|
| 작업 시작 | `git_sync.bat` |
| 작업 끝 | `git_publish.bat "커밋 메시지"` → commit, push, master 병합, push, 기본 브랜치 맞추기 |
| 버전 올릴 때 | `py bump_version.py` → ABOUT 기록 추가 → `git_publish.bat` |
| Claude 클라우드 세션 | 작업 브랜치 push → PR → master 병합까지 Claude가 하고, 끝나면 Windows에서 `git_sync.bat` |
