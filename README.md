# cnmets — e听说自动化研究

对手机端 e听说（api.ets100.com）英语听说作业的接口逆向与自动化补交实验。

## 文件说明

| 文件 | 用途 |
|---|---|
| `ets100_auto_login_api.py` | 登录 / 签名 / 作业列表 / 账号列表等 API 封装 |
| `ets100_submit_upload.py` | 朗读音频补交：STS 凭证 → OSS 上传 → sync-v2 登记 |

## 协议要点（2026-10 实测）

- 签名：`sign = md5(pid + time_ms + body_base64 + SECRET_KEY)`，`pid` 固定 `grlx`
- body 为紧凑 JSON 数组 `[{"r": endpoint, "params": {...}}]` 的 Base64
- 传输需模拟 Android 指纹（curl_cffi `chrome131_android`），HTTP/2 易 405
- 朗读题上传链路：`ossEvaluateUploadStsToken` 取 STS → OSS V1 签名 PUT（mp3+xml，Date 按 ServerTime 校准）→ `m/audio/sync-v2` 登记

## 已知边界

- 客观题答案不在下发数据中（show_score_answer=0），需运行时逆向或 OCR
- 朗读题服务端会对上传音频重做 ise 评测，TTS 合成音难以达到完成线，需真人录音或高仿真克隆音
