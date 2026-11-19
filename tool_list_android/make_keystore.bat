@echo off
rem make_keystore.bat - create the upload keystore (sumpath-upload.jks) once.
rem keytool asks for the password itself. Back up the .jks and the password somewhere safe.
setlocal EnableExtensions
cd /d "%~dp0"
if exist sumpath-upload.jks (
    echo [STOP] sumpath-upload.jks already exists. Not overwriting.
    pause
    exit /b 1
)
if not defined JAVA_HOME if exist "C:\dev\jdk-21\bin\java.exe" set "JAVA_HOME=C:\dev\jdk-21"
if not defined JAVA_HOME if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%ProgramFiles%\Android\Android Studio\jbr"
if not defined JAVA_HOME (
    echo [ERROR] JDK not found.
    pause
    exit /b 1
)
"%JAVA_HOME%\bin\keytool.exe" -genkeypair -v -keystore sumpath-upload.jks -alias sumpath-upload -keyalg RSA -keysize 2048 -validity 10000
if errorlevel 1 (
    echo [ERROR] keystore was not created.
    pause
    exit /b 1
)
echo.
echo Done: sumpath-upload.jks
echo Next: copy keystore.properties.example to keystore.properties and fill in the password.
pause
