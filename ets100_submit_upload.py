# -*- coding: utf-8 -*-
"""CosyVoice2-0.5B 合成朗读音频补交：登录 -> STS -> OSS PUT(speex+mp3+xml) -> sync-v2
   补齐 speex 上传环节：真实客户端链路为 speex + mp3 + xml 三件套，speex 与 mp3 同名前缀
   public_<uid>_<ts>，上传到 ugc/evaluate/speex/middleApp/android/YYYY/MM/DD/<acc_id>/ 目录。
   speex 数据优先由 ffmpeg 将合成音频转 16kHz 单声道 .speex；本机无 ffmpeg 时降级为
   以 .speex 后缀直传 mp3 数据并打印告警。"""
import sys, json, time, hashlib, hmac, base64, uuid, datetime, email.utils, urllib.request, subprocess, os, argparse, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ets100_auto_login_api as m


def _load_config(path):
    """读取配置文件（默认仓库根目录 config.local.json，已被 .gitignore 排除），缺失/异常返回 {}。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _resolve(name, cli_val, cfg, env_names):
    """按 命令行 > 配置文件 > 环境变量 解析单个参数。"""
    if cli_val is not None:
        return cli_val
    if cfg.get(name):
        return cfg[name]
    for env in env_names:
        v = os.environ.get(env)
        if v:
            return v
    return None


def _require(name, val):
    if not val:
        raise SystemExit(f"缺少必填参数 {name}：请通过命令行 --{name}、config.local.json 或环境变量提供")
    return val

def get_server_time(token):
    """从 api 获取服务器时间（OSS 要求按 ServerTime 校准 Date，本机偏慢约2小时）"""
    try:
        resp = m.post("system/time", {"system": "2", "global_client_version": "7.0.52.2263(2263)",
                                      "sn": str(int(time.time()*1000)), "use_https": 1,
                                      "use_homework_privilege": 1, "ets_app": 0, "sign_response": 2}, token)
        body = resp.get("body", {})
        if isinstance(body, dict) and body.get("server_time"):
            return float(body["server_time"]) / 1000.0
        if isinstance(body, (int, float)) and body > 0:
            return float(body) / 1000.0
    except Exception as e:
        print("system/time 失败:", e)
    # 兜底：直接用本机时间+2小时偏差
    return time.time() + 7200

def oss_put(ak, sk, token, bucket, endpoint, object_key, data, content_type, server_ts):
    """OSS V1 hmac-sha1 签名 PUT。Date 使用服务器时间。"""
    date_gmt = email.utils.formatdate(server_ts, usegmt=True)
    canonical_headers = f"x-oss-object-acl:public-read\nx-oss-security-token:{token}\n"
    canonical_resource = f"/{bucket}/{object_key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date_gmt}\n{canonical_headers}{canonical_resource}"
    signature = base64.b64encode(
        hmac.new(sk.encode(), string_to_sign.encode(), hashlib.sha1).digest()).decode()
    url = f"https://{bucket}.{endpoint}/{object_key}"
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"OSS {ak}:{signature}")
    req.add_header("Date", date_gmt)
    req.add_header("Content-Type", content_type)
    req.add_header("x-oss-object-acl", "public-read")
    req.add_header("x-oss-security-token", token)
    req.add_header("User-Agent", "aliyun-sdk-android/2.9.18(Linux/Android 15/2211133C;AQ3A.240912.001)")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode(errors="ignore")

def find_ffmpeg():
    """在 PATH 与常见安装位置中查找 ffmpeg.exe，返回绝对路径或 None。"""
    candidates = ["ffmpeg", r"D:\ffmpeg\bin\ffmpeg.exe",
                  r"C:\ffmpeg\bin\ffmpeg.exe",
                  r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]
    # WinGet 安装位置（Gyan.FFmpeg / BtbN 等）
    import glob
    for base in (os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),):
        candidates += glob.glob(base + r"\**\ffmpeg.exe", recursive=True)
    for cand in candidates:
        try:
            if os.path.isfile(cand):
                return cand
            subprocess.run([cand, "-version"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
            return cand
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def build_speex(mp3_path, speex_path):
    """用 ffmpeg 将 mp3 转为 16kHz 单声道真 speex（Ogg 封装，libspeex 编码）。

    讯飞 ise 链路常见格式为 Ogg/Speex（16kHz 单声道）。ffmpeg 无法以裸 .speex
    扩展名自动选容器，故显式指定 -f ogg 封装。无 ffmpeg 或转码失败时降级为
    复制 mp3 数据并以 .speex 后缀上传并告警。

    返回 (是否降级, 提示信息)。
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        cmd = [ffmpeg, "-y", "-i", mp3_path, "-ar", "16000", "-ac", "1",
               "-c:a", "libspeex", "-f", "ogg", speex_path]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if r.returncode == 0 and os.path.isfile(speex_path) and os.path.getsize(speex_path) > 0:
            return False, f"ffmpeg 真 speex 转换成功(Ogg封装): {ffmpeg}"
        return True, f"ffmpeg 转换失败(rc={r.returncode})，降级直传 mp3 数据"
    return True, "未检测到 ffmpeg，降级直传 mp3 数据(以 .speex 后缀上传)"

