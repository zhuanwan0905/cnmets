# -*- coding: utf-8 -*-
"""
e听说 (api.ets100.com) 听后选择题自动作答模块
====================================================
逆向结论（2026-10-19 实测验证）:

1. 题目包解密拿标准答案
   作业题目包 zip 从 https://cdnsubject.ets100.com/made/{hash}.zip 下发，
   zip 尾部 336 字节中 [16:144] 段为 seed，
   密码 = md5(seed).upper() + md5(md5(seed).upper()).upper()
   解压后 info.json 的 xtlist 内 stander_ans / answer 即为标准答案。

2. 选择题提交
   每道小题(entity_id x order)发一次:
   POST https://api.ets100.com/m/audio/sync-v2
   score_detail = {"total_score":"3.0","choose":"<选项字母>","category":"choose", ...}
   音频字段全空即可，服务端按 choose 写入作答记录并计入完成度
   （纯分数上报不带 choose/category=choose 不会被统计）。

3. 核验
   POST https://api.ets100.com/m/homework/info
   score 数组中目标 entity 的 answer/detail 非空 => 记录已入库。

依赖: pip install curl_cffi（与 ets100_auto_login_api.py 相同）
"""
import json
import hashlib
import io
import time
import zipfile

from ets100_auto_login_api import post


def decrypt_package_zip(zip_path):
    """解密题目包 zip 并返回 info.json 内容。

    zip 尾部 336 字节 -> seed -> 双层 md5 大写拼接为 zip 密码。
    """
    with open(zip_path, "rb") as f:
        data = f.read()
    tail = data[-336:]
    seed = tail[16:144]
    pwd1 = hashlib.md5(seed).hexdigest().upper()
    pwd2 = hashlib.md5(pwd1.encode()).hexdigest().upper()
    password = (pwd1 + pwd2).encode()
    zf = zipfile.ZipFile(io.BytesIO(data))
    name = zf.namelist()[0]
    raw = zf.read(name, pwd=password)
    return json.loads(raw.decode("utf-8"))


def extract_answers(info):
    """从解密后的 info.json 提取标准答案。

    返回 {entity_id: {order: 选项字母}}，兼容 xtlist / list 两种键名。
    """
    answers = {}
    items = info.get("xtlist") or info.get("list") or []
    for item in items:
        eid = str(item.get("entity_id") or item.get("set_id") or "")
        if not eid:
            continue
        order = int(item.get("order") or 1)
        ans = item.get("stander_ans") or item.get("answer") or item.get("user_ans") or ""
        if not ans:
            continue
        answers.setdefault(eid, {})[order] = ans
    return answers


def submit_choices(token, homework_id, set_id, resource_id, answers,
                   parent_account_id=None, use_time=18):
    """按标准答案提交听后选择题，每道小题一个 sync-v2。

    参数:
        answers: extract_answers 的返回值 {entity_id: {order: 选项字母}}
    返回: [(entity_id, order, answer, code, is_update), ...]
    """
    base = {
        "system": "2",
        "global_client_version": "7.0.52.2263(2263)",
        "use_https": 1,
        "use_homework_privilege": 1,
        "ets_app": 0,
        "sign_response": 2,
    }
    results = []
    for eid, orders in sorted(answers.items()):
        for order, ans in sorted(orders.items()):
            score_detail = json.dumps({
                "total_score": "3.0",
                "choose": ans,
                "fluency_score": "0.0",
                "accuracy_score": "0.0",
                "integrity_score": "0.0",
                "standard_score": "0.0",
                "category": "choose",
                "repeat_mode": "0",
                "version": "7.0.52.2263(2263)",
                "rate_scale": 0,
            }, separators=(",", ":"))
            resp = post("m/audio/sync-v2", dict(
                base,
                homework_id=homework_id,
                use_time=use_time,
                resource_id=resource_id,
                serial_id="0",
                set_id=set_id,
                entity_id=eid,
                order=str(order),
                score="3.0",
                correct=0,
                auto_submit=1,
                client_time=time.strftime("%Y-%m-%d %H:%M:%S"),
                version=2,
                graduation=0,
                upload_file_id="0",
                upload_file_url="",
                detail_file_id="",
                detail_file_url="",
                score_detail=score_detail,
                mark_service=1,
                spx_file_url="",
                mark_trace_id="",
                sn=str(int(time.time() * 1000)),
            ), token)
            code = resp.get("code")
            is_update = resp.get("body", {}).get("is_update")
            results.append((eid, order, ans, code, is_update))
            print(f"[sync] {eid} o{order} -> {ans} | code={code} is_update={is_update}")
    return results


def verify_submitted(token, homework_id, resource_id, entity_ids):
    """核验：m/homework/info 中目标实体 answer/detail 是否非空。"""
    base = {
        "system": "2",
        "global_client_version": "7.0.52.2263(2263)",
        "use_https": 1,
        "use_homework_privilege": 1,
        "ets_app": 0,
        "sign_response": 2,
    }
    resp = post("m/homework/info", dict(
        base, resource_id=resource_id, homework_id=homework_id,
        version=2, sn=str(int(time.time() * 1000)),
    ), token)
    body = resp.get("body") or {}
    rows = body.get("score") or []
    detail_map = {}
    for s in rows:
        eid = str(s.get("entity_id"))
        if eid in entity_ids:
            detail_map.setdefault(eid, []).append({
                "order": s.get("order"),
                "answer": s.get("answer"),
                "audio_file_id": s.get("audio_file_id"),
                "detail": bool(s.get("detail")),
            })
    print("[verify] complete =", body.get("complete"))
    for eid in sorted(detail_map):
        print(f"[verify] {eid}: {detail_map[eid]}")
    return body.get("complete"), detail_map


if __name__ == "__main__":
    # 示例流程（需要先把题目包 zip 存到本地）
    from ets100_auto_login_api import login

    token, _ = login()
    print("登录成功, token:", token[:24], "...")

    # 1) 解密题目包拿答案
    # info = decrypt_package_zip("question_package.zip")
    # answers = extract_answers(info)
    # print(json.dumps(answers, ensure_ascii=False, indent=2))

    # 2) 提交
    # submit_choices(token, homework_id="...", set_id="...", resource_id="...",
    #                answers=answers)

    # 3) 核验
    # verify_submitted(token, homework_id="...", resource_id="...",
    #                  entity_ids=list(answers.keys()))
