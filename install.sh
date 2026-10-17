#!/usr/bin/env bash
# ============================================================
#  e听说 朗读题自动化补交 - Linux 一键安装/运行脚本
#  用法:  ./install.sh [可选参数，透传给主程序]
#  示例:  ./install.sh --text "Hello world"
#         ./install.sh --mp3 /path/to/audio.mp3
#  首次运行会: 检测 python3/ffmpeg -> 创建 .venv -> 安装依赖
#              -> 引导下载/选择 CosyVoice2-0.5B 模型
# ============================================================
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo " e听说 朗读题自动化补交 - Linux 一键安装"
echo "============================================================"

# 1. python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] 未找到 python3，请先安装: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# 2. ffmpeg（speex/mp3 转码需要）
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[*] 未找到 ffmpeg，尝试安装..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y ffmpeg
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y ffmpeg
    else
        echo "[!] 请手动安装 ffmpeg 后重试"
        exit 1
    fi
fi

# 3. 虚拟环境 + 依赖
if [ ! -d ".venv" ]; then
    echo "[*] 创建虚拟环境 .venv ..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[*] 检查/安装依赖（首次较慢，含 torch CPU 版）..."
python -c "import curl_cffi, torch" 2>/dev/null || \
    pip install -r requirements-runtime.txt

# 4. 模型引导 + 主程序（launcher 在 Linux 下同样工作：venv 已激活时直接使用当前解释器）
echo "[*] 启动..."
python ets100_launcher.py "$@"
