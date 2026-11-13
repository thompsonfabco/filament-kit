; Inno Setup 6 script: per-user installer for the filament-kit PC sync (no admin rights needed).
; Build (from the repo root, after `pyinstaller --noconfirm pc-sync/fksync.spec`):
;   ISCC /DAppVersion=0.2.0 pc-sync\installer\filament-kit-sync.iss
; Output: dist\filament-kit-sync-setup-<AppVersion>.exe
; Relative paths below are relative to this file's folder.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=<x.y.z> filament-kit-sync.iss
#endif
#ifndef DistDir
  #define DistDir "..\..\dist\filament-kit-sync"
#endif
#ifndef OutDir
  #define OutDir "..\..\dist"
#endif

#define AppName "filament-kit sync"
#define ExeName "filament-kit-sync.exe"
#define TaskExeName "filament-kit-sync-task.exe"

[Setup]
; Fixed AppId: every version upgrades the same install. Never change it.
AppId={{B7461DED-A0F4-46B3-B2C9-C8F0EF762ABB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=filament-kit
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\filament-kit-sync
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=filament-kit-sync-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#ExeName}
; The task exe may be mid-run during an upgrade: close it rather than fail on a locked file.
CloseApplications=yes
RestartApplications=no
; {app} is added to the per-user PATH (so `filament-kit-sync status` works in a new terminal):
; tell Explorer to reload the environment after install and uninstall.
ChangesEnvironment=yes

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install_task.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall_task.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\THIRD-PARTY.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Files of an older build that this build no longer has.
Type: filesandordirs; Name: "{app}\_internal"

[Registry]
; Per-user PATH: append {app} once (NeedsAddPath); the uninstaller removes just that entry (RemovePath in [Code]).
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}')); Flags: preservestringtype

[Icons]
; cmd /k keeps the window open so the result of pair/status stays readable.
Name: "{group}\Pair filament-kit sync"; Filename: "{cmd}"; Parameters: "/k """"{app}\{#ExeName}"" pair"""; WorkingDir: "{app}"
Name: "{group}\filament-kit sync status"; Filename: "{cmd}"; Parameters: "/k """"{app}\{#ExeName}"" status"""; WorkingDir: "{app}"
Name: "{group}\Uninstall filament-kit sync"; Filename: "{uninstallexe}"

[Run]
; 1) The scheduled task is registered in [Code] (CurStepChanged), where its exit code is checked.
; 2) Pair this PC with the server, in a console (paste the link from 'sudo filament-kit pair --pc').
Filename: "{cmd}"; Parameters: "/k """"{app}\{#ExeName}"" pair"""; WorkingDir: "{app}"; Description: "Pair this PC with the filament-kit server now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\uninstall_task.ps1"""; RunOnceId: "RemoveScheduledTask"; Flags: runhidden waituntilterminated

[Code]
// True when Dir is not yet an entry of the per-user PATH (case-insensitive, whole entries only).
function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

// Removes the entry Dir from the per-user PATH, leaving every other entry as it was.
procedure RemovePath(Dir: string);
var
  Paths, Needle: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    exit;
  Paths := ';' + Paths + ';';
  Needle := ';' + Uppercase(Dir) + ';';
  P := Pos(Needle, Uppercase(Paths));
  if P = 0 then
    exit;
  Delete(Paths, P, Length(Needle) - 1);  // drop ";<Dir>", keep the following ";"
  Paths := Copy(Paths, 2, Length(Paths) - 2);  // drop the ";" added at each end above
  if (Paths = '') or (Paths = ';') then
    RegDeleteValue(HKEY_CURRENT_USER, 'Environment', 'Path')
  else
    RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths);
end;

// Registers the scheduled task (every 10 minutes and at logon, as the current user). A failure is shown, with the
// way to finish by hand; the install itself stays (the files are there, and the task can be registered later).
procedure RegisterTask;
var
  ResultCode: Integer;
  Script, Exe: string;
begin
  WizardForm.StatusLabel.Caption := 'Registering the scheduled task...';
  Script := ExpandConstant('{app}\install_task.ps1');
  Exe := ExpandConstant('{app}\{#TaskExeName}');
  ResultCode := -1;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '" -ExePath "' + Exe + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    Log('install_task.ps1 failed, exit code ' + IntToStr(ResultCode));
    SuppressibleMsgBox('The scheduled task that runs the sync every 10 minutes could not be registered (exit code ' +
      IntToStr(ResultCode) + '). The sync will not run by itself until it is.' + #13#10 + #13#10 +
      'To finish, run this in PowerShell:' + #13#10 + 'powershell -ExecutionPolicy Bypass -File "' + Script +
      '" -ExePath "' + Exe + '"' + #13#10 + 'or run this installer again.', mbError, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RegisterTask;
end;

// Asks whether to delete the sync's data (pairing token, settings, log, preset backups) in
// %LOCALAPPDATA%\filament-kit-sync, as `uninstall.sh --purge` does on Linux. The default is to keep it (a reinstall
// pairs again without a new link); a silent uninstall keeps it. Either way the unpair hint is shown.
procedure AskDeleteData;
var
  Data: string;
  Wipe: Boolean;
begin
  Data := ExpandConstant('{localappdata}\filament-kit-sync');
  if not DirExists(Data) then
    exit;
  Wipe := SuppressibleMsgBox('Also delete the sync''s data (pairing token, settings, log and the Bambu Studio and ' +
    'Orca Slicer preset backups) in' + #13#10 + Data + ' ?' + #13#10 + #13#10 +
    'Choose No to keep it; installing again then needs no new pairing.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2,
    IDNO) = IDYES;
  if Wipe then
    DelTree(Data, True, True, True);
  SuppressibleMsgBox('This PC is still paired on the server. To free its place for another PC, run on the server:' +
    #13#10 + 'sudo filament-kit unpair <id>' + #13#10 + '(the id is the "Device id" line of "filament-kit-sync status", run before uninstalling).', mbInformation, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemovePath(ExpandConstant('{app}'))
  else if CurUninstallStep = usPostUninstall then
    AskDeleteData;
end;
