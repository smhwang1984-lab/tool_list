@echo off
rem ============================================================
rem  git_publish.bat "커밋 메시지"
rem  commit - push - master 병합 - push - 기본 브랜치 맞추기 를 한 번에 한다.
rem  규칙: CLAUDE.md 1절
rem ============================================================
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "MSG=%~1"
if "%MSG%"=="" (
    echo 사용법: git_publish.bat "커밋 메시지"
    pause
    exit /b 1
)
set "DEFAULT_BRANCH=agent/drag-drop-installer"

for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD') do set "CUR=%%B"
echo 현재 브랜치: %CUR%

echo [1/6] 커밋...
git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%MSG%"
    if errorlevel 1 goto :fail
) else (
    echo     새로 커밋할 변경 없음
)

git fetch origin --prune
if errorlevel 1 goto :fail

if /i "%CUR%"=="master" goto :on_master

echo [2/6] 작업 브랜치 push: %CUR%
git push -u origin "%CUR%"
if errorlevel 1 goto :fail
echo [3/6] master 로 전환 후 GitHub master 받기
git checkout master
if errorlevel 1 goto :fail
git merge --no-edit origin/master
if errorlevel 1 goto :conflict
echo [4/6] %CUR% 를 master 에 병합
git merge --no-ff --no-edit "%CUR%"
if errorlevel 1 goto :conflict
goto :push_master

:on_master
echo [2-4/6] master 에서 작업 중 - GitHub master 받아 병합
git merge --no-edit origin/master
if errorlevel 1 goto :conflict

:push_master
echo [5/6] master push
git push origin master
if errorlevel 1 goto :fail
echo [6/6] GitHub 기본 브랜치 %DEFAULT_BRANCH% 를 master 와 같게 - 빨리감기만
git push origin master:%DEFAULT_BRANCH%
if errorlevel 1 echo     [주의] 기본 브랜치를 빨리감기할 수 없습니다. GIT_SYNC_PLAN.md 3단계를 보세요.

git fetch origin >nul 2>&1
for /f "delims=" %%H in ('git rev-parse master') do set "LOCALH=%%H"
for /f "delims=" %%H in ('git rev-parse origin/master') do set "REMOTEH=%%H"
findstr /b /c:"APP_VERSION = " NC_Tool_List.py
if /i "%LOCALH%"=="%REMOTEH%" (
    echo 완료 - 로컬 master = GitHub master = %LOCALH:~0,7%
) else (
    echo [주의] 로컬과 GitHub master 가 다릅니다. git_sync.bat 을 실행하세요.
)
pause
exit /b 0

:conflict
echo.
echo [중지] 병합 충돌. 아래 파일을 고친 뒤 git add . 와 git commit, 그리고 git_publish.bat 을 다시 실행하세요.
echo        취소하려면 git merge --abort
git diff --name-only --diff-filter=U
pause
exit /b 1

:fail
echo.
echo [오류] git 명령이 실패했습니다. 위 메시지를 확인하세요.
pause
exit /b 1
