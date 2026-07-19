"""修复已生成的翻译 JSON 文件，清理 inputs 中混入的 tooltip 文本

对每个节点：
  - inputs 的 value 如果包含标点（逗号/句号）或长度 > 30，强制还原为 key 自身
  - tooltips 中如果有英文内容（>50% 拉丁字母），标记为"待重新翻译"

用法:
    python fix_corrupted_translations.py <plugin_folder> [--dry-run]
    python fix_corrupted_translations.py "d:\\AIAIAI\\29_ComfyUI-Node-Translator\\output" --dry-run
"""
import os
import sys
import json
import re
import argparse

# 标识 inputs value 是"长文本"或"含标点句子"的条件
LONG_TEXT_THRESHOLD = 30  # 字符数
SENTENCE_PUNCT = re.compile(r'[，。；？！,.;?!]')

def is_corrupted_value(value: str, key: str) -> bool:
    """判断 inputs value 是否是混入的 tooltip 长文本"""
    if not isinstance(value, str):
        return False
    if value == key:
        return False
    if len(value) > LONG_TEXT_THRESHOLD:
        return True
    if SENTENCE_PUNCT.search(value):
        # 含标点但不长 -> 仍可能是短句，也还原
        return True
    return False

def has_english(text: str) -> bool:
    """判断文本是否主要是英文（占 50% 以上拉丁字符）"""
    if not isinstance(text, str) or not text:
        return False
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return latin > len(text) * 0.4

def fix_node(node_info: dict) -> dict:
    """修复单个节点"""
    fixed = dict(node_info)

    # 1. 修复 inputs
    if isinstance(fixed.get('inputs'), dict):
        fixed_inputs = {}
        for k, v in fixed['inputs'].items():
            if is_corrupted_value(v, k):
                fixed_inputs[k] = k  # 还原为 key
            else:
                fixed_inputs[k] = v
        fixed['inputs'] = fixed_inputs

    # 2. 修复 widgets（widgets 的 value 是用户可编辑参数标签，长度不应超过 30）
    if isinstance(fixed.get('widgets'), dict):
        fixed_widgets = {}
        for k, v in fixed['widgets'].items():
            if isinstance(v, str) and len(v) > 50:
                # 太长，可能是 tooltip 混入
                fixed_widgets[k] = k
            else:
                fixed_widgets[k] = v
        fixed['widgets'] = fixed_widgets

    # 3. 标记 tooltips 中含英文的项（这些需要重新翻译）
    if isinstance(fixed.get('tooltips'), dict):
        for k, v in fixed['tooltips'].items():
            if has_english(v):
                # 暂不修改值，但在 _warnings 中标记
                warnings = fixed.setdefault('_warnings', [])
                if 'tooltips_has_english' not in warnings:
                    warnings.append('tooltips_has_english')

    return fixed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', help='要修复的翻译 JSON 所在文件夹')
    ap.add_argument('--dry-run', action='store_true', help='只统计问题，不修改文件')
    args = ap.parse_args()

    folder = args.folder
    if not os.path.isdir(folder):
        print(f"目录不存在: {folder}")
        return 1

    json_files = [f for f in os.listdir(folder) if f.endswith('.json')]
    if not json_files:
        print(f"未找到 JSON 文件")
        return 1

    total_nodes = 0
    total_fixed_inputs = 0
    total_english_tooltips = 0
    nodes_need_retranslate = []

    for jf in json_files:
        path = os.path.join(folder, jf)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"  读取失败: {path}: {e}")
            continue

        new_data = {}
        file_fixed_inputs = 0
        file_english_tips = 0

        for node_name, node_info in data.items():
            total_nodes += 1
            if not isinstance(node_info, dict):
                new_data[node_name] = node_info
                continue

            # 统计
            if isinstance(node_info.get('inputs'), dict):
                for k, v in node_info['inputs'].items():
                    if is_corrupted_value(v, k):
                        file_fixed_inputs += 1
                        total_fixed_inputs += 1
            if isinstance(node_info.get('tooltips'), dict):
                for k, v in node_info['tooltips'].items():
                    if has_english(v):
                        file_english_tips += 1
                        total_english_tooltips += 1
                        nodes_need_retranslate.append(f"{jf}::{node_name}::{k}")

            new_data[node_name] = fix_node(node_info)

        if file_fixed_inputs > 0 or file_english_tips > 0:
            print(f"  {jf}: 修复 {file_fixed_inputs} 个 inputs, {file_english_tips} 个英文 tooltips")

        if not args.dry_run and (file_fixed_inputs > 0):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=4)
            print(f"    -> 已写入")

    print()
    print(f"=== 总计 ===")
    print(f"扫描节点: {total_nodes}")
    print(f"inputs 需还原: {total_fixed_inputs}")
    print(f"英文 tooltips: {total_english_tooltips}")
    if not args.dry_run:
        print(f"已自动修复 inputs 混入问题")
        if total_english_tooltips > 0:
            print(f"⚠ tooltips 仍含英文 {total_english_tooltips} 处，需要重新翻译这些节点")
    else:
        print("(干运行模式，未修改文件)")
    return 0

if __name__ == '__main__':
    sys.exit(main())
