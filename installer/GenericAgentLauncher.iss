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
SetupIconFile=..\assets\launcher_app_icon.ico
UninstallDisplayIcon={app}\LauncherBootstrap.exe
ChangesAssociations=no
DisableWelcomePage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\release\{#MyVersion}\install\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\assets\launcher_app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\GenericAgent Launcher"; Filename: "{app}\LauncherBootstrap.exe"; WorkingDir: "{app}"; IconFilename: "{app}\launcher_app_icon.ico"; IconIndex: 0
Name: "{autodesktop}\GenericAgent Launcher"; Filename: "{app}\LauncherBootstrap.exe"; WorkingDir: "{app}"; IconFilename: "{app}\launcher_app_icon.ico"; IconIndex: 0; Check: WizardIsTaskSelected('desktopicon') or ExistingDesktopShortcutExists()

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Run]
Filename: "{app}\LauncherBootstrap.exe"; Description: "启动 GenericAgent Launcher"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"

[Code]
const
  SHCNE_ASSOCCHANGED = $08000000;
  SHCNF_IDLIST = $0000;

procedure SHChangeNotify(wEventId: Integer; uFlags: Integer; dwItem1: Integer; dwItem2: Integer);
  external 'SHChangeNotify@shell32.dll stdcall';

function ExistingDesktopShortcutExists(): Boolean;
begin
  Result := FileExists(ExpandConstant('{autodesktop}\GenericAgent Launcher.lnk'));
end;

procedure RefreshShellIcons();
var
  Ie4uinitPath: String;
  ResultCode: Integer;
begin
  SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0);
  Ie4uinitPath := ExpandConstant('{sys}\ie4uinit.exe');
  if FileExists(Ie4uinitPath) then
  begin
    if not Exec(Ie4uinitPath, '-ClearIconCache', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Log('Failed to clear Windows icon cache via ie4uinit.exe');
    if not Exec(Ie4uinitPath, '-show', '', SW_HIDE, ewNoWait, ResultCode) then
      Log('Failed to notify Windows shell to refresh icons via ie4uinit.exe');
  end
  else
    Log('ie4uinit.exe not found; skipping explicit icon cache refresh');
end;

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
  begin
    InitializeLauncherState();
    RefreshShellIcons();
  end;
end;
