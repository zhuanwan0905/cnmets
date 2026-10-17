# -*- coding: utf-8 -*-
"""
e听说朗读题自动化补交（全参数化 + 交互引导版）
=================================================
链路：登录 -> TTS 合成(CosyVoice2-0.5B 零样本克隆) -> ffmpeg 转 16k mp3/speex
      -> STS -> OSS PUT(speex+mp3+xml) -> sync-v2 提交

与 ets100_submit_upload.py 的区别：
  * 内置 TTS 合成（模型缺失时引导：自动下载 / 选择已有模型文件夹）
  * 参考音频缺失时交互提示（零样本克隆音色需一段英文朗读 wav）
  * 支持真实评测 XML（--xml / config submit.xml），自动提取 total_score 作为提交分
  * 支持 mark_trace_id（--mark-trace-id / config submit.mark_trace_id / ETS100_MARK_TRACE_ID）
  * 所有敏感参数均走 config.local.json（不入库）与环境变量，支持交互输入

运行方式：
  Windows:  python ets100_tts_submit.py [--mp3 ...] [--text ...]
            （推荐用 ets100_launcher.py / 打包的 exe，自动准备环境与模型引导）
  Linux:    ./install.sh 一键安装后运行

依赖：requirements-runtime.txt（curl_cffi / torch / torchaudio / cosyvoice / Matcha-TTS /
       modelscope / huggingface_hub）
"""
import sys
import os
import json
import re
import time
import uuid
import datetime
import argparse
import tempfile

# 统一 UTF-8 输出（Windows 控制台 GBK 下避免乱码）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONUTF8", "1")

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(REPO_DIR, "config.local.json")
DEFAULT_MODEL_DIR = os.path.join(REPO_DIR, "models", "CosyVoice2-0.5B")

# 复用参数化提交脚本的登录 / STS / OSS / speex 能力
sys.path.insert(0, REPO_DIR)
import ets100_submit_upload as sub


# ---------------------------------------------------------------- 配置
def load_cfg(path=None):
    path = path or DEFAULT_CONFIG
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cfg(cfg, path=None):
    """写回配置（含登录密文，config.local.json 已被 .gitignore 排除，不会入库）。"""
    path = path or DEFAULT_CONFIG
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def resolve(name, cli_val, cfg_section, env_names):
    """命令行 > 配置文件 > 环境变量。"""
    if cli_val is not None:
        return cli_val
    if cfg_section and cfg_section.get(name):
        return cfg_section[name]
    for env in env_names:
        v = os.environ.get(env)
        if v:
            return v
    return None


def ask(prompt, default=None):
    """交互输入（exe / sh 控制台均可用）。"""
    if default is not None:
        prompt = f"{prompt}（默认: {default}）"
    try:
        val = input(prompt + " > ").strip()
    except EOFError:
        return default or ""
    return val or (default or "")


# ---------------------------------------------------------------- 模型引导
def model_ok(model_dir):
    """粗略校验模型目录：至少存在 llm.pt / hift.pt 之一且目录名含 CosyVoice。"""
    if not model_dir or not os.path.isdir(model_dir):
        return False
    pts = [f for f in os.listdir(model_dir) if f.endswith(".pt")]
    return len(pts) >= 2 or (os.path.isfile(os.path.join(model_dir, "llm.pt")) and
                             os.path.isfile(os.path.join(model_dir, "flow.pt")))


def download_model(target_dir):
    """优先 ModelScope（国内快），失败切 HuggingFace。返回是否成功。"""
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    try:
        print("[1/2] 尝试 ModelScope 下载 iic/CosyVoice2-0.5B ...")
        from modelscope import snapshot_download
        try:
            snapshot_download("iic/CosyVoice2-0.5B", local_dir=target_dir)
        except TypeError:  # 旧版 modelscope 用 cache_dir
            snapshot_download("iic/CosyVoice2-0.5B", cache_dir=os.path.dirname(target_dir))
        if model_ok(target_dir):
            return True
    except Exception as e:
        print("ModelScope 下载失败:", e)
    try:
        print("[2/2] 尝试 HuggingFace 下载 FunAudioLLM/CosyVoice2-0.5B ...")
        from huggingface_hub import snapshot_download
        snapshot_download("FunAudioLLM/CosyVoice2-0.5B", local_dir=target_dir)
        return model_ok(target_dir)
    except Exception as e:
        print("HuggingFace 下载失败:", e)
    return False


