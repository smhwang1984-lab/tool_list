; NC 공구 리스트 생성기 - Inno Setup 설치 스크립트
; C:\NC_Tool_List 폴더에 설치됩니다.

#define MyAppName "NC Tool List"
#define MyAppVersion "1.5.1"
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

[Files]
Source: "dist\NC_Tool_List\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
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

