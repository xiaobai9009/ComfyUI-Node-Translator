"""修复翻译文件中的类型名"""
import json
import os
import sys

def fix_translation_file(file_path):
    """修复翻译文件中的类型名
    
    Args:
        file_path: 翻译文件路径
    """
    # 类型名到中文的映射
    type_to_chinese = {
        'IMAGE': '图像',
        'MASK': '遮罩',
        'MODEL': '模型',
        'LATENT': '潜在空间',
        'VAE': 'VAE',
        'CLIP': 'CLIP',
        'CONDITIONING': '条件',
        'CONTROL_NET': '控制网络',
        'COMBO': '选项',
        'INT': '整数',
        'FLOAT': '浮点数',
        'STRING': '字符串',
        'BOOLEAN': '布尔值'
    }
    
    print(f"\n处理文件: {file_path}")
    print("=" * 80)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"错误: 无法读取文件: {str(e)}")
        return False
    
    fixed_count = 0
    for node_name, node_info in data.items():
        for section in ['inputs', 'widgets', 'outputs']:
            if section in node_info:
                for key, value in node_info[section].items():
                    if value in type_to_chinese:
                        old_value = value
                        new_value = type_to_chinese[value]
                        node_info[section][key] = new_value
                        fixed_count += 1
                        print(f"✓ {node_name}.{section}.{key}: {old_value} → {new_value}")
    
    if fixed_count > 0:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"\n成功修复 {fixed_count} 个参数")
            print(f"文件已保存: {file_path}")
            return True
        except Exception as e:
            print(f"错误: 无法保存文件: {str(e)}")
            return False
    else:
        print("无需修复")
        return False

def main():
    """主函数"""
    print("=" * 80)
    print("翻译文件修复工具")
    print("=" * 80)
    
    # 默认文件路径
    default_path = r"D:\AIAIAI\99_ComfyUI_Mie_PyTorch2.8.0\ComfyUI\custom_nodes\ComfyUI-DD-Translation\zh-CN\Nodes\ComfyUI-SeedVR2_VideoUpscaler.json"
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = default_path
    
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        print(f"\n使用方法: python fix_translation.py <文件路径>")
        return
    
    success = fix_translation_file(file_path)
    
    print("\n" + "=" * 80)
    if success:
        print("修复完成！")
        print("\n请重启ComfyUI以加载更新后的翻译文件。")
    else:
        print("处理完成")
    print("=" * 80)

if __name__ == "__main__":
    main()
