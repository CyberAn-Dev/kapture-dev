# Kapture Dev

**面向 Linux X11 的截图、滚动长截图、OCR、标注与钉图工具。**

本项目基于 [ycwei5/kapture](https://github.com/ycwei5/kapture)，新增双向滚动截图、OCR 取词、剪贴板图片钉图、窗口吸附、GNOME 快捷键恢复和更多主题。

[English](README.md)

<div align="center">

<img src="docs/images/editor.png" alt="Kapture Dev 编辑器" width="900" />

<sub>当前编辑器：演示内容、图片标注与 OCR 结果。</sub>

</div>

## 功能

| 功能 | 说明 |
| --- | --- |
| 截图 | 区域或窗口截图、窗口吸附、屏幕取色、重复上次区域。 |
| 滚动长截图 | 自动向上或向下，也可手动滚动；提供实时预览并避免重复拼接已采集内容。 |
| OCR | 中英文识别、截图后自动识别、编辑器局部取词、截屏取词。 |
| 钉图 | 将剪贴板图片置顶；可移动、缩放、调透明度或复制识别出的文字。 |
| 编辑导出 | 标注、裁剪、保存、复制，或添加背景与阴影后导出。 |
| 录屏 | 录制为 MP4 或 GIF，可调帧率。 |
| 桌面集成 | GNOME 和 KDE Plasma 5 快捷键、主题、系统托盘与后台启动。 |

界面支持简体中文和英文。OCR 使用 Tesseract，录屏使用 ffmpeg。

## 设置

<div align="center">

<img src="docs/images/settings.png" alt="Kapture Dev 设置" width="660" />

<sub>配置快捷键、截图行为、OCR 与界面外观。</sub>

</div>

GNOME 启动时恢复已保存的快捷键，有冲突可在设置中修改。“后台启动”仅隐藏窗口，不等于登录自启。

## 安装

请使用 **X11** 会话。安装脚本面向使用 `apt` 的 Ubuntu 或 Kubuntu，需要联网。

### 从源码安装

```bash
git clone https://github.com/CyberAn-Dev/kapture-dev.git
cd kapture-dev
bash install.sh
./run.sh
```

脚本会安装系统依赖并添加应用菜单入口。启动器依赖源码目录，请保留该目录。

### 可选：构建 `.deb`

```bash
bash build_deb.sh 1.1.0
sudo apt install ./dist/kapture_1.1.0_all.deb
```

`1.1.0` 是示例版本号，软件包从当前源码目录构建。安装后运行 `kapture`；卸载使用 `sudo apt remove kapture`。

[上游 Releases](https://github.com/ycwei5/kapture/releases) 提供上游版本，可能不包含本 fork 的改动。

## 命令行

使用 `./run.sh <选项>` 执行一个操作，例如 `./run.sh --region`。

- 截图：`--region`、`--window`、`--scroll`、`--manual`、`--repeat`
- 其他：`--pin1`、`--pin2`、`--color`、`--record`、`--settings`、`--show`、`--background`

## 使用限制

- 仅支持 X11，暂不支持 Wayland。GNOME 和 KDE Plasma 5 支持在应用内设置全局快捷键。
- 长截图高度上限为 40,000 像素。动态页面、悬浮层、懒加载和重复内容会影响拼接；本功能不是浏览器整页导出。
- OCR 效果受文字大小、字体和图像质量影响。需安装 Tesseract 及中英文语言包。

## 贡献与许可证

问题和改进建议请提交到 [Issues](https://github.com/CyberAn-Dev/kapture-dev/issues)，代码贡献请使用 [Pull Requests](https://github.com/CyberAn-Dev/kapture-dev/pulls)。

本项目基于 [ycwei5/kapture](https://github.com/ycwei5/kapture)；MIT 许可证及上游版权信息见 [LICENSE](LICENSE)。主题配色参考 [One Dark Pro](https://github.com/Binaryify/OneDark-Pro) 与 [Vitesse](https://github.com/antfu/vscode-theme-vitesse)。
