@echo off
rem ============================================================
rem  make_keystore.bat - 업로드 키스토어(sumpath-upload.jks)를 한 번 만든다.
rem  비밀번호는 keytool 이 직접 묻는다(화면·기록에 남지 않음). 만든 뒤
rem  keystore.properties.example 을 keystore.properties 로 복사해 같은 비밀번호를 적는다.
rem  *** 키스토어와 비밀번호를 잃으면 앱 업데이트를 올릴 수 없다. 안전한 곳에 따로 백업할 것. ***
rem ============================================================
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
if exist sumpath-upload.jks (
    echo [중단] sumpath-upload.jks 가 이미 있습니다. 덮어쓰지 않습니다.
    pause
    exit /b 1
)
if not defined JAVA_HOME if exist "C:\dev\jdk-21\bin\java.exe" set "JAVA_HOME=C:\dev\jdk-21"
if not defined JAVA_HOME if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%ProgramFiles%\Android\Android Studio\jbr"
if not defined JAVA_HOME (
    echo [오류] JDK 를 찾을 수 없습니다.
    pause
    exit /b 1
)
"%JAVA_HOME%\bin\keytool.exe" -genkeypair -v -keystore sumpath-upload.jks -alias sumpath-upload -keyalg RSA -keysize 2048 -validity 10000
if errorlevel 1 (
    echo [오류] 키스토어를 만들지 못했습니다.
    pause
    exit /b 1
)
echo.
echo 완료: sumpath-upload.jks
echo 다음: keystore.properties.example 을 keystore.properties 로 복사하고 비밀번호를 적으세요.
pause
