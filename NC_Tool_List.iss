; NC 공구 리스트 생성기 - Inno Setup 설치 스크립트
; Program Files\NC Tool List 폴더에 설치됩니다.

#define MyAppName "NC Tool List"
#define MyAppVersion "1.3.1"
#define MyAppPublisher "S M.HWANG"
#define MyAppExeName "NC_Tool_List.exe"

[Setup]
AppId={{7E9C1F42-3A8B-4D56-9E10-2C4F6A8B0D31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Program Files 아래에 폴더 생성해서 설치
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=NC_Tool_List_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Program Files 쓰기에 관리자 권한 필요 (UAC 프롬프트)
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "지금 {#MyAppName} 실행"; Flags: nowait postinstall skipifsilent
