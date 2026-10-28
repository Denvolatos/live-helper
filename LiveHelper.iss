; Inno Setup 脚本：把 dist\LiveHelper 文件夹打成安装包 LiveHelper-Setup.exe
; 编译方法（需先安装 Inno Setup 6）：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" LiveHelper.iss
; 先运行 build.bat 生成 dist\LiveHelper，再编译本脚本，输出在 Output\ 目录。

#define AppName "LatoMedia"
; 版本号：编译时用 ISCC /DAppVer=x.y.z 传入（build.bat 之后由 release.bat 自动传）
#ifndef AppVer
#define AppVer "1.1.0"
#endif

[Setup]
AppId={{8C0E5B1A-6B1F-4F3E-9D52-3A7C1E9F0B21}
AppName={#AppName}
VersionInfoVersion={#AppVer}
AppVersion={#AppVer}
DefaultDirName={autopf}\LiveHelper
DefaultGroupName={#AppName}
UsePreviousGroup=no
OutputDir=Output
OutputBaseFilename=LiveHelper-Setup-v{#AppVer}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\LiveHelper.exe
SetupIconFile=icon.ico

; 官方 Inno Setup 不带简体中文语言包，向导界面用默认英文；快捷方式和任务说明仍是中文

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "dist\LiveHelper\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; 改名后清掉旧名字的快捷方式，避免升级后留下两份
Type: filesandordirs; Name: "{userprograms}\直播助手"
Type: files; Name: "{userdesktop}\直播助手.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\LiveHelper.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\LiveHelper.exe"; Tasks: desktopicon

[Registry]
; 程序里“开机自启”开关写的启动项：卸载时一并清掉（没开过就什么都不做）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "LiveHelper"; ValueType: none; Flags: uninsdeletevalue

[Run]
Filename: "{app}\LiveHelper.exe"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent
