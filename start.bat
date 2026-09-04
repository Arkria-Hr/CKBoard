@echo off
chcp 65001 >nul
title CKBoard 白板服务器
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.8 及以上版本。
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo 正在启动 CKBoard 服务...
echo 启动后请在【平板浏览器】打开窗口中显示的地址（如 http://192.168.1.107）
echo 首次启动如弹出 Windows 防火墙提示，请勾选"专用网络"并点击"允许访问"。
echo.
python server.py %*
pause
