# NC Tool List 작업 기록

작성일: 2026-09-03  
작성자 표기: Hwang.seonmun  
현재 버전: 1.4.2

## 요청 내용

- 기존 기능은 손대지 않고 About 버튼 추가.
- About 팝업에 버전, 용도, 제작 년월일, 제작자, 사용 오픈소스 표기.
- 설치 파일 제작.
- 새 버전 제작 시 변경 이력과 사용 오픈소스 기록 지침 남기기.
- 보안 프로그램이 설치된 일반 PC에서 설치 또는 실행이 차단되는 문제 대응.
- TSERP처럼 C 드라이브 직접 설치 방식 검토 및 적용.
- 현재 추가 이슈: Windows에서 `게시자 없음`으로 표시됨.

## 완료한 변경

### 1. About 버튼 및 팝업 추가

`NC_Tool_List.py`에 아래 정보를 추가했다.

- `APP_VERSION = '1.4.2'`
- `APP_BUILD_DATE = '2026-09-03'`
- `APP_CREATOR = 'Hwang.seonmun'`
- `APP_PURPOSE = 'NC 프로그램에서 공구 리스트를 산출하고 NC 경로를 Viewer로 확인하는 도구'`
- 사용 오픈소스:
  - Python
  - PyQt5
  - pyqtgraph
  - NumPy
  - PyOpenGL
  - ReportLab
  - PyInstaller
  - Inno Setup

프로그램 상단에 `About` 버튼을 추가했고, 클릭 시 가벼운 팝업 뷰어로 위 정보를 표시한다.

### 2. 버전 및 오픈소스 기록 지침 추가

`ABOUT_RELEASE_INSTRUCTIONS.md` 파일을 새로 추가했다.

기록 목적:

- 새 버전 제작 시 버전, 제작일, 제작자, 변경 내용 기록.
- About 팝업의 버전 정보와 설치 파일 버전을 함께 갱신.
- 사용 오픈소스 목록이 바뀌면 About 팝업과 문서 모두 갱신.
- 설치 파일과 휴대용 ZIP을 만들 경우 SHA256 해시 기록.

### 3. 설치 방식 변경

`NC_Tool_List.iss` 설치 스크립트를 수정했다.

현재 설치 방식:

- 설치 경로: `C:\NC_Tool_List`
- 설치 권한: 관리자 권한
- 파일 구성: PyInstaller `onedir` 폴더 전체 설치
- 기존 `Program Files` 설치 방식 제거
- 직접 `taskkill.exe` 실행 코드 제거
- HKLM 파일 연결 레지스트리 등록 제거
- `ChangesAssociations=no`
- `CloseApplications=force`
- `RestartApplications=no`

목적:

- 보안 프로그램이 `onefile` 자동 압축 해제 방식이나 강제 종료 BAT/명령을 의심하는 가능성을 줄임.
- TSERP와 비슷하게 C 드라이브의 전용 폴더에 설치.

### 4. PyInstaller 패키징 변경

`NC_Tool_List.spec`를 수정했다.

현재 방식:

- `onefile` 대신 `onedir` 배포.
- `upx=False`로 실행 파일 압축 비활성화.
- `exclude_binaries=True`와 `COLLECT(...)` 사용.
- 불필요하거나 보안 프로그램 오탐 가능성이 있는 일부 모듈 제외:
  - `scipy`
  - `torch`
  - `matplotlib`
  - `IPython`
  - `jupyter_rfb`
  - `PySide6`
  - `PyQt6`
  - `PySide2`
  - 일부 `OpenGL.GLUT`, `GLX`, `GLES` 계열 모듈

추가로 `freeglut`, `gle32`, `gle64` 계열 OpenGL DLL을 최종 바이너리 목록에서 제외하도록 조정했다.

### 5. 실행 중 죽는 문제 대응

`NC_Tool_List.py`에 시작 로그와 Viewer fallback 처리를 추가했다.

추가된 동작:

- 실행 시작 시 `%LOCALAPPDATA%\NC_Tool_List\startup.log`에 로그 기록.
- 예외 발생 시 traceback을 startup.log에 기록.
- `QT_OPENGL=software` 기본 설정.
- `QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)` 적용.
- 3D Viewer import 또는 생성 실패 시 프로그램 전체가 죽지 않도록 fallback 화면 표시.
- fallback 상태에서도 공구 리스트 생성, 복사, PDF 출력은 계속 사용 가능하게 유지.

