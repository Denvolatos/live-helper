# 由 build.bat 调用：根据 version.py 生成 PyInstaller 的 version_info.txt（exe 属性->详细信息）
from version import __version__, __app_name__
v = tuple(int(x) for x in __version__.split(".")) + (0,)
txt = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable("080404B0", [
      StringStruct("CompanyName", ""),
      StringStruct("FileDescription", "{__app_name__} - 直播搜索与 PotPlayer 播放"),
      StringStruct("FileVersion", "{__version__}"),
      StringStruct("InternalName", "LiveHelper"),
      StringStruct("OriginalFilename", "LiveHelper.exe"),
      StringStruct("ProductName", "{__app_name__}"),
      StringStruct("ProductVersion", "{__version__}")])]),
    VarFileInfo([VarStruct("Translation", [2052, 1200])])
  ])
"""
open("version_info.txt", "w", encoding="utf-8").write(txt)
print("version_info.txt ok", __version__)
