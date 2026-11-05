@echo off
rem ============================================================
rem  git_sync.bat - GitHub master 와 이 PC 의 master 를 같게 맞춘다
rem  작업 시작 전에 실행. 규칙: CLAUDE.md 1절, 절차: GIT_SYNC_PLAN.md
rem ============================================================
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 goto :nogit

echo [1/5] GitHub 에서 최신 정보 받기...
git fetch origin --prune
if errorlevel 1 goto :fail

echo [2/5] 커밋하지 않은 변경 확인...
set "DIRTY="
for /f "delims=" %%L in ('git status --porcelain --untracked-files=no') do set "DIRTY=1"
if defined DIRTY goto :dirty

for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD') do set "CUR=%%B"
if /i not "%CUR%"=="master" (
    echo     현재 브랜치 %CUR% 에서 master 로 전환합니다.
    git checkout master
    if errorlevel 1 goto :fail
)

echo [3/5] 로컬 master 와 GitHub master 비교...
for /f "tokens=1,2" %%a in ('git rev-list --left-right --count master...origin/master') do (
    set "AHEAD=%%a"
    set "BEHIND=%%b"
)
echo     로컬에만 있는 커밋: %AHEAD%  /  GitHub 에만 있는 커밋: %BEHIND%

if "%AHEAD%%BEHIND%"=="00" goto :same
if "%AHEAD%"=="0" goto :pull
if "%BEHIND%"=="0" goto :push
goto :diverged

:pull
echo [4/5] GitHub 의 새 커밋을 받습니다 - 빨리감기
git merge --ff-only origin/master
if errorlevel 1 goto :fail
goto :done

:push
echo [4/5] 로컬에만 있는 커밋을 GitHub 에 올립니다
git push origin master
if errorlevel 1 goto :fail
goto :done

:diverged
echo [4/5] 로컬과 GitHub 가 서로 다른 커밋을 가지고 있습니다. 병합합니다.
git branch "backup/local-master-%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%" master >nul 2>&1
git merge --no-edit origin/master
if errorlevel 1 goto :conflict
git push origin master
if errorlevel 1 goto :fail
goto :done

:same
echo [4/5] 이미 같습니다.

:done
echo [5/5] 최종 확인
git fetch origin >nul 2>&1
for /f "delims=" %%H in ('git rev-parse master') do set "LOCALH=%%H"
for /f "delims=" %%H in ('git rev-parse origin/master') do set "REMOTEH=%%H"
findstr /b /c:"APP_VERSION = " NC_Tool_List.py
if /i "%LOCALH%"=="%REMOTEH%" (
    echo     OK - 로컬 master 와 GitHub master 가 같습니다: %LOCALH:~0,7%
) else (
    echo     [주의] 아직 다릅니다. 로컬 %LOCALH:~0,7% / GitHub %REMOTEH:~0,7%
)
pause
exit /b 0

:dirty
echo.
echo [중지] 커밋하지 않은 변경이 있습니다. 먼저 git_publish.bat "메시지" 로 올리거나,
echo        필요 없으면 되돌린 뒤 다시 실행하세요.
git status --short --untracked-files=no
pause
exit /b 1

:conflict
echo.
echo [중지] 병합 충돌. 아래 파일을 고친 뒤 git add . 와 git commit 후 다시 실행하세요.
echo        취소하려면 git merge --abort
git diff --name-only --diff-filter=U
pause
exit /b 1

:nogit
echo [오류] git 이 설치되어 있지 않습니다. https://git-scm.com 에서 설치하세요.
pause
exit /b 1

:fail
echo.
echo [오류] git 명령이 실패했습니다. 위 메시지를 확인하세요.
pause
exit /b 1