목적:

- 보안 PC 또는 OpenGL 미지원 PC에서 Viewer 때문에 전체 프로그램이 종료되는 문제를 줄임.
- 그래도 종료될 경우 원인을 startup.log로 확인할 수 있게 함.

## 검증 상태

### 단위 테스트

실행 명령:

```powershell
py -m unittest tests.test_nc_tool_list
```

결과:

- 총 22개 테스트 통과.
- Qt/OpenGL 관련 경고는 출력되지만 테스트 실패는 없음.

### PyInstaller 빌드

실행 명령:

```powershell
py -m PyInstaller --noconfirm --clean NC_Tool_List.spec
```

결과:

- 빌드 성공.
- 산출물 위치: `dist\NC_Tool_List\NC_Tool_List.exe`
- 현재 구조는 `dist\NC_Tool_List` 폴더와 `_internal` 폴더를 함께 배포하는 방식.

확인한 내용:

- 최종 배포 폴더에는 `freeglut*.dll`, `gle*.dll` 자체는 남아 있지 않음.
- 단, `OpenGL\DLLS` 아래 라이선스/README 텍스트 파일은 남아 있었음.
- 이 텍스트 파일까지 제거하는 추가 조정은 진행 중이었으나 사용자 중단으로 아직 반영하지 않음.

### 게시자 상태

확인 명령:

```powershell
Get-AuthenticodeSignature dist\NC_Tool_List\NC_Tool_List.exe
```

결과:

- `Status = NotSigned`
- 즉, 실행 파일은 디지털 서명되지 않음.

중요:

- `NC_Tool_List.iss`의 `AppPublisher=S M.HWANG`은 설치 프로그램 메타데이터일 뿐이다.
- Windows UAC 또는 SmartScreen의 `게시자` 표시는 Authenticode 코드서명이 있어야 표시된다.
- 따라서 현재 `게시자 없음`은 코드 문제라기보다 서명 인증서가 없어서 발생하는 정상 상태다.

## 아직 남은 작업

1. `NC_Tool_List.spec`에서 `OpenGL\DLLS` 텍스트 파일까지 최종 배포 폴더에서 제외하도록 마무리.
2. PyInstaller 재빌드.
3. 빌드된 exe 실행 smoke test.
4. Inno Setup 설치 파일 재생성.
5. 휴대용 ZIP 재생성.
6. 설치 파일과 ZIP의 SHA256 해시를 `ABOUT_RELEASE_INSTRUCTIONS.md`에 기록.
7. 실제 보안 프로그램 설치 PC에서 테스트.

## 보안 PC 대응 판단

현재 조치로 줄인 위험 요소:

- onefile 자동 압축 해제 제거.
- UPX 압축 제거.
- 직접 BAT/taskkill 계열 동작 제거.
- HKLM 파일 연결 레지스트리 등록 제거.
- C 드라이브 전용 폴더 설치.
- Viewer 실패 시 전체 앱 종료 방지.

그래도 보안 프로그램이 설치 직후 제거하거나 실행 즉시 종료한다면 다음 가능성이 크다.

- 서명되지 않은 실행 파일 차단.
- PyInstaller bootloader 기반 실행 파일 오탐.
- OpenGL/PyQt 관련 DLL 또는 로딩 동작 오탐.
- 회사 보안 정책에서 미승인 프로그램 실행 차단.

근본 해결책:

- 회사 또는 개인 코드서명 인증서로 `NC_Tool_List.exe`와 설치 파일을 모두 Authenticode 서명.
- 가능하면 timestamp 포함 서명.
- AhnLab 등 보안 솔루션에 샘플 제출 또는 허용 목록 등록.

## 현재 결론

`게시자 없음`은 설치 스크립트의 게시자 이름 누락이 아니라 디지털 서명 부재 때문이다.  
서명 인증서 없이 일반 사용자 PC에서 `게시자 있음`으로 보이게 만드는 것은 불가능하다.

현재 코드는 보안 오탐 가능성을 줄이는 방향으로 수정 중이며, 최종 설치 파일 재생성은 아직 완료 전이다.
