; NC 공구 리스트 생성기 - Inno Setup 설치 스크립트
; C:\NC_Tool_List 폴더에 설치됩니다.

#define MyAppName "NC Tool List"
#define MyAppVersion "2.0.2"
#define MyAppPublisher "S M.HWANG"
#define MyAppExeName "NC_Tool_List.exe"

[Setup]
AppId={{7E9C1F42-3A8B-4D56-9E10-2C4F6A8B0D31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; TSERP와 유사하게 C 드라이브의 전용 폴더에 설치
DefaultDirName=C:\NC_Tool_List
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=no
OutputDir=installer
OutputBaseFilename=NC_Tool_List_Setup_v{#MyAppVersion}
SetupIconFile=assets\nc_tool_list.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 설치 파일에 정상적인 버전/제작사 정보를 명시해 보안 프로그램의 오탐 가능성을 줄임
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
; C 드라이브 루트 아래 전용 폴더 생성을 위해 관리자 권한 요청
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
; .nc/.mpf/.tap을 이 앱의 기본 프로그램으로 등록(요청 사항 2)
ChangesAssociations=yes
CloseApplications=force
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Dirs]
; v1.8.0: 라이선스 파일(license.lic)을 PC 전체 공용으로 저장하는 폴더.
; 관리자 권한 없는 Windows 계정에서도 라이선스를 등록/교체할 수 있도록
; users-modify 권한을 준다. 제거 시 지우지 않는다(재설치/업데이트해도
; 라이선스가 유지되도록 [UninstallDelete]에 넣지 않음).
Name: "{commonappdata}\NC Tool List"; Permissions: users-modify

[Files]
Source: "dist\NC_Tool_List\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; v1.8.3: 이 앱이 쓸 그래픽 어댑터를 "고성능"으로 못박는다.
;
; 현장 PC 한 대가 설치 후 창만 깜박이고 즉시 종료됐는데(ntdll / 0xC0000409),
; Windows 설정 → 시스템 → 디스플레이 → 그래픽에서 어댑터를 직접 지정하니
; 정상 실행됐다. 기본 어댑터의 OpenGL 드라이버가 3D Viewer의 GL 컨텍스트
; 생성 중 프로세스를 죽인 것이다. 아래 키가 바로 그 화면이 값을 저장하는
; 곳이므로, 설치 시점에 같은 설정을 미리 넣어 둔다.
;   GpuPreference=1 절전(내장), =2 고성능(외장)
; GPU가 하나뿐인 PC에서는 Windows가 이 값을 무시하므로 부작용이 없다.
; 이 설정으로도 해결되지 않으면 앱 자체의 그래픽 안전 모드가 받아 낸다
; (NC_Tool_List.py의 viewer_safe_mode_* 참고).
Root: HKCU; Subkey: "Software\Microsoft\DirectX\UserGpuPreferences"; ValueType: string; ValueName: "{app}\{#MyAppExeName}"; ValueData: "GpuPreference=2;"; Flags: uninsdeletevalue

; .nc/.mpf/.tap 확장자를 이 앱의 기본 프로그램으로 등록 (요청 사항 2). 제거 시 함께 삭제됨.
Root: HKCR; Subkey: "NCToolList.NCProgram"; ValueType: string; ValueName: ""; ValueData: "NC 프로그램"; Flags: uninsdeletekey
Root: HKCR; Subkey: "NCToolList.NCProgram\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "NCToolList.NCProgram\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCR; Subkey: ".nc"; ValueType: string; ValueName: ""; ValueData: "NCToolList.NCProgram"; Flags: uninsdeletevalue
Root: HKCR; Subkey: ".nc\OpenWithProgids"; ValueType: string; ValueName: "NCToolList.NCProgram"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCR; Subkey: ".mpf"; ValueType: string; ValueName: ""; ValueData: "NCToolList.NCProgram"; Flags: uninsdeletevalue
Root: HKCR; Subkey: ".mpf\OpenWithProgids"; ValueType: string; ValueName: "NCToolList.NCProgram"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCR; Subkey: ".tap"; ValueType: string; ValueName: ""; ValueData: "NCToolList.NCProgram"; Flags: uninsdeletevalue
Root: HKCR; Subkey: ".tap\OpenWithProgids"; ValueType: string; ValueName: "NCToolList.NCProgram"; ValueData: ""; Flags: uninsdeletevalue

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "지금 {#MyAppName} 실행"; Flags: nowait postinstall skipifsilent

