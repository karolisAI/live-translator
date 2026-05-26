#define MyAppName "LiveTranslator"
#define MyAppVersion "0.1.0"
#define MyAppExeName "LiveTranslator.exe"

[Setup]
AppId={{9C28BC42-8FC8-41E4-9D98-0B2D861B5F80}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=LiveTranslatorSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Files]
Source: "..\..\dist\LiveTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName} Setup"; Filename: "{app}\{#MyAppExeName}"; Parameters: "setup"; WorkingDir: "{app}"
Name: "{autoprograms}\{#MyAppName} Meeting"; Filename: "{app}\{#MyAppExeName}"; Parameters: "meeting"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "setup"; Description: "Configure LiveTranslator now"; Flags: postinstall skipifsilent nowait
