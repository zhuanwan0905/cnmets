# -*- coding: utf-8 -*-
"""
e听说 (api.ets100.com) 自动化登录 + API 调用脚本
==================================================
协议要点（2026-10-17 实测验证）:
- 签名: sign = md5(pid + time_ms + body_base64 + SECRET_KEY)
  * pid 固定 "grlx"（head.pid 必须同时填 grlx，填 androidV3 会 400）
  * SECRET_KEY = "555ffbe95ccf4e9535a110170b445ab8"
  * body 为紧凑 JSON 数组 [{"r": endpoint, "params": {...}}] 的 Base64
  * time 为 13 位毫秒字符串，head.time_second 同步
- 传输: 强制 HTTP/1.1，curl_cffi impersonate="chrome131_android"
  （HTTP/2 易触发 405；WAF 依赖 UA/TLS 指纹）
- 登录: /user/login 参数 phone/password 均为加密密文，直接复用抓包值重放；
  也可动态重签名（phone/password 密文不变）刷新 token
- 账号与设备绑定信息不内置在代码中：按 参数 > 环境变量 > config.local.json 解析
  （ETS100_PHONE / ETS100_PASSWORD / ETS100_DEVICE_CODE / ETS100_DEVICE_NAME / ETS100_SN）
- 设备绑定: 登录返回 30014 时调 /user/rebind-code 模拟移动端重绑定
- 账号列表: /m/ecard/list，body.data 中混合类型需 isinstance(v, dict) 提取 parent_id
- 作业列表: /g/homework/list，status 1=进行中 2=历史 3=已过期

依赖: pip install curl_cffi
"""
import json
import base64
import hashlib
import os
import time

import curl_cffi.requests as crequests

BASE = "https://api.ets100.com"
SECRET_KEY = "555ffbe95ccf4e9535a110170b445ab8"
PID = "grlx"  # head.pid 与签名 pid 必须一致

# 请求模板。phone/password 为客户端加密后的密文，原样复用（若密文失效需重新抓包或
# 逆向加密算法）。账号与设备绑定信息不再内置：由 login() 按
# 参数 > 环境变量 > config.local.json（已被 .gitignore 排除，不入库）读取。
LOGIN_TPL = {
    "version": "4",
    "cancel_close": 0,
    "ets_ticket": "",
    "use_https": 1,
    "use_homework_privilege": 1,
    "system": "2",
    "global_client_version": "7.0.52.2263(2263)",
    "sign_response": 2,
    "token": "",
    "ets_app": 0,
}


def sign_payload(endpoint, params, token):
    """构造带签名的请求 payload"""
    p = dict(params)
    p["token"] = token
    body = [{"r": endpoint, "params": p}]
    ts = str(int(time.time() * 1000))
    plain = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    b64 = base64.b64encode(plain.encode()).decode()
    sign = hashlib.md5((PID + ts + b64 + SECRET_KEY).encode()).hexdigest()
    return {
        "body": b64,
        "head": {
            "sign": sign,
            "pid": PID,
            "time": ts,
            "time_second": int(ts),
            "version": "1.0",
        },
    }


def post(endpoint, params, token="", url=None):
    payload = sign_payload(endpoint, params, token)
    resp = crequests.post(
        url or f"{BASE}/{endpoint}",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        impersonate="chrome131_android",
        timeout=25,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Referer": BASE},
    )
    resp.raise_for_status()
    return json.loads(resp.text)[0]


def _load_login_config():
    """读取仓库根目录 config.local.json 的 login 段（不入库），缺失/异常返回 {}。"""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("login", {}) or {}
    except (OSError, ValueError):
        return {}


def login(phone=None, password=None, device_code=None, device_name=None, sn=None):
    """登录并返回 (token, 完整 body)。返回 30014 时提示重绑定。

    账号与设备绑定信息按 参数 > 环境变量 > config.local.json 解析：
    ETS100_PHONE / ETS100_PASSWORD / ETS100_DEVICE_CODE / ETS100_DEVICE_NAME / ETS100_SN
    """
    cfg = _load_login_config()
    phone = phone or os.environ.get("ETS100_PHONE") or cfg.get("phone")
    password = password or os.environ.get("ETS100_PASSWORD") or cfg.get("password")
    device_code = device_code or os.environ.get("ETS100_DEVICE_CODE") or cfg.get("device_code")
    device_name = device_name or os.environ.get("ETS100_DEVICE_NAME") or cfg.get("device_name") or "Xiaomi 2211133C"
    sn = sn or os.environ.get("ETS100_SN") or cfg.get("sn") or str(int(time.time() * 1000))
    if not phone or not password:
        raise RuntimeError("缺少登录凭据：请设置环境变量 ETS100_PHONE / ETS100_PASSWORD，"
                           "或在仓库 config.local.json 的 login 段提供")
    params = dict(LOGIN_TPL)
    params.update({"phone": phone, "password": password, "device_code": device_code,
                   "device_name": device_name, "sn": sn})
    resp = post("user/login", params, token="", url=f"{BASE}/user/login")
    if resp.get("code") == 30014:
        raise RuntimeError("设备绑定冲突 (30014)，需调 user/rebind-code 模拟移动端重绑定")
    if resp.get("code") != 0:
        raise RuntimeError(f"登录失败: {resp}")
    return resp["body"]["token"], resp["body"]


def ecard_list(token):
    """账号列表，递归提取 parent_id。"""
    resp = post("m/ecard/list", {
        "all": "1", "json_type": "1", "version": "2", "system": "2",
        "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time() * 1000)),
        "use_https": 1, "use_homework_privilege": 1, "ets_app": 0,
        "sign_response": 2,
    }, token)
    parent_ids = set()

    def walk(v):
        if isinstance(v, dict):
            for k, val in v.items():
                if k == "parent_id" and isinstance(val, (str, int)) and str(val) not in ("", "0"):
                    parent_ids.add(str(val))
                else:
                    walk(val)
        elif isinstance(v, list):
            for item in v:
                walk(item)

    walk(resp.get("body", {}))
    return list(parent_ids), resp


def homework_list(token, parent_id, status=1):
    """作业列表。status: 1 进行中 / 2 历史 / 3 已过期"""
    resp = post("g/homework/list", {
        "parent_account_id": parent_id, "status": status,
        "limit": 10, "offset": 0, "show_offline": 1, "show_old_homework": 1,
        "get_to_do_count": 1, "get_to_overtime_count": 1, "check_pass": 1,
        "only_parent": 1, "version": "4", "get_audio_task": 1, "system": "2",
        "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time() * 1000)),
        "use_https": 1, "use_homework_privilege": 1, "ets_app": 0,
        "sign_response": 2,
    }, token)
    return resp.get("body", {}).get("data", []), resp


def scan_all_homeworks(token):
    """扫描所有状态作业，返回 {status: [作业列表]}"""
    _, parent_ids = ecard_list(token)
    if not parent_ids:
        return {}, []
    result = {}
    for pid in parent_ids:
        for st in (1, 2, 3):
            items, _ = homework_list(token, pid, status=st)
            if items:
                result.setdefault(st, []).extend(items)
    return result, parent_ids


if __name__ == "__main__":
    print("== e听说 自动化 ==")
    token, info = login()
    print("登录成功:", info.get("name"), "token:", token[:30], "...")
    pids, _ = ecard_list(token)
    print("parent_id 列表:", pids)
    hw, pids2 = scan_all_homeworks(token)
    for st in sorted(hw):
        print(f"status={st} 作业数: {len(hw[st])}")
    print("完成")
