@echo off
rem ============================================
rem  打包 e听说一键启动器为 Windows exe
rem  前置：已安装 Python 3.10+（含 py launcher）
rem  产物：dist\ets100_launcher.exe
rem ============================================
setlocal
cd /d %~dp0

echo [1/2] 安装 pyinstaller ...
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

echo [2/2] 打包 ets100_launcher.exe ...
py -3 -m PyInstaller -F -n ets100_launcher ets100_launcher.py --distpath dist --workpath build --specpath build
if errorlevel 1 goto :err

echo.
echo 打包完成：dist\ets100_launcher.exe
echo 用法：
echo   1. 双击 dist\ets100_launcher.exe（首次会创建 .venv 并引导下载 TTS 模型）
echo   2. 或命令行传参：ets100_launcher.exe --text "朗读文本"
echo.
goto :eof

:err
echo 打包失败，请检查上方日志。
exit /b 1