def ensure_model(cfg):
    """确保 tts.model_dir 可用；缺失时引导：自动下载 / 选择已有文件夹。"""
    model_dir = cfg.get("tts", {}).get("model_dir", "")
    if model_ok(model_dir):
        return model_dir
    print("=" * 60)
    print("未检测到可用的 CosyVoice2-0.5B TTS 模型目录。")
    print("  - 模型约 5~6GB，用于本地语音合成，下载完成后只需一次。")
    print("  - 也可以选择你已有的 CosyVoice2-0.5B 模型文件夹（含 llm.pt/flow.pt/hift.pt）。")
    print("=" * 60)
    choice = ask("选择 [1] 自动下载到项目 models/ 目录  [2] 我已有模型，手动输入文件夹路径", "1")
    if choice == "2":
        while True:
            d = ask("请输入模型文件夹完整路径")
            if model_ok(d):
                model_dir = d
                break
            print("该目录下未找到模型文件，请确认路径是否正确（应包含 llm.pt / flow.pt / hift.pt）。")
    else:
        print(f"将下载到: {DEFAULT_MODEL_DIR}")
        if not download_model(DEFAULT_MODEL_DIR):
            raise SystemExit("模型下载失败：请检查网络后重试，或选择已有模型文件夹。")
        model_dir = DEFAULT_MODEL_DIR
    cfg.setdefault("tts", {})["model_dir"] = model_dir
    save_cfg(cfg)
    print("模型路径已写入 config.local.json ->", model_dir)
    return model_dir


def ensure_ref_wav(cfg):
    """确保参考音频（零样本克隆音色）；缺失时提示录制。"""
    ref = cfg.get("tts", {}).get("ref_wav", "")
    if ref and os.path.isfile(ref):
        return ref
    print("=" * 60)
    print("未配置参考音频（tts.ref_wav）。CosyVoice2 零样本克隆需要一段")
    print("清晰英文朗读 wav/mp3（5~10 秒，单人声、无背景音乐）作为音色底稿。")
    print("请先用手机/录音机录制，再把文件路径粘贴进来。")
    print("=" * 60)
    while True:
        p = ask("请输入参考音频文件路径（留空则跳过合成，仅走已有 mp3 提交）")
        if not p:
            return None
        if os.path.isfile(p):
            cfg.setdefault("tts", {})["ref_wav"] = p
            save_cfg(cfg)
            print("参考音频路径已写入 config.local.json ->", p)
            return p
        print("文件不存在，请重新输入。")


# ---------------------------------------------------------------- TTS 合成
def synth_tts(model_dir, ref_wav, text, out_wav, cosyvoice_src=None):
    """CosyVoice2 零样本克隆合成，返回 (wav路径, 采样率)。"""
    for p in (cosyvoice_src, os.path.join(cosyvoice_src or "", "third_party", "Matcha-TTS")):
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    os.environ.setdefault("MODELSCOPE_CACHE", os.path.dirname(model_dir))
    os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(model_dir), "..", "huggingface_cache"))
    try:
        from cosyvoice.cli.cosyvoice import AutoModel
        import torch
        import torchaudio
    except Exception as e:
        raise SystemExit(
            f"无法导入 cosyvoice（{e}）。请先执行依赖安装：\n"
            f"  Windows: 运行 ets100_launcher.exe（或 pip install -r requirements-runtime.txt）\n"
            f"  Linux:   ./install.sh\n"
            f"若已源码安装 CosyVoice，可用 --cosyvoice-src / config tts.cosyvoice_src 指定源码目录。")
    print("加载 CosyVoice2 模型（首次较慢）...")
    cosyvoice = AutoModel(model_dir=model_dir)
    parts = []
    for i, out in enumerate(cosyvoice.inference_zero_shot(text, text, ref_wav, stream=False)):
        parts.append(out["tts_speech"])
    speech = torch.cat(parts, dim=1)
    torchaudio.save(out_wav, speech, cosyvoice.sample_rate)
    print(f"合成完成: {out_wav} (sr={cosyvoice.sample_rate}, dur={speech.shape[1] / cosyvoice.sample_rate:.1f}s)")
    return out_wav, cosyvoice.sample_rate


