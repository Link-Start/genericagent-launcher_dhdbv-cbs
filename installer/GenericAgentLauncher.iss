#define MyAppName "GenericAgent Launcher"
#define MyAppPublisher "GenericAgent Launcher"
#ifndef MyVersion
  #define MyVersion "0.0.0-local"
#endif

[Setup]
AppId={{B7F9E2A6-0E0C-4A57-AF0D-1A188A26891A}
AppName={#MyAppName}
AppVersion={#MyVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\GenericAgentLauncher
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
OutputDir=..\release\{#MyVersion}\installer
OutputBaseFilename=GenericAgentLauncher-Setup-{#MyVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\LauncherBootstrap.exe
ChangesAssociations=no
DisableWelcomePage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\release\{#MyVersion}\install\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\GenericAgent Launcher"; Filename: "{app}\LauncherBootstrap.exe"
Name: "{autodesktop}\GenericAgent Launcher"; Filename: "{app}\LauncherBootstrap.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Run]
Filename: "{app}\LauncherBootstrap.exe"; Description: "启动 GenericAgent Launcher"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"

[Code]
function LauncherStateJson(): String;
begin
  Result :=
    '{' + #13#10 +
    '  "current_version": "{#MyVersion}",' + #13#10 +
    '  "previous_version": "",' + #13#10 +
    '  "pending_update": {},' + #13#10 +
    '  "updated_at": 0' + #13#10 +
    '}';
end;

procedure InitializeLauncherState();
var
  StateDir: String;
  StatePath: String;
begin
  StateDir := ExpandConstant('{localappdata}\GenericAgentLauncher\state');
  if not DirExists(StateDir) then
    ForceDirectories(StateDir);
  StatePath := AddBackslash(StateDir) + 'current.json';
  if not SaveStringToFile(StatePath, LauncherStateJson(), False) then
    Log('Failed to initialize launcher state: ' + StatePath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InitializeLauncherState();
end;
