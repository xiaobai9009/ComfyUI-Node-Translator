#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强制刷新ComfyUI翻译缓存
"""

import os
import shutil
import json
import time

def force_refresh_translation():
    """强制刷新翻译"""
    comfyui_path = r"D:\AIAIAI\1_ComfyUI_Mie_V6.01\ComfyUI"
    
    print("🔄 强制刷新ComfyUI翻译...")
    
    # 1. 检查并备份原翻译文件
    translation_file = os.path.join(
        comfyui_path,
        "custom_nodes",
        "ComfyUI-DD-Translation",
        "zh-CN",
        "Nodes",
        "ComfyUI-MieNodes.json"
    )
    
    if os.path.exists(translation_file):
        print(f"✅ 找到翻译文件: {translation_file}")
        
        # 创建备份
        backup_file = translation_file + ".backup"
        shutil.copy2(translation_file, backup_file)
        print(f"📁 已创建备份: {backup_file}")
        
        # 临时删除翻译文件
        os.remove(translation_file)
        print("🗑️ 临时删除翻译文件")
        
        # 等待2秒
        time.sleep(2)
        
        # 恢复翻译文件
        shutil.copy2(backup_file, translation_file)
        print("📁 恢复翻译文件")
        
        # 删除备份
        os.remove(backup_file)
        print("🗑️ 删除备份文件")
        
    else:
        print(f"❌ 翻译文件不存在: {translation_file}")
        return
    
    # 2. 检查并清理可能的缓存文件
    cache_dirs = [
        os.path.join(comfyui_path, "custom_nodes", "ComfyUI-DD-Translation", "__pycache__"),
        os.path.join(comfyui_path, "__pycache__"),
        os.path.join(comfyui_path, "web", "cache")  # 如果存在
    ]
    
    for cache_dir in cache_dirs:
        if os.path.exists(cache_dir):
            try:
                shutil.rmtree(cache_dir)
                print(f"🗑️ 清理缓存目录: {cache_dir}")
            except Exception as e:
                print(f"⚠️ 无法清理缓存目录 {cache_dir}: {e}")
    
    # 3. 修改翻译文件的时间戳
    if os.path.exists(translation_file):
        # 更新文件的修改时间为当前时间
        current_time = time.time()
        os.utime(translation_file, (current_time, current_time))
        print("⏰ 更新翻译文件时间戳")
    
    # 4. 检查ComfyUI-DD-Translation配置
    config_file = os.path.join(
        comfyui_path,
        "custom_nodes",
        "ComfyUI-DD-Translation",
        "config.json"
    )
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 确保翻译功能启用
            config["translation_enabled"] = True
            
            # 添加强制刷新标记
            config["force_refresh"] = int(time.time())
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            print("✅ 更新翻译插件配置")
            
        except Exception as e:
            print(f"⚠️ 无法更新配置文件: {e}")
    
    print("\n🎉 刷新完成!")
    print("\n📋 接下来的步骤:")
    print("1. 完全关闭ComfyUI")
    print("2. 如果使用浏览器，清除浏览器缓存")
    print("3. 重新启动ComfyUI")
    print("4. 检查ComfyUI界面语言设置是否为中文")
    print("5. 如果仍然不生效，尝试重新安装ComfyUI-DD-Translation插件")

if __name__ == "__main__":
    force_refresh_translation()