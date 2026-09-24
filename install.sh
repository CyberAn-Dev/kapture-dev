#!/usr/bin/env bash
# Kapture 一键安装脚本(Kubuntu / Ubuntu, X11 会话)
# 用法:bash install.sh
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "==> 安装目录: $DIR"

# 1) 系统依赖:Tesseract OCR 引擎 + 中文语言包 + 录屏(需要 sudo)
echo "==> 安装系统依赖(需要输入密码)..."
sudo apt update
sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
                    python3-venv python3-pyqt5 python3-opencv python3-numpy \
                    python3-pil python3-pynput python3-packaging \
                    fonts-noto-cjk ffmpeg

# 2) 复用 apt 安装的 Python 库，仅下载 apt 未提供的两个包
echo "==> 创建可复用系统库的虚拟环境并安装剩余依赖..."
python3 -m venv --system-site-packages "$DIR/.venv"
PYTHONNOUSERSITE=1 "$DIR/.venv/bin/python" -m pip install --no-deps mss pytesseract
PYTHONNOUSERSITE=1 "$DIR/.venv/bin/python" -c \
    'import cv2, numpy, PIL, PyQt5, mss, pynput, pytesseract'

# 3) 启动器可执行权限
chmod +x "$DIR/run.sh" "$DIR/kapture.py"

# 4) 注册到应用菜单(名称/图标由程序按界面语言自动维护)
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/kapture.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Kapture
GenericName=Screenshot / OCR / Recording
Comment=Scrolling screenshot, OCR, annotation and recording
Exec=$DIR/run.sh
Icon=$DIR/kapture.png
Terminal=false
StartupWMClass=kapture
Categories=Graphics;Utility;
Keywords=screenshot;ocr;scroll;capture;录屏;截图;
EOF
update-desktop-database "$APP_DIR" 2>/dev/null || true

echo ""
echo "✅ 安装完成!在应用菜单搜 'Kapture' 打开,或运行: $DIR/run.sh"
