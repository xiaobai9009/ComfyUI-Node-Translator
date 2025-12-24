import os
from typing import Dict, List, Optional
from openai import OpenAI
import requests
import json
import re
import time
import random
from .prompts import PromptTemplate  # 导入提示词模板
from .translation_config import TranslationConfig
import glob
from .file_utils import FileUtils

class Translator:
    """节点翻译器类
    
    负责调用火山引擎 API 将节点信息翻译成中文
    """
    
    def __init__(self, api_key: str, model_id: str, base_url: str = "https://ark.cn-beijing.volces.com/api/v3", temperature: float = 0.3, top_p: float = 0.95, error_policy: Optional[Dict] = None, fallback_models: Optional[List[str]] = None, service_name: Optional[str] = None):
        """初始化翻译器
        
        Args:
            api_key: API 密钥
            model_id: 模型 ID
            base_url: API 基础 URL
        """
        self.model_id = model_id
        
        # 获取程序根目录
        self.base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 初始化输出目录（仅主输出目录）
        self.dirs = FileUtils.init_output_dirs(self.base_path)
        
        # 从提示词模板获取系统提示词
        self.system_prompt = PromptTemplate.get_translator_prompt()
        
        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        
        self.work_dir = None
        self.current_plugin_path = None
        
        self.total_prompt_tokens = 0    # 输入 tokens
        self.total_completion_tokens = 0 # 输出 tokens
        self.total_tokens = 0           # 总 tokens
        self.temperature = temperature
        self.top_p = top_p
        self.error_policy = error_policy or {}
        self.fallback_models = fallback_models or []
        self.service_name = service_name or ""
        self.strategy_log: List[Dict] = []
        self.only_tooltips = False

    def test_connection(self) -> bool:
        try:
            system_prompt = PromptTemplate.get_test_prompt()
            mid = str(self.model_id or "").lower()
            use_single_user = ("google/" in mid) or ("gemma" in mid) or ("gemini" in mid)
            if use_single_user:
                messages = [
                    {"role": "user", "content": f"{system_prompt}\n\n你好，请回复一句话。"}
                ]
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "你好，请回复一句话。"}
                ]
            completion = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                temperature=self.temperature,
                top_p=self.top_p,
                stream=False,
                max_tokens=100,
                presence_penalty=0,
                frequency_penalty=0
            )
            
            # 检查响应
            if completion.choices and completion.choices[0].message:
                return True
            else:
                raise Exception("API 响应格式不正确")
                
        except Exception as e:
            error_msg = str(e)
            if "AccountOverdueError" in error_msg:
                raise Exception("账户余额不足，请充值后重试")
            elif "InvalidApiKeyError" in error_msg:
                raise Exception("API 密钥无效")
            elif "ModelNotFoundError" in error_msg:
                raise Exception("模型 ID 无效")
            else:
                raise Exception(f"API 连接测试失败: {error_msg}")

    def _extract_json_from_response(self, response_text: str) -> Dict:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        match = re.search(r'```(?:json)?\s*(.*?)\s*```', response_text, re.DOTALL)
        if match:
            block = match.group(1)
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                repaired = re.sub(r',\s*(?=[}\]])', '', block)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

        start = response_text.find('{')
        if start != -1:
            candidate = response_text[start:]
            end_balanced = self._find_balanced_end(candidate, 0)
            if end_balanced != -1:
                json_str = candidate[:end_balanced+1]
            else:
                json_str = self._close_unbalanced(candidate)
            json_str = re.sub(r',\s*(?=[}\]])', '', json_str)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        raise Exception(f"无法从响应中提取有效的 JSON 数据: {response_text[:100]}...")

    def _find_balanced_end(self, text: str, start: int = 0) -> int:
        in_str = False
        escape = False
        depth = 0
        last_end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == '{' or ch == '[':
                    depth += 1
                elif ch == '}' or ch == ']':
                    if depth > 0:
                        depth -= 1
                if depth == 0 and (ch == '}' or ch == ']'):
                    last_end = i
        return last_end

    def _close_unbalanced(self, text: str) -> str:
        stack = []
        in_str = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == '{' or ch == '[':
                    stack.append(ch)
                elif ch == '}' or ch == ']':
                    if stack:
                        stack.pop()
        closers = ''.join('}' if c == '{' else ']' for c in reversed(stack))
        return text + closers

    def translate_batch(self, batch_nodes: Dict) -> Dict:
        """翻译一批节点"""
        try:
            mid = str(self.model_id or "").lower()
            use_single_user = ("google/" in mid) or ("gemma" in mid) or ("gemini" in mid)
            if use_single_user:
                messages = [
                    {"role": "user", "content": f"{self.system_prompt}\n\n请翻译以下节点信息:\n{json.dumps(batch_nodes, ensure_ascii=False)}"}
                ]
            else:
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": json.dumps(batch_nodes, ensure_ascii=False)}
                ]
            attempts = 0
            strategy = (self.error_policy.get("strategy") or "exponential").lower()
            max_retries = int(self.error_policy.get("max_retries", 5))
            base_delay = int(self.error_policy.get("base_delay_sec", 2))
            delay = base_delay
            while True:
                try:
                    completion = self.client.chat.completions.create(
                        model=self.model_id,
                        messages=messages,
                        temperature=self.temperature,
                        top_p=self.top_p,
                        stream=False,
                        max_tokens=4096,
                        presence_penalty=0,
                        frequency_penalty=0,
                        stop=None,
                        user="comfyui-translator"
                    )
                    break
                except Exception as e:
                    msg = str(e)
                    mlow = msg.lower()
                    if ("developer instruction is not enabled" in msg or "developer instruction" in mlow) and not use_single_user:
                        messages = [
                            {"role": "user", "content": f"{self.system_prompt}\n\n请翻译以下节点信息:\n{json.dumps(batch_nodes, ensure_ascii=False)}"}
                        ]
                        use_single_user = True
                        self.strategy_log.append({"type": "switch_single_user", "model": self.model_id})
                        continue
                    if ("429" in mlow) or ("rate limit" in mlow) or ("rate-limited" in mlow):
                        self.strategy_log.append({"type": "rate_limit_retry", "attempt": attempts + 1, "delay_sec": delay})
                        if attempts >= max_retries:
                            raise Exception("Error code: 429 - 请求被限流或配额不足，重试已耗尽。建议降低并发或更换备用模型")
                        if strategy == "fixed":
                            pass
                        else:
                            delay = min(delay * 2, 60)
                        if hasattr(time, "sleep"):
                            if hasattr(self, "strategy_log"):
                                pass
                            time.sleep(delay + random.uniform(0, 0.5))
                        attempts += 1
                        continue
                    raise
            
            # 解析返回结果
            response_text = completion.choices[0].message.content
            
            try:
                translated_nodes = self._extract_json_from_response(response_text)
                return translated_nodes
            except Exception as e:
                raise Exception(f"JSON解析失败: {str(e)}")
            
        except Exception as e:
            raise Exception(f"翻译失败: {str(e)}")

    def translate_nodes(self, nodes_info: Dict, folder_path: str, batch_size: int = 6, 
                       update_progress=None, temp_dir: str = None, rounds: int = 2) -> Dict:
        temp_files = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        try:
            plugin_name = os.path.basename(folder_path.rstrip(os.path.sep))
            work_dir = temp_dir if temp_dir else os.path.join(self.base_path, "output", plugin_name, "_temp")
            os.makedirs(work_dir, exist_ok=True)
            self.current_plugin_path = folder_path
            original_file = os.path.join(work_dir, "nodes_to_translate.tmp.json")
            FileUtils.save_json(nodes_info, original_file)
            temp_files.append(original_file)
            if update_progress:
                update_progress(0, f"[准备] 保存原始节点信息到: {original_file}")
            all_translated_nodes = {}
            node_items = list(nodes_info.items())
            total_batches = (len(node_items) + batch_size - 1) // batch_size
            for batch_idx in range(total_batches):
                start_idx = batch_idx * batch_size
                end_idx = min((batch_idx + 1) * batch_size, len(node_items))
                current_batch = dict(node_items[start_idx:end_idx])
                if update_progress:
                    progress = int((batch_idx / total_batches) * 100)
                    node_names = list(current_batch.keys())
                    update_progress(progress, f"[翻译] 第 {batch_idx + 1}/{total_batches} 批: {', '.join(node_names)}")
                try:
                    full_batch_data = {}
                    for node_name, node_data in current_batch.items():
                        full_batch_data[node_name] = {
                            "_class_name": node_data.get("_class_name", ""),
                            "_mapped_name": node_data.get("_mapped_name", ""),
                            "title": node_data.get("title", ""),
                            "inputs": node_data.get("inputs", {}),
                            "widgets": node_data.get("widgets", {}),
                            "outputs": node_data.get("outputs", {}),
                            "tooltips": node_data.get("tooltips", {}),
                            "_source_file": node_data.get("_source_file", "")
                        }
                    batch_translated = self._translate_with_fallback(full_batch_data, update_progress, progress)
                    if update_progress:
                        update_progress(progress, "[验证] 正在严格验证翻译结果...")
                    batch_corrected = self._strict_validate_and_correct_batch(
                        full_batch_data,
                        batch_translated,
                        update_progress,
                        progress
                    )
                    batch_file = os.path.join(work_dir, f"batch_{batch_idx + 1}_translated.tmp.json")
                    FileUtils.save_json(batch_corrected, batch_file)
                    temp_files.append(batch_file)
                    all_translated_nodes.update(batch_corrected)
                    if update_progress:
                        update_progress(progress, f"[完成] 批次 {batch_idx + 1} 的处理已完成")
                except Exception as e:
                    if update_progress:
                        update_progress(progress, f"[错误] 批次 {batch_idx + 1} 处理失败: {str(e)}")
                    raise
            final_file = os.path.join(self.base_path, "output", plugin_name, f"{plugin_name}.json")
            if update_progress:
                update_progress(95, "[验证] 进行最终验证...")
            final_corrected = self._final_validation(
                nodes_info,
                all_translated_nodes,
                update_progress
            )
            if getattr(self, "only_tooltips", False):
                tooltip_only = {}
                for node_name, node_info in nodes_info.items():
                    base = final_corrected.get(node_name, node_info)
                    tooltip_only[node_name] = {
                        "_class_name": node_info.get("_class_name", ""),
                        "_mapped_name": node_info.get("_mapped_name", ""),
                        "title": node_info.get("title", ""),
                        "inputs": node_info.get("inputs", {}),
                        "widgets": node_info.get("widgets", {}),
                        "outputs": node_info.get("outputs", {}),
                        "tooltips": base.get("tooltips", node_info.get("tooltips", {})),
                        "_source_file": node_info.get("_source_file", "")
                    }
                final_corrected = tooltip_only
            FileUtils.save_json(final_corrected, final_file)
            try:
                missing_stats = []
                consecutive_no_improve = 0
                max_rounds = max(1, min(5, int(rounds)))
                for r in range(2, max_rounds + 1):
                    if update_progress:
                        update_progress(96, f"[二次筛查] 第 {r} 轮补漏检测")
                    missing_batch, total_missing = self._collect_missing(nodes_info, final_corrected)
                    if total_missing == 0:
                        if update_progress:
                            update_progress(96, "[二次筛查] 无遗漏，提前结束")
                        break
                    tmp_missing_file = os.path.join(work_dir, f"round_{r}_missing.tmp.json")
                    FileUtils.save_json(missing_batch, tmp_missing_file)
                    translated_missing = self._translate_batch(missing_batch, update_progress, 96)
                    before_cov = self._coverage(final_corrected)
                    self._merge_translations(final_corrected, translated_missing)
                    after_cov = self._coverage(final_corrected)
                    fixed = max(0, int((after_cov["covered_keys"] - before_cov["covered_keys"])) )
                    missing_stats.append({"round": r, "found": total_missing, "fixed": fixed, "coverage": after_cov["coverage"]})
                    tmp_round_file = os.path.join(work_dir, f"round_{r}_merged.tmp.json")
                    FileUtils.save_json(final_corrected, tmp_round_file)
                    if update_progress:
                        update_progress(97, f"[统计] 第 {r} 轮：遗漏 {total_missing}，修复 {fixed}，覆盖率 {after_cov['coverage']:.2f}%")
                    if fixed == 0:
                        consecutive_no_improve += 1
                    else:
                        consecutive_no_improve = 0
                    if consecutive_no_improve >= 1:
                        if update_progress:
                            update_progress(97, "[终止] 连续轮次无改进，结束补漏流程")
                        break
                coverage_report = self._coverage(final_corrected)
                report_file = os.path.join(work_dir, "coverage_report.tmp.json")
                FileUtils.save_json({"rounds": missing_stats, **coverage_report}, report_file)
            except Exception as e:
                if update_progress:
                    update_progress(97, f"[警告] 多轮筛查出现错误: {str(e)}")
                try:
                    err_file = os.path.join(self.base_path, "output", plugin_name, "errors.log")
                    with open(err_file, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} multi-round error: {str(e)}\n")
                except Exception:
                    pass
            try:
                comfyui_file = FileUtils.save_to_comfyui_translation(
                    folder_path, 
                    final_corrected, 
                    plugin_name
                )
                if update_progress:
                    update_progress(98, f"[保存] 已保存到ComfyUI翻译目录: {comfyui_file}")
            except Exception as e:
                if update_progress:
                    update_progress(98, f"[警告] 保存到ComfyUI翻译目录失败: {str(e)}")
            self._cleanup_temp_files(temp_files, update_progress)
            try:
                import shutil
                if os.path.isdir(work_dir):
                    shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
            if update_progress:
                prompt_cost = (self.total_prompt_tokens / 1000) * 0.0008
                completion_cost = (self.total_completion_tokens / 1000) * 0.0020
                total_cost = prompt_cost + completion_cost
                update_progress(100, "[完成] 翻译和验证完成！")
                update_progress(100, f"[统计] 总计使用 {self.total_tokens} tokens:")
                update_progress(100, f"       - 输入: {self.total_prompt_tokens} tokens (¥{prompt_cost:.4f})")
                update_progress(100, f"       - 输出: {self.total_completion_tokens} tokens (¥{completion_cost:.4f})")
                update_progress(100, f"[费用] 预估总费用（请以实际为准）: ¥{total_cost:.4f}")
            return final_corrected
        except Exception as e:
            self._cleanup_temp_files(temp_files, update_progress)
            try:
                import shutil
                if work_dir and os.path.isdir(work_dir):
                    shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
            error_msg = str(e)
            if "AccountOverdueError" in error_msg:
                if update_progress:
                    update_progress(-1, "[错误] 账户余额不足，请充值后重试")
            elif "InvalidApiKeyError" in error_msg:
                if update_progress:
                    update_progress(-1, "[错误] API 密钥无效")
            elif "ModelNotFoundError" in error_msg:
                if update_progress:
                    update_progress(-1, "[错误] 模型 ID 无效")
            else:
                if update_progress:
                    update_progress(-1, f"[错误] 翻译过程出错: {error_msg}")
            raise

    def _translate_with_fallback(self, full_batch_data: Dict, update_progress=None, progress: int = 0, _depth: int = 0) -> Dict:
        try:
            return self._translate_batch(full_batch_data, update_progress, progress)
        except Exception as e:
            items = list(full_batch_data.items())
            if _depth >= 2 or len(items) <= 1:
                raise
            mid = len(items) // 2
            left = dict(items[:mid])
            right = dict(items[mid:])
            self.strategy_log.append({"type": "split_batch", "depth": _depth + 1, "left": len(left), "right": len(right)})
            if update_progress:
                update_progress(progress, f"[策略] 批次拆分为 {len(left)} + {len(right)}")
            result_left = self._translate_with_fallback(left, update_progress, progress, _depth + 1)
            result_right = self._translate_with_fallback(right, update_progress, progress, _depth + 1)
            merged = {}
            merged.update(result_left)
            merged.update(result_right)
            return merged
            
    def _strict_validate_and_correct_batch(self, original_batch: Dict, translated_batch: Dict,
                                        update_progress=None, progress: int = 0) -> Dict:
        """严格验证和修正单个批次的翻译结果"""
        corrected_batch = {}
        
        for node_name, node_info in original_batch.items():
            if node_name not in translated_batch:
                if update_progress:
                    update_progress(progress, f"[严格修正] 节点 {node_name} 未翻译，使用原始数据")
                corrected_batch[node_name] = node_info
                continue
            
            translated_info = translated_batch[node_name]
            corrected_node = {
                "_class_name": node_info.get("_class_name", ""),
                "_mapped_name": node_info.get("_mapped_name", ""),
                "title": translated_info.get("title", node_info.get("title", "")),
                "inputs": {},
                "widgets": {},
                "outputs": {},
                "tooltips": {},
                "_source_file": node_info.get("_source_file", "")
            }
            
            # 严格验证 inputs, widgets, outputs
            for section in ["inputs", "widgets", "outputs"]:
                orig_section = node_info.get(section, {})
                trans_section = translated_info.get(section, {})
                
                # 确保所有原始键都存在
                for key, orig_value in orig_section.items():
                    # 1. 检查是否是保留类型
                    if key.upper() in TranslationConfig.PRESERVED_TYPES:
                        corrected_node[section][key] = key.upper()
                        if update_progress:
                            update_progress(progress, f"[保留] 节点 {node_name} 的 {section}.{key} 是保留类型")
                        continue
                    
                    # 2. 检查是否有标准翻译
                    if key.lower() in TranslationConfig.COMMON_TRANSLATIONS:
                        corrected_node[section][key] = TranslationConfig.COMMON_TRANSLATIONS[key.lower()]
                        if update_progress:
                            update_progress(progress, f"[标准] 节点 {node_name} 的 {section}.{key} 使用标准翻译")
                        continue
                    
                    # 3. 检查翻译结果中是否有对应项
                    if key in trans_section:
                        trans_value = trans_section[key]
                        # 验证翻译值是否合理
                        if self._is_valid_translation(key, trans_value):
                            corrected_node[section][key] = trans_value
                            if update_progress:
                                update_progress(progress, f"[使用] 节点 {node_name} 的 {section}.{key} 使用翻译值")
                        else:
                            corrected_node[section][key] = key
                            if update_progress:
                                update_progress(progress, f"[无效] 节点 {node_name} 的 {section}.{key} 翻译值无效，使用原值")
                    else:
                        corrected_node[section][key] = key
                        if update_progress:
                            update_progress(progress, f"[缺失] 节点 {node_name} 的 {section}.{key} 缺少翻译，使用原值")

            # 特殊处理 tooltips - 即使原版没有，也要尝试从翻译结果中获取
            # tooltips 的目标键集合是 inputs 和 widgets 的所有键
            target_keys = set(node_info.get("inputs", {}).keys()) | set(node_info.get("widgets", {}).keys())
            # 加上原本就有的 tooltips 键
            target_keys |= set(node_info.get("tooltips", {}).keys())
            
            trans_tooltips = translated_info.get("tooltips", {})
            
            for key in target_keys:
                if key in trans_tooltips:
                    trans_value = trans_tooltips[key]
                    if self._is_valid_translation(key, trans_value):
                        corrected_node["tooltips"][key] = trans_value
                        # if update_progress:
                        #     update_progress(progress, f"[Tooltip] 节点 {node_name} 的 {key} 获取到 tooltip")
                elif key in node_info.get("tooltips", {}):
                     # 如果翻译里没有，但原版有，保留原版（虽然原版可能是英文，但总比没有好，或者视为空）
                     # 但根据需求，我们希望是中文。如果原版是英文，这里保留原版会导致英文 tooltip。
                     # 用户希望生成中文。如果LLM没生成，这里保留原版是可以的，后续可以再次翻译。
                     corrected_node["tooltips"][key] = node_info["tooltips"][key]
            
            corrected_batch[node_name] = corrected_node
        
        return corrected_batch

    def _final_validation(self, original_nodes: Dict, translated_nodes: Dict, 
                         update_progress=None) -> Dict:
        """最终验证，确保所有节点都被正确翻译"""
        final_nodes = {}
        
        # 检查所有原始节点是否都被翻译
        for node_name, node_info in original_nodes.items():
            if node_name not in translated_nodes:
                if update_progress:
                    update_progress(95, f"[修正] 节点 {node_name} 未翻译，使用原始数据")
                final_nodes[node_name] = node_info
                continue
            
            translated_info = translated_nodes[node_name]
            
            # 验证必要字段
            if not all(field in translated_info for field in ["title", "inputs", "widgets", "outputs"]):
                if update_progress:
                    update_progress(96, f"[修正] 节点 {node_name} 缺少必要字段，使用原始数据")
                final_nodes[node_name] = node_info
                continue
            
            # 验证字段内容
            validated_node = {
                "_class_name": node_info.get("_class_name", ""),
                "_mapped_name": node_info.get("_mapped_name", ""),
                "title": translated_info.get("title", node_info.get("title", "")),
                "inputs": {},
                "widgets": {},
                "outputs": {},
                "tooltips": {},
                "_source_file": node_info.get("_source_file", "")
            }
            
            # 验证 inputs, widgets, outputs
            for section in ["inputs", "widgets", "outputs"]:
                orig_section = node_info.get(section, {})
                trans_section = translated_info.get(section, {})
                
                # 确保所有原始键都存在
                for key in orig_section:
                    if key in trans_section:
                        # 直接使用翻译值
                        validated_node[section][key] = trans_section[key]
                    else:
                        if update_progress:
                            update_progress(97, f"[修正] 节点 {node_name} 的 {section} 中缺少键 {key}")
                        # 如果找不到翻译，使用原始键作为值
                        validated_node[section][key] = key

            # 验证 tooltips，并为缺失项生成默认说明
            target_keys = set(node_info.get("inputs", {}).keys()) | set(node_info.get("widgets", {}).keys())
            # 同时包含翻译后的 inputs/widgets 键，避免键名变化导致 tooltip 丢失
            target_keys |= set(translated_info.get("inputs", {}).keys()) | set(translated_info.get("widgets", {}).keys())
            target_keys |= set(node_info.get("tooltips", {}).keys())
            
            trans_tooltips = translated_info.get("tooltips", {})
            for key in target_keys:
                display = (
                    validated_node["inputs"].get(key)
                    or validated_node["widgets"].get(key)
                    or translated_info.get("inputs", {}).get(key)
                    or translated_info.get("widgets", {}).get(key)
                    or key
                )
                tip = None
                if key in trans_tooltips:
                    tip = trans_tooltips[key]
                else:
                    if key in node_info.get("tooltips", {}):
                        orig_tip = node_info["tooltips"][key]
                        try:
                            tip = self._translate_doc_line_to_tooltip(str(orig_tip), str(display))
                        except Exception:
                            tip = None
                    if not tip:
                        doc_line = self._find_doc_line(self.current_plugin_path, key)
                        if doc_line:
                            try:
                                tip = self._translate_doc_line_to_tooltip(doc_line, str(display))
                            except Exception:
                                tip = None
                if not tip:
                    tip = f"该参数用于设置“{display}”"
                validated_node["tooltips"][key] = tip
            
            final_nodes[node_name] = validated_node
        
        return final_nodes

    def _find_doc_line(self, plugin_path: Optional[str], key: str) -> Optional[str]:
        if not plugin_path or not os.path.isdir(plugin_path):
            return None
        candidates = []
        for root, _, files in os.walk(plugin_path):
            for f in files:
                name = f.lower()
                if name.endswith('.md') or name.endswith('.txt'):
                    if any(k in root.lower() for k in ['doc', 'docs', 'documentation', '说明', '使用']) or any(k in name for k in ['readme', '说明', '使用', 'doc']):
                        candidates.append(os.path.join(root, f))
        key_lc = key.lower()
        for path in candidates:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                    for line in fh:
                        ln = line.strip()
                        if not ln:
                            continue
                        if key_lc in ln.lower():
                            return ln[:300]
            except Exception:
                continue
        return None

    def _translate_doc_line_to_tooltip(self, doc_line: str, display: str) -> str:
        system_prompt = PromptTemplate.get_test_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"将以下说明简洁翻译为中文Tooltip（不包含多余内容），并贴合参数“{display}”：\n{doc_line}"}
        ]
        completion = self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            temperature=self.temperature,
            max_tokens=128
        )
        text = completion.choices[0].message.content or ""
        text = text.strip()
        if not text:
            return f"该参数用于设置“{display}”"
        return text

    def _translate_batch(self, current_batch: Dict, update_progress=None, progress=0) -> Dict:
        """翻译单个批次
        
        Args:
            current_batch: 当前批次的数据
            update_progress: 进度更新回调函数
            progress: 当前进度
            
        Returns:
            Dict: 翻译后的节点信息
        """
        translated_text = ""
        
        use_single_user = False
        mid = str(self.model_id or "").lower()
        if ("google/" in mid) or ("gemma" in mid) or ("gemini" in mid):
            use_single_user = True
        if use_single_user:
            messages = [
                {"role": "user", "content": f"{self.system_prompt}\n\n请翻译以下节点信息:\n{json.dumps(current_batch, ensure_ascii=False)}"}
            ]
        else:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请翻译以下节点信息:\n{json.dumps(current_batch, ensure_ascii=False)}"}
            ]
        if update_progress:
            strat = (self.error_policy.get("strategy") or "exponential").lower()
            update_progress(progress, f"[策略] 重试策略: {strat}，最大重试: {int(self.error_policy.get('max_retries', 5))}，基础间隔: {int(self.error_policy.get('base_delay_sec', 2))}秒")
        
        attempts = 0
        delay = 2
        while True:
            try:
                completion = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=4096,
                    response_format={"type": "text"},
                    top_p=self.top_p,
                    presence_penalty=0,
                    timeout=300
                )
                break
            except Exception as e:
                msg = str(e)
                mlow = msg.lower()
                if ("developer instruction is not enabled" in msg or "developer instruction" in mlow) and not use_single_user:
                    messages = [
                        {"role": "user", "content": f"{self.system_prompt}\n\n请翻译以下节点信息:\n{json.dumps(current_batch, ensure_ascii=False)}"}
                    ]
                    use_single_user = True
                    continue
                if ("429" in mlow) or ("rate limit" in mlow) or ("rate-limited" in mlow):
                    if update_progress:
                        update_progress(progress, f"[限流] 等待 {delay}s 后重试 ({attempts + 1}/5)")
                    time.sleep(delay + random.uniform(0, 0.5))
                    attempts += 1
                    delay = min(delay * 2, 60)
                    if attempts >= 5:
                        raise Exception("请求被限流，请稍后重试，或在 OpenRouter 设置里添加集成密钥以提高配额")
                    continue
                raise
        
        # deepseek 模型可能会返回 reasoning_content
        if hasattr(completion.choices[0].message, 'reasoning_content'):
            if update_progress:
                update_progress(progress, f"DeepSeek 思考过程: {completion.choices[0].message.reasoning_content}")
        
        # 累计 tokens 使用量
        if hasattr(completion, 'usage'):
            prompt_tokens = completion.usage.prompt_tokens
            completion_tokens = completion.usage.completion_tokens
            batch_tokens = completion.usage.total_tokens
            
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_tokens += batch_tokens
            
            if update_progress:
                update_progress(progress, 
                    f"[统计] 当前批次使用 {batch_tokens} tokens "
                    f"(输入: {prompt_tokens}, 输出: {completion_tokens}), "
                    f"累计: {self.total_tokens} tokens"
                )
        
        translated_text = completion.choices[0].message.content

        # 允许短文本，只在完全为空时视为异常
        if translated_text is None or translated_text.strip() == "":
            raise Exception("API 响应为空")

        # 提取 JSON 内容
        try:
            batch_translated = self._extract_json_from_response(translated_text)
            return batch_translated
        except Exception as e:
            raise Exception(f"API 响应格式不正确: {str(e)}")

    def _validate_batch_files(self, source_file: str, translated_file: str) -> tuple[bool, Dict, str]:
        """通过三步校对修正流程处理翻译结果，并生成详细日志"""
        try:
            # 读取文件
            with open(source_file, 'r', encoding='utf-8') as f:
                original_batch = json.load(f)
            with open(translated_file, 'r', encoding='utf-8') as f:
                translated_batch = json.load(f)
            
            batch_num = os.path.basename(translated_file).split('_')[1]
            log_entries = []
            log_entries.append(f"批次 {batch_num} 校验修正日志")
            log_entries.append("=" * 50)
            
            # 第一步：建立标准映射关系
            from .translation_config import TranslationConfig
            standard_translations = {
                **TranslationConfig.COMMON_TRANSLATIONS,
                **TranslationConfig.BODY_PART_TRANSLATIONS
            }
            
            # 第二步：修正所有节点
            corrected_batch = {}
            log_entries.append("\n节点修正")
            log_entries.append("-" * 30)
            
            for node_name, node_data in original_batch.items():
                log_entries.append(f"\n节点: {node_name}")
                corrected_node = {
                    "title": translated_batch[node_name]["title"] if node_name in translated_batch else node_data["title"],
                    "inputs": {},
                    "outputs": {},
                    "widgets": {}
                }
                
                # 处理每个部分
                for section in ["inputs", "outputs", "widgets"]:
                    if section in node_data:
                        log_entries.append(f"\n{section}:")
                        
                        # 获取原始数据和翻译后的数据
                        orig_section = node_data[section]
                        trans_section = translated_batch.get(node_name, {}).get(section, {})
                        
                        # 使用原始文件中的键
                        for orig_key in orig_section.keys():
                            # 1. 如果是特殊类型值，保持不变
                            if orig_key.upper() in TranslationConfig.PRESERVED_TYPES:
                                corrected_node[section][orig_key] = orig_key.upper()
                                log_entries.append(f"保留特殊类型: {orig_key}")
                                continue
                            
                            # 2. 如果在标准映射中存在对应的翻译
                            if orig_key.lower() in standard_translations:
                                corrected_node[section][orig_key] = standard_translations[orig_key.lower()]
                                log_entries.append(f"使用标准映射: {orig_key} -> {standard_translations[orig_key.lower()]}")
                                continue
                            
                            # 3. 如果在翻译后的数据中有对应的中文值
                            if orig_key in trans_section:
                                trans_value = trans_section[orig_key]
                                # 如果值是中文，使用它
                                if any('\u4e00' <= char <= '\u9fff' for char in str(trans_value)):
                                    corrected_node[section][orig_key] = trans_value
                                    log_entries.append(f"使用翻译值: {orig_key} -> {trans_value}")
                                    continue
                        
                            # 4. 如果都没有找到合适的翻译，保持原值
                            corrected_node[section][orig_key] = orig_key
                            log_entries.append(f"保持原值: {orig_key}")
                
                corrected_batch[node_name] = corrected_node
            
            # 保存修正后的结果
            corrected_file = os.path.join(self.dirs["temp"], f"batch_{batch_num}_corrected.json")
            FileUtils.save_json(corrected_batch, corrected_file)
            
            # 保存详细日志
            log_file = os.path.join(self.dirs["logs"], 
                                  f"batch_{batch_num}_correction_log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_entries))
            
            return True, corrected_batch, '\n'.join(log_entries)
            
        except Exception as e:
            return False, translated_batch, f"修正过程出错: {str(e)}"

    def _is_valid_translation(self, english_key: str, chinese_text: str) -> bool:
        """严格检查中文文本是否是英文键的合理翻译
        
        Args:
            english_key: 英文键名
            chinese_text: 中文文本
            
        Returns:
            bool: 是否是合理的翻译
        """
        # 1. 基本检查
        if not chinese_text or not isinstance(chinese_text, str):
            return False
            
        # 2. 检查是否包含中文字符
        if not any('\u4e00' <= char <= '\u9fff' for char in chinese_text):
            return False
            
        # 3. 检查特殊字符
        if any(char in chinese_text for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']):
            return False
            
        # 4. 长度检查
        if len(chinese_text) > 3 * len(english_key) + 10:
            return False
            
        # 5. 常见翻译对照
        translations = {
            'image': {'图像', '图片'},
            'mask': {'遮罩', '掩码', '蒙版'},
            'model': {'模型'},
            'processor': {'处理器'},
            'device': {'设备'},
            'bbox': {'边界框', '边框'},
            'samples': {'样本'},
            'operation': {'操作'},
            'guide': {'引导图'},
            'radius': {'半径'},
            'epsilon': {'epsilon', 'eps'},
            'threshold': {'阈值'},
            'contrast': {'对比度'},
            'brightness': {'亮度'},
            'saturation': {'饱和度'},
            'hue': {'色调'},
            'gamma': {'伽马'},
            'input': {'输入'},
            'output': {'输出'},
            'weight': {'权重'},
            'bias': {'偏置'},
            'scale': {'缩放'},
            'factor': {'因子'},
            'strength': {'强度'},
            'value': {'值'},
            'color': {'颜色'},
            'size': {'尺寸'},
            'width': {'宽度'},
            'height': {'高度'},
            'depth': {'深度'},
            'channel': {'通道'},
            'index': {'索引'},
            'count': {'计数'},
            'number': {'数量'},
            'type': {'类型'},
            'mode': {'模式'},
            'method': {'方法'},
            'algorithm': {'算法'},
            'function': {'函数'},
            'parameter': {'参数'},
            'setting': {'设置'},
            'option': {'选项'},
            'enable': {'启用'},
            'disable': {'禁用'},
            'true': {'是', '真'},
            'false': {'否', '假'}
        }
        
        # 6. 检查是否在标准翻译中
        if english_key.lower() in translations:
            return chinese_text in translations[english_key.lower()]
            
        # 7. 默认通过检查
        return True

    def _final_validate_and_correct(self, original_file: str, final_translated_file: str) -> tuple[bool, Dict, str]:
        """最终校验和修正，通过建立中英文映射关系来修正键名"""
        try:
            # 读取文件
            with open(original_file, 'r', encoding='utf-8') as f:
                original_data = json.load(f)
            with open(final_translated_file, 'r', encoding='utf-8') as f:
                translated_data = json.load(f)
            
            log_entries = []
            log_entries.append("\n=== 最终校验修正日志 ===")
            log_entries.append(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_entries.append("=" * 50)
            
            # 第一步：建立中英文双向映射
            en_to_cn = {}  # 英文到中文的映射
            cn_to_en = {}  # 中文到英文的映射
            log_entries.append("\n第一步：建立中英文映射关系")
            
            # 1.1 首先从原始文件中获取所有英文键
            for node_name, node_data in original_data.items():
                for section in ["inputs", "outputs", "widgets"]:
                    if section in node_data:
                        for key, value in node_data[section].items():
                            # 如果原始文件中键和值相同，这个键就是标准英文键
                            if key == value:
                                # 在翻译后的文件中查找对应的中文值
                                if (node_name in translated_data and 
                                    section in translated_data[node_name]):
                                    trans_section = translated_data[node_name][section]
                                    # 如果找到了这个键对应的中文值
                                    if key in trans_section:
                                        trans_value = trans_section[key]
                                        if any('\u4e00' <= char <= '\u9fff' for char in str(trans_value)):
                                            en_to_cn[key] = trans_value
                                            cn_to_en[trans_value] = key
                                            log_entries.append(f"从原始文件映射: {key} <-> {trans_value}")
            
            # 1.2 从翻译后的文件中收集其他映射关系
            for node_name, node_data in translated_data.items():
                for section in ["inputs", "outputs", "widgets"]:
                    if section in node_data:
                        for key, value in node_data[section].items():
                            # 如果值是中文且键是英文
                            if (any('\u4e00' <= char <= '\u9fff' for char in str(value)) and
                                not any('\u4e00' <= char <= '\u9fff' for char in str(key))):
                                en_to_cn[key] = value
                                cn_to_en[value] = key
                                log_entries.append(f"从翻译文件映射: {key} <-> {value}")
                            # 如果键是中文且值是英文
                            elif (any('\u4e00' <= char <= '\u9fff' for char in str(key)) and
                                  not any('\u4e00' <= char <= '\u9fff' for char in str(value))):
                                cn_to_en[key] = value
                                en_to_cn[value] = key
                                log_entries.append(f"从翻译文件映射: {value} <-> {key}")
            
            # 第二步：修正所有节点
            final_corrected = {}
            corrections_made = False
            log_entries.append("\n第二步：应用修正")
            
            for node_name, node_data in translated_data.items():
                corrected_node = {
                    "title": node_data["title"],
                    "inputs": {},
                    "outputs": {},
                    "widgets": {}
                }
                
                # 获取原始节点数据
                orig_node = original_data.get(node_name, {})
                
                # 处理每个部分
                for section in ["inputs", "outputs", "widgets"]:
                    if section in node_data:
                        # 获取原始部分的键
                        orig_keys = orig_node.get(section, {}).keys()
                        
                        for key, value in node_data[section].items():
                            # 如果键是中文，需要修正
                            if any('\u4e00' <= char <= '\u9fff' for char in str(key)):
                                if key in cn_to_en:
                                    eng_key = cn_to_en[key]
                                    # 验证这个英文键是否在原始数据中
                                    if eng_key in orig_keys:
                                        corrected_node[section][eng_key] = value
                                        corrections_made = True
                                        log_entries.append(f"修正键: {key} -> {eng_key}")
                                    else:
                                        # 如果不在原始数据中，尝试查找原始键
                                        for orig_key in orig_keys:
                                            if orig_key.lower() == eng_key.lower():
                                                corrected_node[section][orig_key] = value
                                                corrections_made = True
                                                log_entries.append(f"修正键(使用原始大小写): {key} -> {orig_key}")
                                                break
                                else:
                                    # 在原始数据中查找对应的英文键
                                    found = False
                                    for orig_key in orig_keys:
                                        if orig_key in en_to_cn and en_to_cn[orig_key] == key:
                                            corrected_node[section][orig_key] = value
                                            corrections_made = True
                                            log_entries.append(f"修正键(从原始数据): {key} -> {orig_key}")
                                            found = True
                                            break
                                    if not found:
                                        log_entries.append(f"警告: 未找到键 '{key}' 的英文映射")
                                        # 保持原样
                                        corrected_node[section][key] = value
                            else:
                                corrected_node[section][key] = value
                
                final_corrected[node_name] = corrected_node
            
            # 保存映射关系
            mapping_file = os.path.join(self.dirs["temp"], "translation_mapping.json")
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "en_to_cn": en_to_cn,
                    "cn_to_en": cn_to_en
                }, f, indent=4, ensure_ascii=False)
            
            # 保存详细日志
            log_file = os.path.join(self.dirs["logs"], 
                                  f"final_correction_log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
            log_content = '\n'.join(log_entries)
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(log_content)
            
            # 如果进行了修正，保存结果
            if corrections_made:
                output_file = os.path.join(self.dirs["temp"], "final_corrected.json")
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(final_corrected, f, indent=4, ensure_ascii=False)
            
            return not corrections_made, final_corrected, log_content
            
        except Exception as e:
            error_msg = f"最终校验修正失败: {str(e)}"
            return False, translated_data, error_msg 

    def _cleanup_temp_files(self, temp_files: List[str], update_progress=None):
        """清理临时文件
        
        Args:
            temp_files: 临时文件路径列表
            update_progress: 进度更新回调函数
        """
        if not temp_files:
            return
        
        if update_progress:
            update_progress(97, "[清理] 开始清理临时文件...")
        
        for file_path in temp_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    if update_progress:
                        update_progress(98, f"[清理] 已删除: {os.path.basename(file_path)}")
            except Exception as e:
                if update_progress:
                    update_progress(98, f"[警告] 清理文件失败: {os.path.basename(file_path)} ({str(e)})")
        
        if update_progress:
            update_progress(99, "[清理] 临时文件清理完成") 
    def _collect_missing(self, original_nodes: Dict, current_nodes: Dict) -> tuple[Dict, int]:
        missing = {}
        total = 0
        only_tooltips = getattr(self, "only_tooltips", False)
        
        for node_name, orig in original_nodes.items():
            curr = current_nodes.get(node_name, {})
            node_miss = {"title": None, "inputs": {}, "widgets": {}, "outputs": {}, "tooltips": {}}
            
            # 如果开启了“仅译tooltip”，跳过标题、输入、输出和控件的检查
            if not only_tooltips:
                title = curr.get("title", "")
                if not self._has_chinese(title):
                    node_miss["title"] = orig.get("title", title or node_name)
                    total += 1
                    
                for section in ["inputs", "widgets", "outputs"]:
                    osec = orig.get(section, {})
                    csec = curr.get(section, {})
                    for k in set(osec.keys()) | set(csec.keys()):
                        v = csec.get(k, "")
                        if not self._has_chinese(str(v)) or v == k:
                            node_miss[section][k] = osec.get(k, k)
                            total += 1
            
            # 无论是否开启“仅译tooltip”，都要检查 tooltips
            tsec = curr.get("tooltips", {})
            # 这里的逻辑需要微调：如果 target_keys 中的项在 tsec 中没有中文，则标记为缺失
            target_keys = set(orig.get("inputs", {}).keys()) | set(orig.get("widgets", {}).keys()) | set(orig.get("tooltips", {}).keys())
            for k in target_keys:
                v = tsec.get(k, "")
                if not self._has_chinese(str(v)):
                    # 这里我们需要原始的信息来重新翻译 tooltip
                    node_miss["tooltips"][k] = orig.get("tooltips", {}).get(k, k)
                    total += 1
                    
            if node_miss["title"] or node_miss["inputs"] or node_miss["widgets"] or node_miss["outputs"] or node_miss["tooltips"]:
                missing[node_name] = node_miss
        return missing, total

    def _merge_translations(self, current_nodes: Dict, translated_missing: Dict) -> None:
        only_tooltips = getattr(self, "only_tooltips", False)
        for node_name, trans in translated_missing.items():
            curr = current_nodes.setdefault(node_name, {
                "title": "", "inputs": {}, "widgets": {}, "outputs": {}, "tooltips": {},
                "_class_name": "", "_mapped_name": "", "_source_file": ""
            })
            
            if not only_tooltips:
                if trans.get("title") and self._has_chinese(str(trans["title"])):
                    curr["title"] = trans["title"]
                for section in ["inputs", "widgets", "outputs"]:
                    for k, v in trans.get(section, {}).items():
                        if self._has_chinese(str(v)):
                            curr.setdefault(section, {})[k] = v
                            
            for k, v in trans.get("tooltips", {}).items():
                if self._has_chinese(str(v)):
                    curr.setdefault("tooltips", {})[k] = v

    def _coverage(self, nodes: Dict) -> Dict:
        total_keys = 0
        covered = 0
        for _, info in nodes.items():
            if "title" in info:
                total_keys += 1
                if self._has_chinese(str(info.get("title", ""))):
                    covered += 1
            for section in ["inputs", "widgets", "outputs", "tooltips"]:
                sec = info.get(section, {})
                for k, v in sec.items():
                    total_keys += 1
                    if self._has_chinese(str(v)):
                        covered += 1
        coverage = 100.0 * covered / total_keys if total_keys else 100.0
        return {"total_keys": total_keys, "covered_keys": covered, "coverage": coverage}

    def _has_chinese(self, text: str) -> bool:
        return any('\u4e00' <= ch <= '\u9fff' for ch in str(text))
