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
    
    def __init__(self, api_key: str, model_id: str, base_url: str = "https://ark.cn-beijing.volces.com/api/v3", temperature: float = 0.3, top_p: float = 0.95, fallback_models: Optional[List[str]] = None, service_name: Optional[str] = None):
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
        # 错误重试策略已由主流程统一管理(批次级重试 + 429 自动退避),不再使用单一 error_policy
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
            # 错误重试策略已统一(批次级 + 429 自动退避)
            max_retries = 5
            delay = 2
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
                        # 统一使用指数退避 (2s -> 4s -> 8s -> ... -> 上限60s)
                        delay = min(delay * 2, 60)
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
                       update_progress=None, temp_dir: str = None, rounds: int = 2,
                       cooldown_sec: int = 0, batches_per_cooldown: int = 0,
                       update_cooldown=None) -> Dict:
        """智能分段翻译节点信息，支持断点续传和批次间冷却

        Args:
            nodes_info: 待翻译节点信息
            folder_path: 插件文件夹路径
            batch_size: 每批翻译的节点数
            update_progress: 进度回调
            temp_dir: 临时目录(用于断点续传)
            rounds: 多轮验证轮数
            cooldown_sec: 每 N 批后的冷却秒数 (0=不冷却)
            batches_per_cooldown: 每多少批后触发冷却 (0=不冷却)
            update_cooldown: 冷却状态回调 fn(batches_done:int, cooldown_sec:int, remaining_sec:int)
                - batches_done: 已完成的批次数
                - cooldown_sec: 计划冷却总秒数
                - remaining_sec: 剩余等待秒数(冷却期间逐秒减小)
        """
        temp_files = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        # 动态冷却参数(429后自动拉长)
        dynamic_cooldown = cooldown_sec
        rate_limit_hits = 0
        try:
            plugin_name = os.path.basename(folder_path.rstrip(os.path.sep))
            work_dir = temp_dir if temp_dir else os.path.join(self.base_path, "output", plugin_name, "_temp")
            os.makedirs(work_dir, exist_ok=True)
            self.current_plugin_path = folder_path
            original_file = os.path.join(work_dir, "nodes_to_translate.tmp.json")
            FileUtils.save_json(nodes_info, original_file)
            temp_files.append(original_file)

            # ====== 断点续传: 检查 checkpoint ======
            checkpoint_file = os.path.join(work_dir, "_checkpoint.json")
            all_translated_nodes = {}
            start_batch_idx = 0
            if os.path.exists(checkpoint_file):
                try:
                    ck = json.loads(open(checkpoint_file, "r", encoding="utf-8").read())
                    all_translated_nodes = ck.get("translated", {})
                    start_batch_idx = ck.get("batch_idx", 0)
                    if update_progress:
                        update_progress(0, f"[断点续传] 从 checkpoint 恢复，已翻译 {len(all_translated_nodes)} 个节点，从第 {start_batch_idx + 1} 批继续")
                except Exception:
                    if update_progress:
                        update_progress(0, "[警告] checkpoint 文件损坏，将从头开始翻译")

            if update_progress:
                update_progress(0, f"[准备] 保存原始节点信息到: {original_file}")

            node_items = list(nodes_info.items())
            total_batches = (len(node_items) + batch_size - 1) // batch_size
            # 限流时被推迟的节点(避免在主循环中修改 node_items 造成索引错位)
            deferred_translation_queue = []

            for batch_idx in range(start_batch_idx, total_batches):
                start_idx = batch_idx * batch_size
                end_idx = min((batch_idx + 1) * batch_size, len(node_items))
                current_batch = dict(node_items[start_idx:end_idx])

                # 跳过已在 checkpoint 中的批次
                batch_keys = set(current_batch.keys())
                if batch_keys.issubset(set(all_translated_nodes.keys())) and batch_idx < start_batch_idx:
                    continue

                if update_progress:
                    progress = int((batch_idx / total_batches) * 100)
                    node_names = list(current_batch.keys())
                    update_progress(progress, f"[翻译] 第 {batch_idx + 1}/{total_batches} 批: {', '.join(node_names)}")

                # ====== 批次级重试循环 ======
                batch_success = False
                batch_retry = 0
                max_batch_retries = 3
                current_batch_size = batch_size
                last_error = None

                while not batch_success and batch_retry <= max_batch_retries:
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

                        # ====== 保存 checkpoint ======
                        self._save_checkpoint(checkpoint_file, all_translated_nodes, batch_idx + 1)

                        if update_progress:
                            update_progress(progress, f"[完成] 批次 {batch_idx + 1} 的处理已完成")
                        batch_success = True
                        rate_limit_hits = 0  # 成功后重置限流计数
                        dynamic_cooldown = cooldown_sec  # 重置动态冷却

                    except Exception as e:
                        last_error = e
                        err_str = str(e).lower()
                        is_rate_limit = "429" in err_str or "rate limit" in err_str or "rate-limited" in err_str

                        if is_rate_limit:
                            rate_limit_hits += 1
                            # 动态退避: 冷却时间翻倍,上限300秒
                            dynamic_cooldown = max(dynamic_cooldown or 10, dynamic_cooldown * 2)
                            dynamic_cooldown = min(dynamic_cooldown, 300)
                            # 减半批次大小(最小2个节点)
                            current_batch_size = max(2, current_batch_size // 2)
                            # 重新分割当前批次:把未翻译的剩余项加入 deferred 队列
                            # (而不是直接修改 node_items 列表,避免外层循环的 batch_idx 计算与列表错位)
                            sub_items = list(current_batch.items())
                            if len(sub_items) > 1 and current_batch_size < len(sub_items):
                                # 只翻译前一半,剩下的推迟到主循环之后处理
                                sub_batch = dict(sub_items[:current_batch_size])
                                current_batch = sub_batch
                                deferred_translation_queue.extend(sub_items[current_batch_size:])
                                if update_progress:
                                    update_progress(progress, f"[限流策略] 429限流,冷却 {dynamic_cooldown}s,本批缩减为 {current_batch_size} 个节点,剩余 {len(sub_items) - current_batch_size} 个节点延迟到主循环后处理")
                            else:
                                if update_progress:
                                    update_progress(progress, f"[限流策略] 429限流,冷却 {dynamic_cooldown}s 后重试")

                            time.sleep(dynamic_cooldown + random.uniform(0, 2))
                            batch_retry += 1
                            continue

                        batch_retry += 1
                        if batch_retry <= max_batch_retries:
                            wait = 2 ** batch_retry
                            if update_progress:
                                update_progress(progress, f"[重试] 批次 {batch_idx + 1} 失败，{wait}s 后第 {batch_retry} 次重试: {str(e)[:80]}")
                            time.sleep(wait + random.uniform(0, 1))
                        else:
                            break

                if not batch_success:
                    raise Exception(f"批次 {batch_idx + 1} 翻译失败(已重试 {max_batch_retries} 次): {str(last_error)[:200]}")

                # ====== 批次间冷却 ======
                # 仅在到达用户设置的批数时显示累计信息(例如"每10批冷却30秒" → 第10/20/30...批完成后显示)
                if batches_per_cooldown > 0 and dynamic_cooldown > 0:
                    batches_done = batch_idx - start_batch_idx + 1
                    if batches_done % batches_per_cooldown == 0 and batch_idx < total_batches - 1:
                        if update_progress:
                            update_progress(progress, f"[冷却] 已完成 {batches_done} 批，暂停 {dynamic_cooldown}s 避免限流...")
                        # 逐秒等待 + 通知 UI(让用户在信息窗口看到倒计时)
                        total_wait = int(dynamic_cooldown)
                        for remaining in range(total_wait, 0, -1):
                            if update_cooldown:
                                try:
                                    update_cooldown(batches_done, total_wait, remaining)
                                except Exception:
                                    pass
                            time.sleep(1)
                        if update_cooldown:
                            try:
                                update_cooldown(batches_done, total_wait, 0)
                            except Exception:
                                pass

            # ====== 处理 429 限流时推迟的节点(主循环跑完后再处理) ======
            if deferred_translation_queue:
                if update_progress:
                    update_progress(95, f"[限流补偿] 处理主循环中被推迟的 {len(deferred_translation_queue)} 个节点...")
                # 再次冷却,确保限流窗口已过
                time.sleep(dynamic_cooldown + random.uniform(0, 2))
                # 用当前缩小的 current_batch_size 重新分批
                # 过滤掉已经在 all_translated_nodes 中的节点(主循环可能已翻译)
                pending = [(k, v) for (k, v) in deferred_translation_queue if k not in all_translated_nodes]
                if pending:
                    deferred_total = len(pending)
                    deferred_batch_size = max(1, current_batch_size)
                    deferred_done = 0
                    for d_start in range(0, deferred_total, deferred_batch_size):
                        d_end = min(d_start + deferred_batch_size, deferred_total)
                        d_batch = dict(pending[d_start:d_end])
                        d_keys = set(d_batch.keys())
                        # 跳过已翻译的
                        if d_keys.issubset(set(all_translated_nodes.keys())):
                            continue
                        deferred_done += 1
                        if update_progress:
                            update_progress(95, f"[限流补偿] 批次 {deferred_done}/{(deferred_total + deferred_batch_size - 1) // deferred_batch_size}: {', '.join(list(d_batch.keys())[:3])}...")
                        try:
                            res = self._translate_batch(d_batch, update_progress, 95)
                            self._merge_translations(all_translated_nodes, res)
                            # 保存checkpoint以支持断点续传
                            self._save_checkpoint(checkpoint_file, all_translated_nodes, total_batches)
                        except Exception as e:
                            if update_progress:
                                update_progress(95, f"[限流补偿警告] 推迟批次失败: {str(e)[:100]},将由后续补漏处理")
                    if update_progress:
                        update_progress(95, f"[限流补偿] 完成,共处理 {deferred_done} 批")

            # ====== 最终验证 ======
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

            # ====== 多轮补漏 ======
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
                    # 连续 2 轮无改进才退出(给模型留出重新思考的机会,避免误退)
                    if consecutive_no_improve >= 2:
                        if update_progress:
                            update_progress(97, f"[终止] 连续 {consecutive_no_improve} 轮无改进,结束补漏流程")
                        break
                    if update_progress:
                        update_progress(97, f"[继续] 第 {r} 轮有进展,准备下一轮")
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

            # ====== 保存到 ComfyUI 目录 ======
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

            # ====== 清理 ======
            self._cleanup_temp_files(temp_files, update_progress)
            # 成功后删除 checkpoint
            try:
                if os.path.exists(checkpoint_file):
                    os.remove(checkpoint_file)
            except Exception:
                pass
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
            # 失败时保留 checkpoint，下次可续传
            self._cleanup_temp_files(temp_files, update_progress)
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

    def _save_checkpoint(self, checkpoint_file: str, translated: Dict, batch_idx: int):
        """保存断点续传 checkpoint"""
        try:
            ck = {"translated": translated, "batch_idx": batch_idx, "time": time.strftime('%Y-%m-%d %H:%M:%S')}
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(ck, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # checkpoint 保存失败不应中断翻译

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
        
        # 第一遍：收集所有需要补译 tooltip 的键，避免逐个调用 LLM（性能优化）
        # 按节点分组的缺失 tooltip 列表
        nodes_need_tooltip_translation = {}  # {node_name: {key: display}}
        nodes_need_doc_lookup = {}  # {node_name: {key: display}}
        
        # 先做一次快速检查，只做 key 补齐，不调用 LLM
        for node_name, node_info in original_nodes.items():
            if node_name not in translated_nodes:
                final_nodes[node_name] = node_info
                continue
            
            translated_info = translated_nodes[node_name]
            
            # 验证必要字段
            if not all(field in translated_info for field in ["title", "inputs", "widgets", "outputs"]):
                final_nodes[node_name] = node_info
                continue
            
            target_keys = (
                set(node_info.get("inputs", {}).keys()) |
                set(node_info.get("widgets", {}).keys()) |
                set(translated_info.get("inputs", {}).keys()) |
                set(translated_info.get("widgets", {}).keys()) |
                set(node_info.get("tooltips", {}).keys())
            )
            trans_tooltips = translated_info.get("tooltips", {})
            
            for key in target_keys:
                # 已经有翻译过的 tooltip 就跳过
                if key in trans_tooltips and trans_tooltips[key]:
                    continue
                # 原节点有 tooltip 但翻译结果里没有 -> 需要翻译原 tooltip
                if key in node_info.get("tooltips", {}):
                    display = (
                        translated_info.get("inputs", {}).get(key) or
                        translated_info.get("widgets", {}).get(key) or
                        key
                    )
                    nodes_need_tooltip_translation.setdefault(node_name, {})[key] = display
                else:
                    # 原节点也没有 -> 走 README 查找逻辑
                    display = (
                        translated_info.get("inputs", {}).get(key) or
                        translated_info.get("widgets", {}).get(key) or
                        key
                    )
                    nodes_need_doc_lookup.setdefault(node_name, {})[key] = display
        
        # 第二遍：按节点批量翻译缺失的 tooltip（一次 API 调用处理一个节点所有缺失的 tooltip）
        translated_tooltips_cache = {}  # {(node_name, key): tip}
        
        # 批量翻译原 tooltip
        for node_name, keys_map in nodes_need_tooltip_translation.items():
            if update_progress:
                update_progress(96, f"[验证] 补译节点 {node_name} 的 {len(keys_map)} 个 tooltip")
            try:
                results = self._translate_tooltips_batch(keys_map, translated_nodes[node_name].get("tooltips", {}))
                for key, tip in results.items():
                    translated_tooltips_cache[(node_name, key)] = tip
            except Exception as e:
                # 失败时回退到默认模板
                for key, display in keys_map.items():
                    translated_tooltips_cache[(node_name, key)] = None  # 标记失败
        
        # 批量查找 README 并翻译
        for node_name, keys_map in nodes_need_doc_lookup.items():
            try:
                results = self._translate_doc_lines_batch(keys_map, self.current_plugin_path)
                for key, tip in results.items():
                    if tip:
                        translated_tooltips_cache[(node_name, key)] = tip
            except Exception as e:
                pass
        
        # 第三遍：组装最终结果
        for node_name, node_info in original_nodes.items():
            if node_name in final_nodes:
                continue
            translated_info = translated_nodes[node_name]
            
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
                for key in orig_section:
                    if key in trans_section:
                        validated_node[section][key] = trans_section[key]
                    else:
                        validated_node[section][key] = key
            
            # 组装 tooltips
            target_keys = (
                set(node_info.get("inputs", {}).keys()) |
                set(node_info.get("widgets", {}).keys()) |
                set(translated_info.get("inputs", {}).keys()) |
                set(translated_info.get("widgets", {}).keys()) |
                set(node_info.get("tooltips", {}).keys())
            )
            trans_tooltips = translated_info.get("tooltips", {})
            for key in target_keys:
                if key in trans_tooltips and trans_tooltips[key]:
                    validated_node["tooltips"][key] = trans_tooltips[key]
                elif (node_name, key) in translated_tooltips_cache and translated_tooltips_cache[(node_name, key)]:
                    validated_node["tooltips"][key] = translated_tooltips_cache[(node_name, key)]
                else:
                    display = (
                        validated_node["inputs"].get(key) or
                        validated_node["widgets"].get(key) or
                        translated_info.get("inputs", {}).get(key) or
                        translated_info.get("widgets", {}).get(key) or
                        key
                    )
                    validated_node["tooltips"][key] = f"该参数用于设置“{display}”"
            
            final_nodes[node_name] = validated_node
        
        return final_nodes

    def _translate_tooltips_batch(self, keys_map: Dict[str, str], orig_tooltips: Dict[str, str]) -> Dict[str, str]:
        """批量翻译原 tooltip（一次 API 调用处理多个 key）
        
        Args:
            keys_map: {key: display_name} 需要补译的键
            orig_tooltips: 原始 tooltip 字典 {key: english_tooltip}
            
        Returns:
            Dict[str, str]: {key: translated_tooltip}
        """
        if not keys_map:
            return {}
        
        # 构造批处理 prompt
        items = []
        for key, display in keys_map.items():
            orig = orig_tooltips.get(key, "")
            if orig:
                items.append(f"参数: {display} (key={key})\n原tooltip: {orig}")
        
        if not items:
            return {}
        
        system_prompt = "你是一个专业的 ComfyUI 节点翻译助手。请将提供的英文 tooltip 简洁准确地翻译成中文。"
        user_prompt = (
            "请将以下参数的原 tooltip 翻译为简洁准确的中文 tooltip，"
            "保持与原意一致，不超过 80 字。\n"
            "返回严格的 JSON 格式: {\"key1\": \"翻译1\", \"key2\": \"翻译2\"}\n\n"
            + "\n\n---\n\n".join(items)
        )
        
        try:
            completion = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=1024
            )
            text = (completion.choices[0].message.content or "").strip()
            
            # 尝试解析 JSON
            import json as json_mod
            # 清理 markdown 代码块
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
            
            try:
                data = json_mod.loads(text)
                return {k: str(v) for k, v in data.items() if k in keys_map}
            except Exception:
                # 解析失败，逐个回退到默认模板
                return {key: None for key in keys_map}
        except Exception:
            return {key: None for key in keys_map}

    def _translate_doc_lines_batch(self, keys_map: Dict[str, str], plugin_path: Optional[str]) -> Dict[str, str]:
        """批量从 README 查找并翻译缺失 tooltip
        
        Args:
            keys_map: {key: display_name} 需要补译的键
            plugin_path: 插件路径
            
        Returns:
            Dict[str, str]: {key: translated_tooltip}
        """
        if not keys_map or not plugin_path:
            return {}
        
        # 先查找所有候选 doc 行
        key_to_doc = {}  # {key: doc_line}
        for key in keys_map:
            doc_line = self._find_doc_line(plugin_path, key)
            if doc_line:
                key_to_doc[key] = doc_line
        
        if not key_to_doc:
            return {}
        
        # 一次性翻译所有找到的 doc 行
        items = []
        key_order = []
        for key, doc_line in key_to_doc.items():
            display = keys_map[key]
            items.append(f"参数: {display} (key={key})\n文档片段: {doc_line}")
            key_order.append(key)
        
        system_prompt = "你是一个专业的 ComfyUI 节点翻译助手。请将提供的英文文档片段简洁翻译为中文 tooltip。"
        user_prompt = (
            "请将以下参数相关的英文文档片段翻译为简洁的中文 tooltip，"
            "每条不超过 60 字。\n"
            "返回严格的 JSON 格式: {\"key1\": \"翻译1\", \"key2\": \"翻译2\"}\n\n"
            + "\n\n---\n\n".join(items)
        )
        
        try:
            completion = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=1024
            )
            text = (completion.choices[0].message.content or "").strip()
            
            import json as json_mod
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
            
            try:
                data = json_mod.loads(text)
                return {k: str(v) for k, v in data.items() if k in key_to_doc}
            except Exception:
                return {}
        except Exception:
            return {}

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
        # ====== 输入保护：防止 LLM 把 tooltip 长文本塞到 inputs.value 里 ======
        # inputs 的 value 是 ComfyUI socket 类型，不应被翻译为完整句子
        # 翻译前用 __INPUT_TYPE__ 标记占位，翻译后强制还原为 key 名（保持类型标识语义）
        input_guard_keys = {}  # {node_name: {input_name: original_value}}
        safe_batch = {}
        for node_name, node_info in current_batch.items():
            safe_node = dict(node_info) if isinstance(node_info, dict) else node_info
            if isinstance(safe_node, dict) and 'inputs' in safe_node and isinstance(safe_node['inputs'], dict):
                guarded = {}
                orig_map = {}
                for k, v in safe_node['inputs'].items():
                    # 占位符：LLM 看到非英文标记会保持不变
                    guarded[k] = "__INPUT_TYPE__"
                    orig_map[k] = v
                input_guard_keys[node_name] = orig_map
                safe_node['inputs'] = guarded
            safe_batch[node_name] = safe_node

        translated_text = ""

        use_single_user = False
        mid = str(self.model_id or "").lower()
        if ("google/" in mid) or ("gemma" in mid) or ("gemini" in mid):
            use_single_user = True
        if use_single_user:
            messages = [
                {"role": "user", "content": f"{self.system_prompt}\n\n请翻译以下节点信息:\n{json.dumps(safe_batch, ensure_ascii=False)}"}
            ]
        else:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请翻译以下节点信息:\n{json.dumps(safe_batch, ensure_ascii=False)}"}
            ]
        # 错误重试策略已统一(批次级重试 + 429 自动退避),不再输出策略说明
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
            # 还原 input guard 标记：如果 LLM 误把 inputs.value 改成了 tooltip 长文本，
            # 或保留为 __INPUT_TYPE__，都强制还原为 key 自身（保持类型标识语义）
            if isinstance(batch_translated, dict) and input_guard_keys:
                for node_name, node_info in batch_translated.items():
                    if not isinstance(node_info, dict):
                        continue
                    if 'inputs' in node_info and isinstance(node_info['inputs'], dict) and node_name in input_guard_keys:
                        restored_inputs = {}
                        for k, v in node_info['inputs'].items():
                            # 还原：使用 key 名作为 value（避免 LLM 错误翻译）
                            if v == "__INPUT_TYPE__" or (isinstance(v, str) and len(v) > 40):
                                # 占位符未变 / 翻译成了长文本 -> 还原为 key
                                restored_inputs[k] = k
                            else:
                                restored_inputs[k] = v
                        node_info['inputs'] = restored_inputs
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
                if not self._is_valid_chinese_translation(title):
                    node_miss["title"] = orig.get("title", title or node_name)
                    total += 1
                    
                for section in ["inputs", "widgets", "outputs"]:
                    osec = orig.get(section, {})
                    csec = curr.get(section, {})
                    for k in set(osec.keys()) | set(csec.keys()):
                        v = csec.get(k, "")
                        if not self._is_valid_chinese_translation(str(v)) or v == k:
                            node_miss[section][k] = osec.get(k, k)
                            total += 1
            
            # 无论是否开启“仅译tooltip”，都要检查 tooltips
            tsec = curr.get("tooltips", {})
            # 这里的逻辑需要微调：如果 target_keys 中的项在 tsec 中没有中文，则标记为缺失
            target_keys = set(orig.get("inputs", {}).keys()) | set(orig.get("widgets", {}).keys()) | set(orig.get("tooltips", {}).keys())
            for k in target_keys:
                v = tsec.get(k, "")
                if not self._is_valid_chinese_translation(str(v)):
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
                if trans.get("title") and self._is_valid_chinese_translation(str(trans["title"])):
                    curr["title"] = trans["title"]
                for section in ["inputs", "widgets", "outputs"]:
                    for k, v in trans.get(section, {}).items():
                        if self._is_valid_chinese_translation(str(v)):
                            curr.setdefault(section, {})[k] = v

            for k, v in trans.get("tooltips", {}).items():
                if self._is_valid_chinese_translation(str(v)):
                    curr.setdefault("tooltips", {})[k] = v

    def _coverage(self, nodes: Dict) -> Dict:
        total_keys = 0
        covered = 0
        for _, info in nodes.items():
            if "title" in info:
                total_keys += 1
                if self._is_valid_chinese_translation(str(info.get("title", ""))):
                    covered += 1
            for section in ["inputs", "widgets", "outputs", "tooltips"]:
                sec = info.get(section, {})
                for k, v in sec.items():
                    total_keys += 1
                    if self._is_valid_chinese_translation(str(v)):
                        covered += 1
        coverage = 100.0 * covered / total_keys if total_keys else 100.0
        return {"total_keys": total_keys, "covered_keys": covered, "coverage": coverage}

    def _has_chinese(self, text: str) -> bool:
        return any('\u4e00' <= ch <= '\u9fff' for ch in str(text))

    # 判定为"无效中文翻译"的填充式/占位式回答模式
    # 例如: "该参数用于设置 \"X\"", "用于设置 \"X\"", "此参数是 X 类型的参数"
    # 这些都属于模型偷懒的输出,不能算作有效翻译
    _PLACEHOLDER_CN_PATTERNS = [
        "该参数用于设置", "此参数用于设置", "用于设置",
        "该参数是", "此参数是", "参数是",
        "用来设置", "用于配置", "用于控制", "用于调整",
        "这是一个", "此参数控制", "控制参数",
    ]

    def _is_valid_chinese_translation(self, text: str) -> bool:
        """判断是否是有意义的中文翻译(而非模型偷懒的占位/填充式输出)"""
        if not self._has_chinese(text):
            return False
        t = str(text).strip()
        # 太短(只有1-2个中文字符)可能是空泛翻译,但也可能是合法的(例如"宽度")。
        # 这里只对过短且等于原文的标记为无效,其他都接受
        if len(t) <= 1:
            return False
        # 含"该参数用于设置"等明显占位模式 → 视为无效
        for p in self._PLACEHOLDER_CN_PATTERNS:
            if p in t:
                return False
        return True
