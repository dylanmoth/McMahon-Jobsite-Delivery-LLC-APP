#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif

#define AppName "McMahon Dispatch"
#define AppPublisher "McMahon Jobsite Delivery LLC"
#define AppExeName "McMahon Dispatch.exe"
#define AppId "{{8B0D5228-C71D-4E92-98D8-5B7EBBF33E81}"
#define BuildSource SourceRoot + "\dist\McMahon Dispatch"
#define AppIcon SourceRoot + "\src\mcmahon_dispatch\assets\icons\mcmahon_dispatch.ico"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/dylanmoth/McMahon-Jobsite-Delivery-LLC-APP
AppSupportURL=https://github.com/dylanmoth/McMahon-Jobsite-Delivery-LLC-APP/issues
AppUpdatesURL=https://github.com/dylanmoth/McMahon-Jobsite-Delivery-LLC-APP/releases
DefaultDirName={localappdata}\Programs\McMahon Dispatch
DefaultGroupName=McMahon Dispatch
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SourceRoot}\release
OutputBaseFilename=McMahonDispatch-Setup-{#AppVersion}
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes
ChangesAssociations=no
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
MinVersion=10.0.17763
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
CreateUninstallRegKey=yes
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "startupicon"; Description: "Start McMahon Dispatch when I sign in"; GroupDescription: "Optional startup:"; Flags: unchecked

[Files]
Source: "{#BuildSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\McMahon Dispatch"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\McMahon Dispatch"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\McMahon Dispatch"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Tasks: startupicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\McMahon Dispatch.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\McMahon Dispatch.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch McMahon Dispatch"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
