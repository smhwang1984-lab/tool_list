@echo off
rem ============================================================
rem  build_release.bat      - 서명된 release APK (사내 직접 배포용) out\SumPath_vX.Y.Z.apk
rem  build_release.bat aab  - Play 스토어용 AAB out\SumPath_vX.Y.Z.aab  (build_aab.bat 이 이것을 부른다)
rem  필요: keystore.properties (make_keystore.bat 로 키스토어를 만든 뒤 keystore.properties.example 을 복사해 작성)
rem  준비: SETUP_WINDOWS.md (Node.js 22, Android Studio)
rem ============================================================
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

where node >nul 2>&1
if errorlevel 1 (
    echo [오류] Node.js 가 없습니다. SETUP_WINDOWS.md 1단계를 보세요.
    goto :fail
)

rem ---- JDK: Gradle 8.14 는 JDK 25 를 읽지 못한다(Android Studio 최신판 내장 JBR 이 25). JDK 21 을 우선 쓴다 ----
if not defined JAVA_HOME if exist "C:\dev\jdk-21\bin\java.exe" set "JAVA_HOME=C:\dev\jdk-21"
rem ---- JDK: JAVA_HOME 이 없으면 Android Studio 내장 JBR 을 쓴다 ----
if not defined JAVA_HOME if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%ProgramFiles%\Android\Android Studio\jbr"
if not defined JAVA_HOME (
    echo [오류] JDK 를 찾을 수 없습니다. Android Studio 를 설치하거나 JAVA_HOME 을 설정하세요.
    goto :fail
)

rem ---- Android SDK ----
if not defined ANDROID_HOME if exist "%LOCALAPPDATA%\Android\Sdk" set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not defined ANDROID_HOME (
    echo [오류] Android SDK 를 찾을 수 없습니다. Android Studio 를 한 번 실행해 SDK 를 설치하세요.
    goto :fail
)
set "SDK_DIR=%ANDROID_HOME:\=/%"
> android\local.properties echo sdk.dir=%SDK_DIR%

for /f "delims=" %%V in ('node -p "require('./package.json').version"') do set "VER=%%V"
if not exist keystore.properties (
    echo [오류] keystore.properties 가 없습니다. make_keystore.bat 로 키스토어를 만들고 keystore.properties.example 을 복사해 작성하세요.
    goto :fail
)
set "KIND=%~1"
if "%KIND%"=="" set "KIND=apk"
echo === Sum Path Android v%VER% release %KIND% 빌드 ===
echo     JAVA_HOME   = %JAVA_HOME%
echo     ANDROID_HOME= %ANDROID_HOME%

if not exist node_modules (
    echo [1/4] 패키지 설치 - 처음 한 번만 오래 걸립니다
    call npm ci
    if errorlevel 1 goto :fail
) else (
    echo [1/4] 패키지 설치됨
)

echo [2/4] 웹 앱 빌드 - 타입 검사 포함
call npm run build
if errorlevel 1 goto :fail

echo [3/4] Android 프로젝트에 복사
call npx cap sync android
if errorlevel 1 goto :fail

echo [4/4] Gradle release 빌드
pushd android
if /i "%KIND%"=="aab" (call gradlew.bat bundleRelease) else (call gradlew.bat assembleRelease)
set "GRADLE_ERR=%ERRORLEVEL%"
popd
if not "%GRADLE_ERR%"=="0" goto :fail

if not exist out mkdir out
if /i "%KIND%"=="aab" (
    set "OUTFILE=out\SumPath_v%VER%.aab"
    copy /y "android\app\build\outputs\bundle\release\app-release.aab" "%OUTFILE%" >nul
) else (
    set "OUTFILE=out\SumPath_v%VER%.apk"
    copy /y "android\app\build\outputs\apk\release\app-release.apk" "%OUTFILE%" >nul
)
if errorlevel 1 goto :fail
echo.
echo 완료: %OUTFILE%
pause
exit /b 0

:fail
echo.
echo [오류] 빌드가 실패했습니다. 위 메시지를 확인하세요.
pause
exit /b 1
