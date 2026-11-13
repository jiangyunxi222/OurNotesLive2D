# BandoriLove 独立角色预览

在 Windows 上用同一份控制台预览 GarupaLive2D 和 OurNotesLive2D 的角色 ZIP。打开页面后选择一个角色包，点击「更换角色包」可以切换到另一个角色。浏览器使用随程序附带的渲染组件，无需安装 Live2DViewerEX。

## 从源码运行

```powershell
python server.py
```

## 构建 Windows 版

使用 Python 3.10 或更高版本和 PyInstaller，在此目录执行。

```powershell
python -m PyInstaller --onefile --windowed --name ControlPanel --icon ControlPanel.ico server.py
Copy-Item -Recurse web dist
Copy-Item standalone.mode, 使用说明.txt, THIRD_PARTY_NOTICES.txt dist
```

完整保留 `dist` 目录并双击 `ControlPanel.exe`。`standalone.mode` 启用独立预览模式。角色 ZIP 格式见 [使用说明](使用说明.txt)。
