# cnmets — e听说自动化研究

对手机端 e听说（api.ets100.com）英语听说作业的接口逆向与自动化补交实验。

## 文件说明

| 文件 | 用途 |
|---|---|
| `ets100_auto_login_api.py` | 登录 / 签名 / 作业列表 / 账号列表等 API 封装 |
| `ets100_submit_upload.py` | 朗读音频补交：STS 凭证 → OSS 上传 → sync-v2 登记 |
| `ets100_tts_submit.py` | 全链路主程序：TTS 合成(CosyVoice2) → 16k mp3/speex → 上传提交（含模型/参考音频交互引导） |
| `ets100_launcher.py` | 一键启动器：自动建 venv、装依赖、引导模型，可打包为 Windows exe |
| `build_windows.bat` | 打包 `ets100_launcher.py` 为 `dist\ets100_launcher.exe` |
| `install.sh` | Linux 一键安装/运行（检测 python3/ffmpeg → venv → 依赖 → 模型引导） |
| `requirements-runtime.txt` | 运行依赖清单（curl_cffi / torch / torchaudio / cosyvoice / Matcha-TTS / modelscope / huggingface_hub） |
| `config.example.json` | 配置模板（copy 为 `config.local.json` 后填写） |
| `config.local.json` | 本机私有配置（已被 `.gitignore` 排除，不入库） |

## 一键启动（Windows exe / Linux sh）

**Windows**：先本机打包一次（需 Python 3.10+）：

```powershell
build_windows.bat
```

产物 `dist\ets100_launcher.exe` 可复制给任何 Windows 用户。运行后启动器会：
1. 自动创建项目 `.venv` 并安装依赖（首次较慢，含 torch CPU 版）
2. 引导 TTS 模型：选择自动下载 CosyVoice2-0.5B（约 5~6GB），或选择你已有的模型文件夹
3. 进入主程序交互

**Linux**：

```bash
chmod +x install.sh
./install.sh                 # 首次自动装依赖并引导模型
./install.sh --text "Hello"  # 传参直达主程序
```

> 说明：exe/sh 只负责"环境准备 + 模型引导"，真正的登录凭据仍在 `config.local.json` 或环境变量中，不内置于可执行文件。

## 配置

脚本不内置任何账号/作业信息，全部按 **命令行参数 > `config.local.json` > 环境变量** 解析。

1. 复制模板并填写：

   ```powershell
   copy config.example.json config.local.json
   ```

2. 编辑 `config.local.json`：
   - `login` 段：e听说账号加密密文（phone/password，抓包获得）、设备绑定信息（device_code / device_name / sn）
   - `tts` 段：`model_dir` CosyVoice2 模型目录（缺省自动引导下载/选择）、`ref_wav` 参考音频路径（5~10 秒英文朗读，缺省交互提示）、`cosyvoice_src` CosyVoice 源码目录（pip 未安装 cosyvoice 时用于 sys.path）
   - `submit` 段：`mp3` 本地音频绝对路径、`xml` 真实评测 XML（自动提取 `total_score` 作为提交分）、`mark_trace_id` 评测引擎 traceId、`acc_id` 学生账号 ID、`homework_id` / `set_id` / `entity_id` / `order` 作业与题目标识、`resource_id` 资源 ID

3. 或使用环境变量：`ETS100_PHONE` / `ETS100_PASSWORD` / `ETS100_DEVICE_CODE` / `ETS100_DEVICE_NAME` / `ETS100_SN` / `ETS100_MP3_FILE` / `ETS100_XML_FILE` / `ETS100_MARK_TRACE_ID` / `ETS100_MODEL_DIR` / `ETS100_REF_WAV` / `ETS100_COSYVOICE_SRC` / `ETS100_ACC_ID` / `ETS100_HOMEWORK_ID` / `ETS100_SET_ID` / `ETS100_ENTITY_ID` / `ETS100_ORDER` / `ETS100_RESOURCE_ID`

## 使用方法

```powershell
# 依赖（或直接用启动器，自动安装）
pip install -r requirements-runtime.txt

# 方式一：已有朗读 mp3，直接补交（使用 config.local.json）
python ets100_tts_submit.py

# 方式二：无 mp3，走 TTS 合成（交互引导模型/参考音频/文本）
python ets100_tts_submit.py --text "Chinese painting is one of the oldest forms of art..."

# 方式三：全部走命令行
python ets100_tts_submit.py --mp3 C:\audio\read.mp3 --acc-id <acc_id> `
  --homework-id <作业ID> --set-id <题目集ID> --entity-id <题目实体ID> --order <序号> `
  --xml C:\audio\resp.xml --mark-trace-id <traceId>

# 低层提交脚本（不含 TTS，仅上传）
python ets100_submit_upload.py

# 登录相关工具
python ets100_auto_login_api.py
```

> 安全提醒：`config.local.json` 包含你的账号密文与设备绑定信息，已被 `.gitignore` 排除，请勿手动提交到仓库。

## 协议要点（2026-10 实测）

- 签名：`sign = md5(pid + time_ms + body_base64 + SECRET_KEY)`，`pid` 固定 `grlx`
- body 为紧凑 JSON 数组 `[{"r": endpoint, "params": {...}}]` 的 Base64
- 传输需模拟 Android 指纹（curl_cffi `chrome131_android`），HTTP/2 易 405
- 朗读题上传链路：`ossEvaluateUploadStsToken` 取 STS → OSS V1 签名 PUT（speex+mp3+xml 三件套，Date 按 ServerTime 校准）→ `m/audio/sync-v2` 登记

## 已知边界

- 客观题答案不在下发数据中（show_score_answer=0），需运行时逆向或 OCR
- 朗读题服务端会对上传音频重做 ise 评测，TTS 合成音难以达到完成线，需真人录音或高仿真克隆音
- speex 必须用 `ffmpeg -f ogg libspeex` 真编码，否则评测全 0 分
