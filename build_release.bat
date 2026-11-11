@echo off
rem build_release.bat      - signed release APK  -> out\SumPath_vX.Y.Z.apk
rem build_release.bat aab  - signed Play AAB     -> out\SumPath_vX.Y.Z.aab  (build_aab.bat calls this)
rem Needs keystore.properties (see keystore.properties.example). Setup: SETUP_WINDOWS.md
setlocal EnableExtensions
cd /d "%~dp0"

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found.
    goto :fail
)
if not exist keystore.properties (
    echo [ERROR] keystore.properties not found. Copy keystore.properties.example and fill it in.
    goto :fail
)
if not defined JAVA_HOME if exist "C:\dev\jdk-21\bin\java.exe" set "JAVA_HOME=C:\dev\jdk-21"
if not defined JAVA_HOME if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%ProgramFiles%\Android\Android Studio\jbr"
if not defined JAVA_HOME (
    echo [ERROR] JDK not found.
    goto :fail
)
if not defined ANDROID_HOME if exist "%LOCALAPPDATA%\Android\Sdk" set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not defined ANDROID_HOME (
    echo [ERROR] Android SDK not found.
    goto :fail
)
set "SDK_DIR=%ANDROID_HOME:\=/%"
> android\local.properties echo sdk.dir=%SDK_DIR%

for /f "delims=" %%V in ('node -p "require('./package.json').version"') do set "VER=%%V"
set "KIND=%~1"
if "%KIND%"=="" set "KIND=apk"
echo === Sum Path v%VER% release %KIND% ===

if not exist node_modules (
    echo [1/4] npm ci
    call npm ci
    if errorlevel 1 goto :fail
)
echo [2/4] web build
call npm run build
if errorlevel 1 goto :fail
echo [3/4] cap sync
call npx cap sync android
if errorlevel 1 goto :fail
echo [4/4] gradle release
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
echo Done: %OUTFILE%
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. See messages above.
pause
exit /b 1
