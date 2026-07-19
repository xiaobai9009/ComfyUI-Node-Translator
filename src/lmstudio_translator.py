import os
import json
import time
import requests
import subprocess
from typing import Dict, List
from .prompts import PromptTemplate
from .file_utils import FileUtils
from .translation_config import TranslationConfig

from .translator import Translator

class LMStudioTranslator(Translator):
    """LMStudio节点翻译器类
    
    负责调用LMStudio API将节点信息翻译成中文
    """
    
    def __init__(self, base_url: str, model_id: str, temperature: float = 0.3, top_p: float = 0.95):
        """初始化翻译器
        
        Args:
            base_url: LMStudio API基础URL
            model_id: LMStudio模型ID
        """
        self.base_url = base_url.rstrip('/')
        self.model_id = model_id
        self.temperature = temperature
        self.top_p = top_p
        
        # 获取程序根目录
        self.base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 初始化输出目录（仅主目录）
        self.dirs = FileUtils.init_output_dirs(self.base_path)
        
        # 从提示词模板获取系统提示词
        self.system_prompt = PromptTemplate.get_translator_prompt()
        
        # 工作目录按插件在翻译时临时创建
        self.work_dir = None
        
        self.total_prompt_tokens = 0    # 输入 tokens
        self.total_completion_tokens = 0 # 输出 tokens
        self.total_tokens = 0           # 总 tokens
        self.only_tooltips = False

    def test_connection(self) -> bool:
        """测试 API 连接

        针对 Gemma 系列模型（translategemma-12b-it 等）容易出现：
          1) 400 Bad Request：通常是不支持 system role / max_tokens 太小
          2) Channel Error：LM Studio 后端问题或模型未加载

        修复策略：按顺序尝试多种请求体格式
        """
        # 多种请求格式的回退尝试
        attempt_payloads = [
            # 尝试 1：标准 chat 格式（带 system + max_tokens=100）
            {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": "你是一个翻译助手。"},
                    {"role": "user", "content": "你好"}
                ],
                "temperature": self.temperature,
                "top_p": self.top_p,
                "stream": False,
                "max_tokens": 100
            },
            # 尝试 2：去掉 system role（部分 Gemma/翻译模型不支持）
            {
                "model": self.model_id,
                "messages": [
                    {"role": "user", "content": "你好"}
                ],
                "temperature": self.temperature,
                "top_p": self.top_p,
                "stream": False,
                "max_tokens": 100
            },
            # 尝试 3：去掉 top_p（部分 LM Studio 版本不接受）
            {
                "model": self.model_id,
                "messages": [
                    {"role": "user", "content": "你好"}
                ],
                "temperature": self.temperature,
                "stream": False,
                "max_tokens": 100
            },
            # 尝试 4：最小化请求（仅 model + messages）
            {
                "model": self.model_id,
                "messages": [
                    {"role": "user", "content": "hi"}
                ],
                "max_tokens": 50
            },
        ]

        last_error = None
        for idx, data in enumerate(attempt_payloads, 1):
            try:
                response = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=data,
                    timeout=30
                )
                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"].get("content", "")
                        if content:
                            if idx > 1:
                                print(f"[LMStudio] API 测试在第 {idx} 次尝试时成功（兼容回退）")
                            return True
                        raise Exception("API 响应中 content 为空")
                    raise Exception("API 响应中没有 choices 字段")
                # 400 错误：尝试下一种格式
                if response.status_code == 400:
                    err_text = ""
                    try:
                        err_text = response.text[:300]
                    except Exception:
                        pass
                    last_error = f"尝试 {idx} 失败 (400): {err_text}"
                    continue
                # 其他错误码：抛出
                raise Exception(f"API 请求失败，状态码: {response.status_code} - {response.text[:200]}")
            except requests.exceptions.ConnectionError:
                raise Exception("无法连接到LMStudio服务器，请确认服务器地址和端口是否正确（默认 http://localhost:1234）")
            except requests.exceptions.Timeout:
                raise Exception("请求超时，请检查LMStudio服务器是否正常运行")
            except Exception as e:
                # 尝试下一组 payload
                last_error = str(e)
                continue

        # 所有尝试都失败
        raise Exception(
            f"API 连接测试失败：尝试了 {len(attempt_payloads)} 种请求格式均失败。\n"
            f"最后错误: {last_error}\n"
            f"建议：\n"
            f"1) 在 LM Studio 中确认模型已加载（Developer → Active Model）\n"
            f"2) 检查 Context Length 设置（建议 8192+）\n"
            f"3) translategemma-12b-it 是 base 模型，请使用 -it 变体（instruct-tuned）\n"
            f"4) 在 LM Studio 中检查模型是否支持 chat template"
        )

    def _translate_batch(self, batch_nodes: Dict, update_progress=None, progress=0) -> Dict:
        """翻译一批节点"""
        # 基础 payload（标准 chat 格式）
        def make_data(use_system=True, use_top_p=True, max_tokens=4096):
            messages = []
            if use_system:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": json.dumps(batch_nodes, ensure_ascii=False)})
            data = {
                "model": self.model_id,
                "messages": messages,
                "stream": False,
                "max_tokens": max_tokens
            }
            if use_top_p:
                data["top_p"] = self.top_p
            data["temperature"] = self.temperature
            return data

        # 多级回退：先标准，失败再尝试兼容性更好的格式
        attempts = [
            ("标准", lambda: make_data(use_system=True, use_top_p=True)),
            ("去system", lambda: make_data(use_system=False, use_top_p=True)),
            ("去system+top_p", lambda: make_data(use_system=False, use_top_p=False)),
        ]
        last_err = None
        for label, builder in attempts:
            data = builder()
            try:
                response = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=data,
                    timeout=300
                )
                if response.status_code == 200:
                    if update_progress and label != "标准":
                        update_progress(progress, f"[LMStudio] 使用兼容回退格式 ({label}) 成功")
                    # 进入主解析流程
                    return self._parse_translation_response(response, update_progress, progress)
                # 400: 尝试下一格式
                if response.status_code == 400:
                    msg = None
                    try:
                        err = response.json()
                        msg = err.get("error", {}).get("message") or err.get("message")
                    except Exception:
                        msg = response.text[:200] if response.text else None
                    last_err = f"{response.status_code} ({label}): {msg}"
                    continue
                # 其他错误直接抛出
                msg = None
                try:
                    err = response.json()
                    msg = err.get("error", {}).get("message") or err.get("message")
                except Exception:
                    msg = response.text[:200] if response.text else None
                raise Exception(f"API 请求失败，状态码: {response.status_code}" + (f": {msg}" if msg else ""))
            except requests.exceptions.ConnectionError:
                raise Exception("无法连接到LMStudio服务器")
            except requests.exceptions.Timeout:
                raise Exception("请求超时（300s）")
        # 所有尝试失败
        raise Exception(f"翻译失败：尝试 {len(attempts)} 种请求格式均失败 - 最后错误: {last_err}")

    def _parse_translation_response(self, response, update_progress, progress):
        """解析 LM Studio 翻译响应"""
        result = response.json()
        if "usage" in result:
            usage = result["usage"]
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            batch_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_tokens += batch_tokens
            if update_progress:
                update_progress(progress, f"[统计] 本批次使用 {batch_tokens} tokens (输入: {prompt_tokens}, 输出: {completion_tokens})，累计: {self.total_tokens} tokens")
        response_text = result["choices"][0]["message"]["content"]
        try:
            return self._extract_json_from_response(response_text)
        except Exception as e:
            raise Exception(f"翻译结果不是有效的 JSON 格式: {response_text}, 错误: {str(e)}")

    def get_available_models(self) -> List[str]:
        """获取可用的LMStudio模型列表"""
        try:
            response = requests.get(f"{self.base_url}/v1/models", timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"获取模型列表失败，状态码: {response.status_code}")
            
            result = response.json()
            
            if "data" in result:
                return [model["id"] for model in result["data"]]
            else:
                return []
        except Exception as e:
            raise Exception(f"获取模型列表失败: {str(e)}")

    def unload_model(self, model_name: str = None) -> bool:
        """卸载LMStudio模型
        
        Args:
            model_name: 要卸载的模型名称，如果为None则卸载当前模型
            
        Returns:
            bool: 卸载是否成功
        """
        try:
            target_model = model_name if model_name else self.model_id
            
            if not target_model:
                raise Exception("未指定要卸载的模型")
            
            # 使用LM Studio命令行工具卸载模型
            # 命令格式: lms unload <model_name>
            try:
                result = subprocess.run(
                    ["lms", "unload", target_model],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False
                )
                
                # 检查命令执行结果
                if result.returncode == 0:
                    return True
                else:
                    # 即使返回非0，也可能已经卸载成功
                    # 因为模型可能本来就没有加载
                    error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
                    if "not loaded" in error_msg.lower() or "not found" in error_msg.lower():
                        # 模型本来就没有加载，视为成功
                        return True
                    raise Exception(f"命令执行失败: {error_msg}")
                    
            except FileNotFoundError:
                raise Exception("未找到lms命令，请确保LM Studio CLI已安装并添加到PATH环境变量")
            except subprocess.TimeoutExpired:
                raise Exception("卸载命令执行超时")
                
        except Exception as e:
            raise Exception(f"卸载模型失败: {str(e)}")
