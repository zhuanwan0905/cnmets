# -*- coding: utf-8 -*-
"""CosyVoice2-0.5B 合成朗读音频补交：登录 -> STS -> OSS PUT(mp3+xml) -> sync-v2"""
import sys, json, time, hashlib, hmac, base64, uuid, datetime, email.utils, urllib.request
sys.path.insert(0, r"C:\Users\81155\AppData\Roaming\Tencent\Marvis\User\A92F03260CDE18D33E23B6FA1F0B7490\workspace\conv_71973da86a524ced90b19e7a023ef6e8\output")
import ets100_auto_login_api as m

TMP = r"C:\Users\81155\AppData\Roaming\Tencent\Marvis\User\A92F03260CDE18D33E23B6FA1F0B7490\workspace\conv_71973da86a524ced90b19e7a023ef6e8\temp"
MP3_FILE = TMP + r"\synth_st10.mp3"
HOMEWORK_ID = "107439545"
SET_ID = "634821"
ENTITY_ID = "618292"
ORDER = "10"
RESOURCE_ID = "55"
ACC_ID = "17580092"

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

def main():
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

    # 3. 上传 mp3
    ts = str(int(time.time() * 1000))
    uid = uuid.uuid4().hex[:32]
    day = datetime.datetime.now().strftime("%Y/%m/%d")
    mp3_key = f"ugc/evaluate/mp3/middleApp/android/{day}/{ACC_ID}/public_{uid}_{ts}.mp3"
    mp3_data = open(MP3_FILE, "rb").read()
    st1, _ = oss_put(ak, sk, st, bucket, endpoint, mp3_key, mp3_data, "audio/mpeg", server_ts)
    print("mp3 PUT:", st1, mp3_key)

    # 4. 生成并上传 xml（ise 评测结果骨架，服务端会重新评测 mp3）
    xml_key = f"ugc/evaluate/xml/middleApp/android/{day}/{ACC_ID}/public_{uuid.uuid4().hex[:32]}_{str(int(time.time()*1000))}.xml"
    xml_body = ('<?xml version="1.0" encoding="utf-8"?>\n'
                '<xml_result>\n  <read_sentence lan="en" type="study" version="V4.2.0R6.62.46.9M4.62.46.9">\n'
                '    <rec_paper>\n      <read_chapter accuracy_score="4.0" beg_pos="0" content="Chinese painting" '
                'continus_deduct_score="0" end_pos="500" except_info="0" fluency_score="4.0" integrity_score="4.0" '
                'standard_score="4.0" stress_pronunciation_score="4.0" total_score="4.0" wrong_words="0"/>\n'
                '    </rec_paper>\n  </read_sentence>\n</xml_result>\n').encode("utf-8")
    st2, _ = oss_put(ak, sk, st, bucket, endpoint, xml_key, xml_body, "application/octet-stream", server_ts)
    print("xml PUT:", st2, xml_key)

    if st1 != 200 or st2 != 200:
        print("上传失败，中止")
        return

    # 5. sync-v2 登记补交
    mp3_url = f"https://ets60.ets100.com/{mp3_key}"
    xml_url = f"https://ets60.ets100.com/{xml_key}"
    client_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resp = m.post("m/audio/sync-v2", {
        "homework_id": HOMEWORK_ID, "use_time": 31, "resource_id": RESOURCE_ID,
        "serial_id": "0", "set_id": SET_ID, "entity_id": ENTITY_ID, "order": ORDER,
        "score": "4.0", "correct": 0, "auto_submit": 1, "client_time": client_time,
        "version": 2, "graduation": 0, "upload_file_id": "", "upload_file_url": mp3_url,
        "detail_file_id": "", "detail_file_url": xml_url,
        "system": "2", "global_client_version": "7.0.52.2263(2263)",
        "sn": str(int(time.time()*1000)), "use_https": 1,
        "use_homework_privilege": 1, "ets_app": 0, "sign_response": 2}, token)
    print("sync-v2 code:", resp.get("code"), resp.get("msg"))
    print("body:", json.dumps(resp.get("body", {}), ensure_ascii=False)[:600])
    print("mp3:", mp3_url)
    print("xml:", xml_url)

if __name__ == "__main__":
    main()
