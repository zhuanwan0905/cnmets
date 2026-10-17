# cnmets — e听说自动化研究

对手机端 e听说（api.ets100.com）英语听说作业的接口逆向与自动化补交实验。

## 文件说明

| 文件 | 用途 |
|---|---|
| `ets100_auto_login_api.py` | 登录 / 签名 / 作业列表 / 账号列表等 API 封装 |
| `ets100_submit_upload.py` | 朗读音频补交：STS 凭证 → OSS 上传 → sync-v2 登记 |
| `config.example.json` | 配置模板（copy 为 `config.local.json` 后填写） |
| `config.local.json` | 本机私有配置（已被 `.gitignore` 排除，不入库） |

## 配置

脚本不内置任何账号/作业信息，全部按 **命令行参数 > `config.local.json` > 环境变量** 解析。

1. 复制模板并填写：

   ```powershell
   copy config.example.json config.local.json
   ```

2. 编辑 `config.local.json`：
   - `login` 段：e听说账号加密密文（phone/password，抓包获得）、设备绑定信息（device_code / device_name / sn）
   - `submit` 段：`mp3` 本地音频绝对路径、`acc_id` 学生账号 ID、`homework_id` / `set_id` / `entity_id` / `order` 作业与题目标识、`resource_id` 资源 ID

3. 或使用环境变量：`ETS100_PHONE` / `ETS100_PASSWORD` / `ETS100_DEVICE_CODE` / `ETS100_DEVICE_NAME` / `ETS100_SN` / `ETS100_MP3_FILE` / `ETS100_ACC_ID` / `ETS100_HOMEWORK_ID` / `ETS100_SET_ID` / `ETS100_ENTITY_ID` / `ETS100_ORDER` / `ETS100_RESOURCE_ID`

## 使用方法

```powershell
# 依赖
pip install curl_cffi

# 使用 config.local.json（推荐）
python ets100_submit_upload.py

# 全部走命令行
python ets100_submit_upload.py --mp3 C:\audio\read.mp3 --acc-id <你的acc_id> `
  --homework-id <作业ID> --set-id <题目集ID> --entity-id <题目实体ID> --order <序号>

# 登录相关工具
python ets100_auto_login_api.py
```

> 安全提醒：`config.local.json` 包含你的账号密文与设备绑定信息，已被 `.gitignore` 排除，请勿手动提交到仓库。

## 协议要点（2026-10 实测）

- 签名：`sign = md5(pid + time_ms + body_base64 + SECRET_KEY)`，`pid` 固定 `grlx`
- body 为紧凑 JSON 数组 `[{"r": endpoint, "params": {...}}]` 的 Base64
- 传输需模拟 Android 指纹（curl_cffi `chrome131_android`），HTTP/2 易 405
- 朗读题上传链路：`ossEvaluateUploadStsToken` 取 STS → OSS V1 签名 PUT（mp3+xml，Date 按 ServerTime 校准）→ `m/audio/sync-v2` 登记

## 已知边界

- 客观题答案不在下发数据中（show_score_answer=0），需运行时逆向或 OCR
- 朗读题服务端会对上传音频重做 ise 评测，TTS 合成音难以达到完成线，需真人录音或高仿真克隆音
- speex 必须用 `ffmpeg -f ogg libspeex` 真编码，否则评测全 0 分
