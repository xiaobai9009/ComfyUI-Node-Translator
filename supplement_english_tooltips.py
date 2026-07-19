"""补译翻译 JSON 中仍为英文的 tooltips

扫描指定文件夹下所有 JSON，检测 tooltips 中含英文的项，
调用 LLM 一次性补译为中文。**保留所有其他字段不动**。

用法:
    python supplement_english_tooltips.py <plugin_json_or_folder> [--api-key XXX] [--model XXX]
"""
import os
import sys
import json
import re
import argparse
import glob
from typing import Dict, List, Tuple

# 兼容直接运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def has_english(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return latin > len(text) * 0.4

def collect_english_tooltips(data: dict) -> List[Tuple[str, str, str]]:
    """收集所有需要补译的 tooltips

    Returns:
        List of (node_name, key, english_tooltip)
    """
    items = []
    for node_name, node_info in data.items():
        if not isinstance(node_info, dict):
            continue
        tooltips = node_info.get('tooltips', {})
        if not isinstance(tooltips, dict):
            continue
        # 获取上下文：widgets 和 inputs 的中文名
        widgets = node_info.get('widgets', {}) or {}
        inputs = node_info.get('inputs', {}) or {}
        for k, v in tooltips.items():
            if has_english(v):
                # 用中文 label 做上下文
                display = widgets.get(k) or inputs.get(k) or k
                items.append((node_name, k, str(v), str(display)))
    return items

def batch_translate_with_llm(items: List[Tuple[str, str, str, str]], api_key: str, model: str, base_url: str = None) -> Dict[Tuple[str, str], str]:
    """用 LLM 批量翻译英文 tooltips

    Args:
        items: [(node_name, key, english_tooltip, display_name), ...]
    Returns:
        {(node_name, key): chinese_tooltip}
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("需要 openai 库: pip install openai")
        return {}

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)

    system_prompt = (
        "你是一个专业的 ComfyUI 节点翻译助手。请将提供的英文 tooltip 简洁准确地翻译为中文，"
        "保持专业术语（如 VAE、CLIP、LoRA）原样不译。\n"
        "返回严格的 JSON 格式: {\"key1\": \"翻译1\", \"key2\": \"翻译2\"}"
    )

    # 按 20 个一组批量翻译
    result = {}
    batch_size = 20
    for i in range(0, len(items), batch_size):
        chunk = items[i:i+batch_size]
        # 用 key 作为 JSON 键（避免 node_name 影响）
        # 同一 node + 同一 key 即可定位
        lines = []
        local_key_map = {}  # local_key -> (node_name, key)
        for idx, (node, k, en_tip, display) in enumerate(chunk):
            local_key = f"k{idx}"
            local_key_map[local_key] = (node, k)
            lines.append(f"参数显示名: {display}\ntooltip: {en_tip}")
        user_prompt = (
            "请将以下每条 tooltip 翻译为简洁的中文（不超过 80 字）。"
            "返回 JSON 格式: " + json.dumps({local_key: "翻译" for local_key in local_key_map}, ensure_ascii=False) + "\n\n"
            + "\n\n---\n\n".join(lines)
        )

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                max_tokens=2048,
                timeout=120
            )
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
            data = json.loads(text)
            for local_key, translated in data.items():
                if local_key in local_key_map:
                    node, k = local_key_map[local_key]
                    result[(node, k)] = str(translated).strip()
        except Exception as e:
            print(f"  批次 {i//batch_size + 1} 翻译失败: {e}")
            continue

    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', help='JSON 文件或包含 JSON 的文件夹')
    ap.add_argument('--api-key', help='LLM API key（默认从 config.json 读取）')
    ap.add_argument('--model', default='doubao-1-5-pro-32k-250115', help='模型名')
    ap.add_argument('--base-url', help='API base URL')
    ap.add_argument('--dry-run', action='store_true', help='只扫描，不修改')
    args = ap.parse_args()

    path = args.path
    if not os.path.exists(path):
        print(f"路径不存在: {path}")
        return 1

    # 收集所有 JSON
    if os.path.isfile(path):
        files = [path]
    else:
        files = glob.glob(os.path.join(path, '*.json'))

    if not files:
        print(f"未找到 JSON 文件")
        return 1

    # 1. 收集所有英文 tooltips
    all_items = []
    file_data = {}
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
        except Exception as e:
            print(f"读取 {f} 失败: {e}")
            continue
        items = collect_english_tooltips(data)
        all_items.extend([(node, key, tip, disp) for node, key, tip, disp in items])
        file_data[f] = data

    print(f"扫描到 {len(all_items)} 个英文 tooltips 待补译")

    if args.dry_run or not all_items:
        if not all_items:
            print("无需翻译")
        return 0

    # 2. 获取 API key
    api_key = args.api_key
    base_url = args.base_url
    if not api_key:
        cfg_path = 'config.json'
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            api_key = cfg.get('api_key', '')
            base_url = base_url or cfg.get('base_url', '')

    if not api_key:
        print("未提供 API key，使用 --api-key 或在 config.json 中配置")
        return 1

    print(f"使用模型: {args.model}")
    print(f"开始批量翻译...")

    # 3. 翻译
    translations = batch_translate_with_llm(all_items, api_key, args.model, base_url)
    print(f"成功翻译: {len(translations)} / {len(all_items)}")

    # 4. 写回
    fixed_count = 0
    for f, data in file_data.items():
        for node_name, node_info in data.items():
            if not isinstance(node_info, dict):
                continue
            tooltips = node_info.get('tooltips', {})
            if not isinstance(tooltips, dict):
                continue
            changed = False
            for k in list(tooltips.keys()):
                if (node_name, k) in translations:
                    new_tip = translations[(node_name, k)]
                    if new_tip and not has_english(new_tip):
                        tooltips[k] = new_tip
                        changed = True
                        fixed_count += 1
            if changed:
                # 移除警告标记
                if '_warnings' in node_info and 'tooltips_has_english' in node_info['_warnings']:
                    node_info['_warnings'] = [w for w in node_info['_warnings'] if w != 'tooltips_has_english']
        with open(f, 'w', encoding='utf-8') as fp:
            json.dump(data, fp, ensure_ascii=False, indent=4)
        print(f"  -> {f} 已更新")

    print(f"\n总计补译: {fixed_count} 条 tooltip")
    return 0

if __name__ == '__main__':
    sys.exit(main())
