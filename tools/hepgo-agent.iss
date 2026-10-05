; HEPGO fabrika ajanı — Inno Setup şablonu (entegrasyon başına /D tanımlarıyla parametrelenir).
; build-agent-windows.ps1 tarafından çağrılır. Elle derleme örneği:
;   ISCC.exe /DInteg=mikro /DIntegName="Mikro ERP" /DStageDir="C:\...\hepgo-stage-mikro" /DOutDir="..\agent-dist\mikro" hepgo-agent.iss

#ifndef Integ
  #define Integ "mikro"
#endif
#ifndef IntegName
  #define IntegName "HEPGO Ajan"
#endif
#ifndef StageDir
  #define StageDir "stage\hepgo-" + Integ
#endif
#ifndef OutDir
  #define OutDir "..\agent-dist\" + Integ
#endif
#define SvcName "hepgo-" + Integ

[Setup]
AppName=HEPGO Fabrika Ajani - {#IntegName}
AppVersion=1.0
DefaultDirName={autopf}\HepgoAgent-{#Integ}
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=hepgo-{#Integ}-setup-windows
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "{#StageDir}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\code\*";   DestDir: "{app}\code";   Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\nssm.exe"; DestDir: "{app}";        Flags: ignoreversion

[Icons]
; Yerel ayar sayfasını açan kısayollar (servis ilk açılışta 127.0.0.1:8765'i dinler)
Name: "{group}\{#IntegName} Ayarlari"; Filename: "http://127.0.0.1:8765/"
Name: "{commondesktop}\HEPGO {#IntegName} Ayarlari"; Filename: "http://127.0.0.1:8765/"

[Run]
; Windows servisini NSSM ile kaydet + ortamı ayarla + başlat
Filename: "{app}\nssm.exe"; Parameters: "install {#SvcName} ""{app}\python\python.exe"" -m agent.service"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set {#SvcName} AppDirectory ""{app}\code"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set {#SvcName} DisplayName ""HEPGO Fabrika Ajani - {#IntegName}"""; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set {#SvcName} Start SERVICE_AUTO_START"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "set {#SvcName} AppEnvironmentExtra HEPGO_INTEG={#Integ} ""HEPGO_AGENT_CONFIG={app}\agent-config.env"" HEPGO_LOCALCONFIG_PORT=8765"; Flags: runhidden
Filename: "{app}\nssm.exe"; Parameters: "start {#SvcName}"; Flags: runhidden
; Kurulum sonrası ayar sayfasını aç (kullanıcı Domain + API anahtarını girsin)
Filename: "http://127.0.0.1:8765/"; Description: "Ayar sayfasini ac"; Flags: postinstall shellexec nowait

[UninstallRun]
Filename: "{app}\nssm.exe"; Parameters: "stop {#SvcName}";            Flags: runhidden; RunOnceId: "StopSvc"
Filename: "{app}\nssm.exe"; Parameters: "remove {#SvcName} confirm";  Flags: runhidden; RunOnceId: "RemoveSvc"

[UninstallDelete]
Type: files; Name: "{app}\agent-config.env"
