@echo off
chcp 65001 > nul
title ComfyUI Node Translator - Startup Script

:: 初始化并优先使用项目内环境
call scripts\init_env.bat
call set_env.bat

:: 安装依赖（如未安装）
call scripts\install_requirements.bat

:: Start the main program without console window
echo [INFO] Starting the program...
echo [INFO] GUI窗口将在几秒后打开...
echo [INFO] 所有日志信息将显示在GUI的"控制台"选项卡中
timeout /t 2 /nobreak > nul

:: 使用项目内 pythonw.exe 启动GUI程序，不显示控制台窗口
start "" .venv\Scripts\pythonw.exe main.py
exit
