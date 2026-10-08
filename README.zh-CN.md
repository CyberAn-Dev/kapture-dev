<div align="center">

<img src="kapture.png" alt="Kapture Dev" width="88" />

# Kapture Dev

**Linux 上的 PixPin 平替**

截图 · 长截图 · OCR 取词 · 钉图 · 标注 · 录屏

面向 Linux X11，把截图、提取文字和贴图参考放进同一个工作流。

[English](README.md) · [快速开始](#快速开始) · [功能](#功能) · [反馈问题](https://github.com/CyberAn-Dev/kapture-dev/issues)

![Platform](https://img.shields.io/badge/Linux-X11-3776ab)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

<div align="center">

<img src="docs/images/editor.png" alt="Kapture Dev 编辑器" width="900" />

<sub>当前编辑器：演示内容、图片标注与 OCR 结果。</sub>

</div>

## 熟悉的截图工作流

- **截下来，标清楚**：框选或吸附窗口，添加箭头、序号和马赛克，复制分享。
- **图片里的字，直接拿走**：截图自动 OCR，也可局部取词或框选屏幕直接复制文字。
- **参考图，贴在手边**：钉住剪贴板图片，缩放、调透明度，一边看一边工作。
- **一屏不够，继续滚动**：自动或手动采集长图，上下往返不重复追加已采集内容。

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

## 快速开始

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

<details>
<summary>界面与设置</summary>

<div align="center">

<img src="docs/images/settings.png" alt="Kapture Dev 设置" width="660" />

<sub>配置快捷键、截图行为、OCR 与界面外观。</sub>

</div>

GNOME 启动时恢复已保存的快捷键，有冲突可在设置中修改。“后台启动”仅隐藏窗口，不等于登录自启。

</details>

## 常用操作

| 操作 | 按键 / 手势 |
| --- | --- |
| 钉住最近 / 上一张剪贴板图片 | Ctrl+1 / Ctrl+2（GNOME 默认，可修改） |
| 缩放 / 调整钉图透明度 | 滚轮 / Ctrl+滚轮 |
| 识别钉图文字 | O 或右键菜单 |
| 停止长截图 / 关闭当前钉图 | Esc |

钉图右键支持鼠标穿透；从托盘可恢复交互。剪贴板图片历史仅保留当前运行期间的最近 10 张。

## 命令行

使用 `./run.sh <选项>` 执行一个操作，例如 `./run.sh --region`。

- 截图：`--region`、`--window`、`--scroll`、`--manual`、`--repeat`
- 其他：`--pin1`、`--pin2`、`--color`、`--record`、`--settings`、`--show`、`--background`

## 与 PixPin 的区别

Kapture Dev 是基于 [Kapture](https://github.com/ycwei5/kapture) 的独立开源项目，与 [PixPin](https://pixpin.cn/) 无隶属关系。“平替”指截图、长截图、OCR 与钉图等常用工作流，不代表功能完全一致。目前不提供 OCR 翻译、二维码识别或录屏音频。

- 仅支持 X11，暂不支持 Wayland。GNOME 和 KDE Plasma 5 支持在应用内设置全局快捷键。
- 长截图高度上限为 40,000 像素。动态页面、悬浮层、懒加载和重复内容会影响拼接；本功能不是浏览器整页导出。
- OCR 效果受文字大小、字体和图像质量影响。需安装 Tesseract 及中英文语言包。

## 贡献与许可证

问题和改进建议请提交到 [Issues](https://github.com/CyberAn-Dev/kapture-dev/issues)，代码贡献请使用 [Pull Requests](https://github.com/CyberAn-Dev/kapture-dev/pulls)。

本项目基于 [ycwei5/kapture](https://github.com/ycwei5/kapture)；MIT 许可证及上游版权信息见 [LICENSE](LICENSE)。主题配色参考 [One Dark Pro](https://github.com/Binaryify/OneDark-Pro) 与 [Vitesse](https://github.com/antfu/vscode-theme-vitesse)。
