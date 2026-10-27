# 🛠️ 构建与打包

在 Windows 上，用 conda 环境 + PyInstaller 打成文件夹版，再用 Inno Setup 做安装包。

## 准备

1. 创建环境并安装依赖（不要用 base 环境）：
   ```bash
   conda create -n livetool python=3.12 -y
   conda activate livetool
   pip install customtkinter streamlink requests pillow websocket-client brotli psutil pyinstaller
   ```
2. 安装 Inno Setup 6（只在打包的电脑上需要）：
   ```bash
   winget install JRSoftware.InnoSetup
   ```
3. `build.bat` 里的 Python 路径默认是 `%USERPROFILE%\miniconda3\envs\livetool\python.exe`；环境在别处就先设置环境变量 `PY`。

## 版本号

只改 `version.py` 一处（`__version__`）。窗口标题、exe 属性（`make_version.py` 生成）、zip 与安装包文件名都引用它。

## 打包步骤

1. **先关掉正在运行的 `LiveHelper.exe`**：运行中的程序会占用 `dist\LiveHelper` 里的文件，PyInstaller 清不掉旧目录，会留下残缺的 `dist`。清不掉时先把旧 `dist` 改名挪开。
2. 在 PowerShell 里运行：
   ```powershell
   cmd /c ".\build.bat"
   ```
   产出 `dist\LiveHelper\` 和 `LiveHelper-vX.Y.Z-win64.zip`。
3. 编译安装包（版本号要和 `version.py` 一致）：
   ```powershell
   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVer=X.Y.Z LiveHelper.iss
   ```
   产出 `Output\LiveHelper-Setup-vX.Y.Z.exe`。

> `release.bat` 想一键完成上面两步，但从 PowerShell 里调用 `build.bat` 在中文路径下会失败；上面的手动两步经过实测。

## 打包后自检

去掉系统里的 streamlink（临时缩短 PATH），验证包里自带的能用：

```powershell
$env:PATH = "C:\Windows\System32;C:\Windows"
.\dist\LiveHelper\LiveHelper.exe --selftest "$env:TEMP\selftest.txt"
Get-Content "$env:TEMP\selftest.txt"
```

`--selftest` 会做三平台的搜索、房间查询、流解析，并各连十几秒统计弹幕条数。退出码 0 且文件里有数据才算通过。

## 一个内部约定

打包后的 exe 里 `--streamlink-cli` 是隐藏子命令：主界面用 subprocess 调用自己来跑 streamlink（等价于命令行 `streamlink -p PotPlayer ...`），所以用户不需要另外安装 streamlink。
