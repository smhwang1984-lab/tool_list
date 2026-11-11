; NC Viewer 설치 스크립트 (Inno Setup)
; ISCC.exe installer.iss 로 컴파일하면 Output\NC_Viewer_Setup.exe 가 생성됩니다.

#define MyAppName "NC Viewer"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Master"
#define MyAppExeName "NC_Viewer.exe"

[Setup]
; AppId 는 프로그램을 고유하게 식별합니다(제거/업그레이드용). 변경하지 마세요.
AppId={{8F3A7C21-4D6B-4E9A-9C12-A1B2C3D4E5F6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 기본 설치는 관리자 권한(모든 사용자). 관리자 권한이 없으면 현재 사용자로 설치.
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=NC_Viewer_Setup
SetupIconFile=nc_viewer.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; PyInstaller onedir 결과물 전체를 포함
Source: "dist\NC_Viewer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
