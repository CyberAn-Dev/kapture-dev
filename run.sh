#!/usr/bin/env bash
# Kapture 启动器:用项目自带的 venv 运行
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONNOUSERSITE=1
exec "$DIR/.venv/bin/python" "$DIR/kapture.py" "$@"
