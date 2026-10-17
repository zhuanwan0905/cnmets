# -*- coding: utf-8 -*-
"""
e听说 一键启动器（可打包为 Windows exe，Linux 下同样可用）
=============================================================
职责：
  1. 定位/创建项目虚拟环境 .venv（exe 运行时若本机无 Python 会提示安装）
  2. 安装 requirements-runtime.txt 依赖（已装则跳过）
  3. 引导 CosyVoice2-0.5B 模型：自动下载 / 选择已有模型文件夹（结果写入 config.local.json）
  4. 调用主程序 ets100_tts_submit.py 并透传命令行参数

打包方式（Windows，需本机有 Python 3.10+ 与 pyinstaller）：
  build_windows.bat  或
  py -3 -m PyInstaller -F -n ets100_launcher ets100_launcher.py --distpath dist --workpath build --specpath build
产出 dist/ets100_launcher.exe，双击或命令行运行。
"""
import sys
import os
import json
import subprocess
import shutil

os.environ.setdefault("PYTHONUTF8", "1")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.local.json")
VENV_DIR = os.path.join(BASE_DIR, ".venv")
REQ_FILE = os.path.join(BASE_DIR, "requirements-runtime.txt")
MAIN_SCRIPT = os.path.join(BASE_DIR, "ets100_tts_submit.py")
DEFAULT_MODEL_DIR = os.path.join(BASE_DIR, "models", "CosyVoice2-0.5B")


def print_banner():
    print("=" * 60)
    print(" e听说 朗读题自动化补交（TTS 合成 + 上传 + 提交）")
    print("=" * 60)


def find_system_python():
    """返回可用的系统 Python 解释器路径；找不到返回 None。"""
    if os.name == "nt":
        for cand in ("py", "python"):
            try:
                r = subprocess.run([cand, "-3", "--version"] if cand == "py"
                                   else [cand, "--version"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return cand
            except (OSError, subprocess.SubprocessError):
                continue
    else:
        for cand in ("python3", "python"):
            try:
                r = subprocess.run([cand, "--version"], capture_output=True,
                                   text=True, timeout=10)
                if r.returncode == 0:
                    return cand
            except (OSError, subprocess.SubprocessError):
                continue
    return None


def venv_python():
    """当前虚拟环境（若已激活则直接用当前解释器）。"""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return sys.executable
    if os.name == "nt":
        p = os.path.join(VENV_DIR, "Scripts", "python.exe")
    else:
        p = os.path.join(VENV_DIR, "bin", "python")
    return p if os.path.isfile(p) else None


def prepare_env():
    """确保 venv 与依赖就绪。返回 venv python 路径。"""
    py = venv_python()
    if py:
        return py

    sys_py = find_system_python()
    if not sys_py:
        raise SystemExit(
            "本机未检测到 Python。请先安装 Python 3.10+（勾选 Add to PATH）后重新运行。\n"
            "下载: https://www.python.org/downloads/")

    if not os.path.isdir(VENV_DIR):
        print("创建虚拟环境 .venv ...")
        r = subprocess.run([sys_py, "-m", "venv", VENV_DIR])
        if r.returncode != 0:
            raise SystemExit("创建虚拟环境失败。")
    py = venv_python()
    assert py, "venv 创建后解释器仍不可用"

    # 依赖检查：curl_cffi 与 torch 任一缺失则安装
    check = subprocess.run([py, "-c", "import curl_cffi, torch"],
                           capture_output=True, text=True)
    if check.returncode != 0:
        print("安装运行依赖（首次约数分钟，含 torch CPU 版）...")
        r = subprocess.run([py, "-m", "pip", "install", "-q", "-r", REQ_FILE])
        if r.returncode != 0:
            raise SystemExit("依赖安装失败，请查看上方日志。")
        print("依赖安装完成。")
    return py


def model_ok(model_dir):
    if not model_dir or not os.path.isdir(model_dir):
        return False
    pts = [f for f in os.listdir(model_dir) if f.endswith(".pt")]
    return len(pts) >= 2 or (os.path.isfile(os.path.join(model_dir, "llm.pt")) and
                             os.path.isfile(os.path.join(model_dir, "flow.pt")))


def ensure_model():
    """模型引导（自动下载 / 选择已有文件夹），结果写入 config.local.json。"""
    cfg = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except ValueError:
            cfg = {}
    if model_ok(cfg.get("tts", {}).get("model_dir", "")):
        return

    print("未检测到 CosyVoice2-0.5B TTS 模型（约 5~6GB，本地语音合成用，只需准备一次）。")
    try:
        choice = input("选择 [1] 自动下载到项目 models/  [2] 我已有模型，输入文件夹路径 > ").strip()
    except EOFError:
        choice = "1"
    model_dir = ""
    if choice == "2":
        while not model_dir:
            p = input("请输入模型文件夹完整路径 > ").strip()
            if model_ok(p):
                model_dir = p
            else:
                print("该目录未找到模型文件（应包含 llm.pt/flow.pt/hift.pt）。")
    else:
        print("将下载到:", DEFAULT_MODEL_DIR)
        os.makedirs(os.path.dirname(DEFAULT_MODEL_DIR), exist_ok=True)
        ok = False
        try:
            from modelscope import snapshot_download
            try:
                snapshot_download("iic/CosyVoice2-0.5B", local_dir=DEFAULT_MODEL_DIR)
            except TypeError:
                snapshot_download("iic/CosyVoice2-0.5B",
                                  cache_dir=os.path.dirname(DEFAULT_MODEL_DIR))
            ok = model_ok(DEFAULT_MODEL_DIR)
        except Exception:
            ok = False
        if not ok:
            print("ModelScope 下载失败，尝试 HuggingFace ...")
            try:
                from huggingface_hub import snapshot_download
                snapshot_download("FunAudioLLM/CosyVoice2-0.5B", local_dir=DEFAULT_MODEL_DIR)
                ok = model_ok(DEFAULT_MODEL_DIR)
            except Exception:
                ok = False
        if not ok:
            raise SystemExit("模型下载失败：请检查网络后重试，或选择已有模型文件夹。")
        model_dir = DEFAULT_MODEL_DIR

    cfg.setdefault("tts", {})["model_dir"] = model_dir
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("模型路径已写入 config.local.json ->", model_dir)


def main():
    print_banner()
    py = prepare_env()
    ensure_model()
    cmd = [py, MAIN_SCRIPT] + sys.argv[1:]
    print("启动主程序:", " ".join(cmd))
    try:
        r = subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n已取消。")
        return
    sys.exit(r.returncode if r is not None else 0)


if __name__ == "__main__":
    main()