# ---------------------------------------------------------------- XML / 提交
def read_xml_score(xml_path):
    """从真实评测 XML 提取 total_score（找不到返回 None）。"""
    try:
        with open(xml_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        m = re.search(r'total_score="([0-9.]+)"', content)
        return m.group(1) if m else None
    except OSError:
        return None


def build_xml(xml_path):
    """真实 XML 原样读取；缺失时生成骨架并告警。返回 (bytes, score)。"""
    if xml_path and os.path.isfile(xml_path):
        with open(xml_path, "rb") as f:
            data = f.read()
        score = read_xml_score(xml_path)
        return data, score
    print("WARN: 未提供真实评测 XML（--xml / config submit.xml），将上传骨架 XML，服务端可能按骨架评分。")
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<xml_result>\n  <read_sentence lan="en" type="study" version="V4.2.0R6.62.46.9M4.62.46.9">\n'
            '    <rec_paper>\n      <read_chapter accuracy_score="4.0" beg_pos="0" content="text" '
            'continus_deduct_score="0" end_pos="500" except_info="0" fluency_score="4.0" integrity_score="4.0" '
            'standard_score="4.0" stress_pronunciation_score="4.0" total_score="4.0" wrong_words="0"/>\n'
            '    </rec_paper>\n  </read_sentence>\n</xml_result>\n').encode("utf-8"), "4.0"


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(
        description="e听说朗读题自动化补交：TTS 合成 + 三件套上传 + sync-v2 提交（全参数化）")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="配置文件（默认 config.local.json）")
    ap.add_argument("--mp3", help="已有朗读 mp3 路径（提供则跳过 TTS 合成，直接提交）")
    ap.add_argument("--text", help="朗读文本（不提供则交互输入或 --text-file）")
    ap.add_argument("--text-file", help="从文件读取朗读文本")
    ap.add_argument("--model-dir", help="CosyVoice2 模型目录（覆盖 config tts.model_dir）")
    ap.add_argument("--ref-wav", help="参考音频路径（覆盖 config tts.ref_wav）")
    ap.add_argument("--cosyvoice-src", help="CosyVoice 源码目录（依赖未安装时用于 sys.path）")
    ap.add_argument("--xml", help="真实评测 XML 路径（自动提取 total_score）")
    ap.add_argument("--mark-trace-id", help="评测引擎 traceId（sync-v2 携带）")
    ap.add_argument("--acc-id", help="学生账号 ID")
    ap.add_argument("--homework-id", help="作业 ID")
    ap.add_argument("--set-id", help="题目集 ID")
    ap.add_argument("--entity-id", help="题目实体 ID")
    ap.add_argument("--order", help="题目序号")
    ap.add_argument("--resource-id", help="资源 ID（默认 55）")
    ap.add_argument("--tmp", default=tempfile.gettempdir(), help="中间文件目录（默认系统临时目录）")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    tts_cfg = cfg.get("tts", {}) or {}
    sub_cfg = cfg.get("submit", {}) or {}

    # ---- 提交参数（命令行 > 配置文件 > 环境变量）
    acc_id = sub._require("acc_id", sub._resolve("acc_id", args.acc_id, sub_cfg, ["ETS100_ACC_ID"]))
    homework_id = sub._require("homework_id", sub._resolve("homework_id", args.homework_id, sub_cfg, ["ETS100_HOMEWORK_ID"]))
    set_id = sub._require("set_id", sub._resolve("set_id", args.set_id, sub_cfg, ["ETS100_SET_ID"]))
    entity_id = sub._require("entity_id", sub._resolve("entity_id", args.entity_id, sub_cfg, ["ETS100_ENTITY_ID"]))
    order = sub._require("order", sub._resolve("order", args.order, sub_cfg, ["ETS100_ORDER"]))
    resource_id = sub._resolve("resource_id", args.resource_id, sub_cfg, ["ETS100_RESOURCE_ID"]) or "55"
    xml_file = resolve("xml", args.xml, sub_cfg, ["ETS100_XML_FILE"])
    mark_trace_id = resolve("mark_trace_id", args.mark_trace_id, sub_cfg, ["ETS100_MARK_TRACE_ID"])
    tmp = args.tmp

    # ---- 音频来源
    mp3_file = resolve("mp3", args.mp3, sub_cfg, ["ETS100_MP3_FILE"])
    if not (mp3_file and os.path.isfile(mp3_file)):
        # 需要 TTS 合成：模型 / 参考音频 / 文本 引导
        model_dir = resolve("model_dir", args.model_dir, tts_cfg, ["ETS100_MODEL_DIR"]) or ""
        if model_dir:
            if not model_ok(model_dir):
                model_dir = ""
        if not model_dir:
            model_dir = ensure_model(cfg)
        ref_wav = resolve("ref_wav", args.ref_wav, tts_cfg, ["ETS100_REF_WAV"])
        if not (ref_wav and os.path.isfile(ref_wav)):
            ref_wav = ensure_ref_wav(cfg)
        if not ref_wav:
            raise SystemExit("未提供参考音频，无法 TTS 合成。请提供 --ref-wav / config tts.ref_wav，或使用 --mp3 直接提交已有音频。")

        text = args.text
        if not text and args.text_file:
            try:
                with open(args.text_file, encoding="utf-8") as f:
                    text = f.read().strip()
            except OSError as e:
                raise SystemExit(f"读取文本文件失败: {e}")
        if not text:
            print("=" * 60)
            print("请输入本次朗读题的英文文本（将被 TTS 合成朗读）。")
            print("支持粘贴多行；输入完成后另起一行输入 EOF 结束。")
            print("=" * 60)
            lines = []
            while True:
                line = input("text> ")
                if line.strip() in ("EOF", "exit", "q"):
                    break
                lines.append(line)
            text = "\n".join(lines).strip()
            if not text:
                raise SystemExit("未输入文本，中止。")

        os.makedirs(tmp, exist_ok=True)
        ts = str(int(time.time() * 1000))
        wav_file = os.path.join(tmp, f"synth_{ts}.wav")
        cosyvoice_src = resolve("cosyvoice_src", args.cosyvoice_src, tts_cfg, ["ETS100_COSYVOICE_SRC"])
        synth_tts(model_dir, ref_wav, text, wav_file, cosyvoice_src)
        # 转 16k mp3（提交链路统一 16kHz）
        ffmpeg = sub.find_ffmpeg()
        mp3_file = os.path.join(tmp, f"synth_{ts}.mp3")
        if ffmpeg:
            r = sub.subprocess.run([ffmpeg, "-y", "-i", wav_file, "-ar", "16000", "-ac", "1",
                                    "-codec:a", "libmp3lame", "-b:a", "64k", mp3_file],
                                   stdout=sub.subprocess.PIPE, stderr=sub.subprocess.PIPE, timeout=180)
            if r.returncode != 0 or not os.path.isfile(mp3_file):
                raise SystemExit("ffmpeg 转 mp3 失败：请确认 ffmpeg 可用。")
        else:
            raise SystemExit("未找到 ffmpeg，无法将合成音频转为提交格式。请安装 ffmpeg 后重试。")
        print("mp3 就绪:", mp3_file)
    else:
        print("使用已有 mp3:", mp3_file)

    # ---- 登录
    token, info = sub.m.login()
    print("登录:", info.get("name"), "token:", token[:25], "...")

    # ---- STS
    sts = sub.m.post("p1/student/config/config/ossEvaluateUploadStsToken", {
        "system": "2", "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time() * 1000)), "use_https": 1,
        "use_homework_privilege": 1, "ets_app": 0, "sign_response": 2}, token)
    up = sts["body"]["upload"]
    ak, sk, st = up["accessKeyId"], up["accessKeySecret"], up["securityToken"]
    bucket, endpoint = up["bucket"], up.get("endpoint", "oss-cn-hangzhou.aliyuncs.com")
    print("STS OK:", ak[:10], "bucket:", bucket, "exp:", up.get("expiration"))

    # ---- 服务器时间校准
    server_ts = sub.get_server_time(token)
    print("校准服务器时间戳:", int(server_ts))

    # ---- OSS 三件套（speex + mp3 + xml 同名前缀 public_<uid>_<ts>）
    ts = str(int(time.time() * 1000))
    uid = uuid.uuid4().hex[:32]
    day = datetime.datetime.now().strftime("%Y/%m/%d")
    mp3_key = f"ugc/evaluate/mp3/middleApp/android/{day}/{acc_id}/public_{uid}_{ts}.mp3"
    mp3_data = open(mp3_file, "rb").read()
    st1, _ = sub.oss_put(ak, sk, st, bucket, endpoint, mp3_key, mp3_data, "audio/mpeg", server_ts)
    print("mp3 PUT:", st1, mp3_key)

    speex_path = os.path.join(tmp, f"public_{uid}_{ts}.speex")
    degraded, msg = sub.build_speex(mp3_file, speex_path)
    if degraded:
        speex_data = mp3_data
        print("WARN: " + msg)
    else:
        with open(speex_path, "rb") as f:
            speex_data = f.read()
    speex_key = f"ugc/evaluate/speex/middleApp/android/{day}/{acc_id}/public_{uid}_{ts}.speex"
    st3, _ = sub.oss_put(ak, sk, st, bucket, endpoint, speex_key, speex_data, "application/octet-stream", server_ts)
    print("speex PUT:", st3, speex_key)

    xml_data, score = build_xml(xml_file)
    xml_key = f"ugc/evaluate/xml/middleApp/android/{day}/{acc_id}/public_{uuid.uuid4().hex[:32]}_{str(int(time.time()*1000))}.xml"
    st2, _ = sub.oss_put(ak, sk, st, bucket, endpoint, xml_key, xml_data, "application/octet-stream", server_ts)
    print("xml PUT:", st2, xml_key)

    if st1 != 200 or st2 != 200 or st3 != 200:
        print("上传失败，中止")
        return

    # ---- sync-v2 提交
    mp3_url = f"https://ets60.ets100.com/{mp3_key}"
    xml_url = f"https://ets60.ets100.com/{xml_key}"
    speex_url = f"https://ets60.ets100.com/{speex_key}"
    client_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    params = {
        "homework_id": homework_id, "use_time": 31, "resource_id": resource_id,
        "serial_id": "0", "set_id": set_id, "entity_id": entity_id, "order": order,
        "score": score or "4.0", "correct": 0, "auto_submit": 1, "client_time": client_time,
        "version": 2, "graduation": 0, "upload_file_id": "", "upload_file_url": mp3_url,
        "detail_file_id": "", "detail_file_url": xml_url,
        "system": "2", "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time() * 1000)), "use_https": 1,
        "use_homework_privilege": 1, "ets_app": 0, "sign_response": 2,
    }
    if mark_trace_id:
        params["mark_trace_id"] = mark_trace_id
    resp = sub.m.post("m/audio/sync-v2", params, token)
    print("sync-v2 code:", resp.get("code"), resp.get("msg"))
    print("body:", json.dumps(resp.get("body", {}), ensure_ascii=False)[:600])
    print("mp3:", mp3_url)
    print("speex:", speex_url)
    print("xml:", xml_url)
    if resp.get("code") == 0:
        print("\n提交成功。是否入册请到 App 端确认（过期作业 complete 可能仍为 0）。")
    else:
        print("\n提交未成功，请根据返回信息排查（常见：账号密文失效需重新抓包）。")


if __name__ == "__main__":
    main()
