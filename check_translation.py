#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ComfyUI翻译文件检查工具
用于验证翻译文件格式和路径是否正确
"""

import json
import os
import sys

def check_translation_file(file_path):
    """检查翻译文件"""
    print(f"检查翻译文件: {file_path}")
    
    # 1. 检查文件是否存在
    if not os.path.exists(file_path):
        print("❌ 文件不存在")
        return False
    
    print("✅ 文件存在")
    
    # 2. 检查文件大小
    file_size = os.path.getsize(file_path)
    print(f"📁 文件大小: {file_size} 字节")
    
    # 3. 检查JSON格式
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print("✅ JSON格式正确")
    except json.JSONDecodeError as e:
        print(f"❌ JSON格式错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return False
    
    # 4. 检查数据结构
    if not isinstance(data, dict):
        print("❌ 根节点应该是对象")
        return False
    
    print("✅ 数据结构正确")
    
    # 5. 统计节点数量
    node_count = len(data)
    print(f"📊 节点数量: {node_count}")
    
    # 6. 检查节点结构
    valid_nodes = 0
    for node_name, node_data in data.items():
        if isinstance(node_data, dict):
            if 'title' in node_data:
                valid_nodes += 1
    
    print(f"📊 有效节点: {valid_nodes}/{node_count}")
    
    # 7. 显示前几个节点
    print("\n📋 前5个节点:")
    for i, (node_name, node_data) in enumerate(data.items()):
        if i >= 5:
            break
        title = node_data.get('title', '无标题') if isinstance(node_data, dict) else '格式错误'
        print(f"  {i+1}. {node_name}: {title}")
    
    return True

def check_comfyui_structure(comfyui_path):
    """检查ComfyUI目录结构"""
    print(f"\n检查ComfyUI目录结构: {comfyui_path}")
    
    # 检查主要目录
    required_dirs = [
        "custom_nodes",
        "custom_nodes/ComfyUI-DD-Translation",
        "custom_nodes/ComfyUI-DD-Translation/zh-CN",
        "custom_nodes/ComfyUI-DD-Translation/zh-CN/Nodes"
    ]
    
    for dir_path in required_dirs:
        full_path = os.path.join(comfyui_path, dir_path)
        if os.path.exists(full_path):
            print(f"✅ {dir_path}")
        else:
            print(f"❌ {dir_path} (不存在)")
    
    # 检查翻译插件是否存在
    translation_plugin = os.path.join(comfyui_path, "custom_nodes", "ComfyUI-DD-Translation")
    if os.path.exists(translation_plugin):
        print(f"\n📁 翻译插件目录内容:")
        try:
            for item in os.listdir(translation_plugin):
                item_path = os.path.join(translation_plugin, item)
                if os.path.isdir(item_path):
                    print(f"  📁 {item}/")
                else:
                    print(f"  📄 {item}")
        except Exception as e:
            print(f"❌ 无法读取目录: {e}")

def main():
    """主函数"""
    print("ComfyUI翻译文件检查工具")
    print("=" * 50)
    
    # 默认路径
    default_comfyui_path = r"D:\AIAIAI\1_ComfyUI_Mie_V6.01\ComfyUI"
    default_translation_file = os.path.join(
        default_comfyui_path,
        "custom_nodes",
        "ComfyUI-DD-Translation",
        "zh-CN",
        "Nodes",
        "ComfyUI-MieNodes.json"
    )
    
    # 检查ComfyUI目录结构
    if os.path.exists(default_comfyui_path):
        check_comfyui_structure(default_comfyui_path)
    else:
        print(f"❌ ComfyUI目录不存在: {default_comfyui_path}")
    
    print("\n" + "=" * 50)
    
    # 检查翻译文件
    if os.path.exists(default_translation_file):
        check_translation_file(default_translation_file)
    else:
        print(f"❌ 翻译文件不存在: {default_translation_file}")
    
    print("\n" + "=" * 50)
    print("检查完成!")
    
    # 提供解决建议
    print("\n💡 解决建议:")
    print("1. 确认ComfyUI-DD-Translation插件已正确安装")
    print("2. 确认ComfyUI语言设置为中文")
    print("3. 完全重启ComfyUI")
    print("4. 清除浏览器缓存")
    print("5. 检查插件文件夹名称是否与翻译文件名匹配")

if __name__ == "__main__":
    main()