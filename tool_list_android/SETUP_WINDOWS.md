# Windows 11 Home 빌드 환경 준비 (처음 한 번)

테스트용 **debug APK**를 만들어 휴대폰·태블릿에 설치하기까지의 순서다.
(Play 스토어용 **AAB**는 나중 단계에서 서명 키를 만든 뒤 따로 안내한다.)

## 1. Node.js 22 LTS

1. https://nodejs.org 에서 **22.x LTS** Windows Installer(.msi)를 받아 기본값으로 설치한다.
2. 새 명령 프롬프트에서 확인한다.
   ```bat
   node -v     :: v22.x 이상
   npm -v
   ```

## 2. Android Studio (SDK + JDK 포함)

1. https://developer.android.com/studio 에서 Android Studio를 받아 기본값으로 설치한다.
2. 처음 실행하면 나오는 **Setup Wizard → Standard**를 끝까지 진행한다. Android SDK, Platform-Tools(adb), 내장 JDK(JBR)가 함께 깔린다. **주의:** 최신 Android Studio의 내장 JBR이 JDK 25인 경우 이 프로젝트의 Gradle 8.14가 `Unsupported class file major version 69`로 실패한다. 그때는 JDK 21(Temurin)을 `C:\dev\jdk-21`에 풀어 두면 `build_apk.bat`이 먼저 쓴다.
3. **More Actions → SDK Manager**에서 다음이 설치돼 있는지 확인한다.
   - SDK Platforms: **Android 16 (API 36)**
   - SDK Tools: **Android SDK Build-Tools**, **Android SDK Platform-Tools**
4. 기본 설치 경로는 아래와 같다. `build_apk.bat`이 이 경로를 자동으로 찾는다.
   - SDK: `%LOCALAPPDATA%\Android\Sdk`
   - JDK: `C:\Program Files\Android\Android Studio\jbr`

   다른 곳에 설치했다면 시스템 환경 변수 `ANDROID_HOME`과 `JAVA_HOME`을 직접 설정한다.

## 3. 저장소 받기

```bat
cd /d C:\dev             :: 원하는 폴더
git clone https://github.com/smhwang1984-lab/tool_list
cd tool_list
git_sync.bat             :: 작업 시작 전에 항상 GitHub와 맞춘다(저장소 루트의 bat)
cd tool_list_android
npm install
```

> 2026-11-19부터 안드로이드 앱은 원본 저장소 `tool_list` 안의 `tool_list_android\` 폴더에 있다
> (예전 별도 저장소 `tool_list_android`는 더 이상 쓰지 않는다). 골든 데이터를 만들 때 원본은 상위 폴더 `..`이다.
> 서명 키스토어(`sumpath-upload.jks`, `keystore.properties`)는 Git에 없으므로 `tool_list_android\`에 따로 복사해 둔다.

## 4. 테스트 APK 만들기

```bat
build_apk.bat
```

- 처음에는 npm 패키지와 Gradle을 내려받느라 5~10분 걸린다.
- 결과 파일: `out\SumPath_v1.0.0_debug.apk`

## 5. 기기에 설치

### 방법 A — USB (권장)
1. 기기에서 **설정 → 휴대전화 정보 → 소프트웨어 정보 → 빌드번호**를 7번 눌러 개발자 옵션을 켠다.
2. **설정 → 개발자 옵션 → USB 디버깅**을 켠다.
3. USB로 PC에 연결하고, 기기에 뜨는 "USB 디버깅 허용"을 누른다.
4. 다음을 실행한다.
   ```bat
   build_apk.bat install
   ```

### 방법 B — 파일 복사
`out\SumPath_v1.0.0_debug.apk`를 카카오톡·메일·USB 등으로 기기에 옮겨 연다.
"출처를 알 수 없는 앱 설치 허용"을 묻는 창이 뜨면 허용한다.

## 6. PC 브라우저에서 바로 보기 (개발할 때)

APK를 만들지 않고 화면을 확인할 수 있다.

```bat
npm install
npm run dev
```

- 같은 와이파이에 있는 휴대폰 브라우저에서 화면에 표시된 `http://192.168.x.x:5173` 주소로 열 수 있다.
- 크롬 개발자 도구(F12) → 기기 모드(Ctrl+Shift+M)에서 터치를 흉내 낼 수 있다.

## 7. 기기에서 디버깅

debug APK는 크롬 원격 디버깅이 켜져 있다. USB로 연결한 뒤 PC 크롬에서 `chrome://inspect`를 열면
앱 화면(WebView)의 콘솔과 오류를 볼 수 있다.

## 문제 해결

| 증상 | 조치 |
|---|---|
| `JDK 를 찾을 수 없습니다` | Android Studio를 설치했는지 확인한다. 다른 경로라면 `JAVA_HOME`을 설정한다 |
| `SDK location not found` | Android Studio를 한 번 실행해 Setup Wizard를 끝낸다 |
| Gradle 다운로드 중 멈춤 | 회사 방화벽 문제일 수 있다. 집이나 다른 네트워크에서 처음 한 번 빌드하면 캐시가 생긴다 |
| `adb` 에서 기기가 안 보임 | USB 케이블(데이터용)을 확인하고, 기기의 USB 모드를 "파일 전송"으로 바꾼다 |
| 설치 시 "패키지가 손상" | 이전에 다른 서명으로 설치한 Sum Path를 지운 뒤 다시 설치한다 |