def main():
    ap = argparse.ArgumentParser(
        description="e听说朗读音频补交（参数化）：登录 -> STS -> OSS PUT(speex+mp3+xml) -> sync-v2")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json"),
                    help="配置文件路径（默认仓库根目录 config.local.json）")
    ap.add_argument("--mp3", help="本地朗读 mp3 路径")
    ap.add_argument("--acc-id", help="学生账号 ID")
    ap.add_argument("--homework-id", help="作业 ID")
    ap.add_argument("--set-id", help="题目集 ID")
    ap.add_argument("--entity-id", help="题目实体 ID")
    ap.add_argument("--order", help="题目序号")
    ap.add_argument("--resource-id", help="资源 ID（默认 55）")
    ap.add_argument("--tmp", default=tempfile.gettempdir(), help="speex 中间文件目录（默认系统临时目录）")
    args = ap.parse_args()
    cfg = _load_config(args.config).get("submit", {}) or {}

    mp3_file = _require("mp3", _resolve("mp3", args.mp3, cfg, ["ETS100_MP3_FILE"]))
    acc_id = _require("acc_id", _resolve("acc_id", args.acc_id, cfg, ["ETS100_ACC_ID"]))
    homework_id = _require("homework_id", _resolve("homework_id", args.homework_id, cfg, ["ETS100_HOMEWORK_ID"]))
    set_id = _require("set_id", _resolve("set_id", args.set_id, cfg, ["ETS100_SET_ID"]))
    entity_id = _require("entity_id", _resolve("entity_id", args.entity_id, cfg, ["ETS100_ENTITY_ID"]))
    order = _require("order", _resolve("order", args.order, cfg, ["ETS100_ORDER"]))
    resource_id = _resolve("resource_id", args.resource_id, cfg, ["ETS100_RESOURCE_ID"]) or "55"
    tmp = args.tmp

    token, info = m.login()
    print("登录:", info.get("name"), "token:", token[:25], "...")

    # 1. STS
    sts = m.post("p1/student/config/config/ossEvaluateUploadStsToken", {
        "system": "2", "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time()*1000)), "use_https": 1,
        "use_homework_privilege": 1, "ets_app": 0, "sign_response": 2}, token)
    up = sts["body"]["upload"]
    ak, sk, st = up["accessKeyId"], up["accessKeySecret"], up["securityToken"]
    bucket, endpoint = up["bucket"], up.get("endpoint", "oss-cn-hangzhou.aliyuncs.com")
    print("STS OK:", ak[:10], "bucket:", bucket, "exp:", up.get("expiration"))

    # 2. 服务器时间校准
    server_ts = get_server_time(token)
    print("校准服务器时间戳:", int(server_ts))

    # 3. 上传 mp3 / speex（真实链路三件套：speex + mp3 同名前缀 public_<uid>_<ts>）
    ts = str(int(time.time() * 1000))
    uid = uuid.uuid4().hex[:32]
    day = datetime.datetime.now().strftime("%Y/%m/%d")
    mp3_key = f"ugc/evaluate/mp3/middleApp/android/{day}/{acc_id}/public_{uid}_{ts}.mp3"
    mp3_data = open(mp3_file, "rb").read()
    st1, _ = oss_put(ak, sk, st, bucket, endpoint, mp3_key, mp3_data, "audio/mpeg", server_ts)
    print("mp3 PUT:", st1, mp3_key)

    # 3b. 补齐 speex：优先 ffmpeg 转 16kHz 单声道，无 ffmpeg 则降级直传 mp3 数据
    speex_path = os.path.join(tmp, f"public_{uid}_{ts}.speex")
    degraded, msg = build_speex(mp3_file, speex_path)
    if degraded:
        # 降级：直接以 mp3 数据充当 speex 内容上传
        speex_data = mp3_data
        print("WARN: " + msg)
    else:
        with open(speex_path, "rb") as f:
            speex_data = f.read()
    speex_key = f"ugc/evaluate/speex/middleApp/android/{day}/{acc_id}/public_{uid}_{ts}.speex"
    st3, _ = oss_put(ak, sk, st, bucket, endpoint, speex_key, speex_data, "application/octet-stream", server_ts)
    print("speex PUT:", st3, speex_key)

    # 4. 生成并上传 xml（ise 评测结果骨架，服务端会重新评测 mp3）
    xml_key = f"ugc/evaluate/xml/middleApp/android/{day}/{acc_id}/public_{uuid.uuid4().hex[:32]}_{str(int(time.time()*1000))}.xml"
    xml_body = ('<?xml version="1.0" encoding="utf-8"?>\n'
                '<xml_result>\n  <read_sentence lan="en" type="study" version="V4.2.0R6.62.46.9M4.62.46.9">\n'
                '    <rec_paper>\n      <read_chapter accuracy_score="4.0" beg_pos="0" content="Chinese painting" '
                'continus_deduct_score="0" end_pos="500" except_info="0" fluency_score="4.0" integrity_score="4.0" '
                'standard_score="4.0" stress_pronunciation_score="4.0" total_score="4.0" wrong_words="0"/>\n'
                '    </rec_paper>\n  </read_sentence>\n</xml_result>\n').encode("utf-8")
    st2, _ = oss_put(ak, sk, st, bucket, endpoint, xml_key, xml_body, "application/octet-stream", server_ts)
    print("xml PUT:", st2, xml_key)

    if st1 != 200 or st2 != 200 or st3 != 200:
        print("上传失败，中止")
        return

    # 5. sync-v2 登记补交
    mp3_url = f"https://ets60.ets100.com/{mp3_key}"
    xml_url = f"https://ets60.ets100.com/{xml_key}"
    speex_url = f"https://ets60.ets100.com/{speex_key}"
    client_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resp = m.post("m/audio/sync-v2", {
        "homework_id": homework_id, "use_time": 31, "resource_id": resource_id,
        "serial_id": "0", "set_id": set_id, "entity_id": entity_id, "order": order,
        "score": "4.0", "correct": 0, "auto_submit": 1, "client_time": client_time,
        "version": 2, "graduation": 0, "upload_file_id": "", "upload_file_url": mp3_url,
        "detail_file_id": "", "detail_file_url": xml_url,
        "system": "2", "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time()*1000)), "use_https": 1,
        "use_homework_privilege": 1, "ets_app": 0, "sign_response": 2}, token)
    print("sync-v2 code:", resp.get("code"), resp.get("msg"))
    print("body:", json.dumps(resp.get("body", {}), ensure_ascii=False)[:600])
    print("mp3:", mp3_url)
    print("speex:", speex_url)
    print("xml:", xml_url)

if __name__ == "__main__":
    main()
