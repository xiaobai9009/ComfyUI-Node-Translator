import os
import json
import time
import requests
from typing import Dict, List, Optional
from .prompts import PromptTemplate
from .file_utils import FileUtils
from .translator import Translator

class OllamaTranslator(Translator):
    """Ollama节点翻译器类
    
    负责调用Ollama API将节点信息翻译成中文
    """
    
    def __init__(self, base_url: str, model_id: str, temperature: float = 0.3, top_p: float = 0.95):
        """初始化翻译器
        
        Args:
            base_url: Ollama API基础URL
            model_id: Ollama模型ID
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
        """测试 API 连接"""
        try:
            # 从模板获取测试提示词
            system_prompt = PromptTemplate.get_test_prompt()
            
            # 构建请求数据
            data = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "你好，请回复一句话。"}
                ],
                "temperature": self.temperature,
                "top_p": self.top_p,
                "stream": False,
                "max_tokens": 100
            }
            
            # 发送请求
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=30
            )
            
            # 检查响应
            if response.status_code == 200:
                result = response.json()
                if "message" in result and result["message"]["content"]:
                    return True
                else:
                    raise Exception("API 响应格式不正确")
            else:
                raise Exception(f"API 请求失败，状态码: {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            raise Exception("无法连接到Ollama服务器，请确认服务器地址和端口是否正确")
        except requests.exceptions.Timeout:
            raise Exception("请求超时，请检查Ollama服务器是否正常运行")
        except Exception as e:
            raise Exception(f"API 连接测试失败: {str(e)}")

    def _translate_batch(self, batch_nodes: Dict, update_progress=None, progress=0) -> Dict:
        """翻译一批节点"""
        try:
            # 构建请求数据
            data = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": json.dumps(batch_nodes, ensure_ascii=False)}
                ],
                "temperature": self.temperature,
                "top_p": self.top_p,
                "stream": False,
                "max_tokens": 4096
            }
            
            # 发送请求
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=300  # 增加超时时间到300秒，因为本地模型翻译可能需要较长时间
            )
            
            # 检查响应
            if response.status_code != 200:
                msg = None
                try:
                    err = response.json()
                    msg = err.get("error") or err.get("message")
                except Exception:
                    msg = response.text[:200] if response.text else None
                raise Exception(f"API 请求失败，状态码: {response.status_code}" + (f": {msg}" if msg else ""))
            
            result = response.json()
            
            # 解析返回结果
            response_text = result["message"]["content"]
            
            # 统计 tokens (Ollama API 返回的 prompt_eval_count 和 eval_count)
            prompt_tokens = result.get("prompt_eval_count", 0)
            completion_tokens = result.get("eval_count", 0)
            batch_tokens = prompt_tokens + completion_tokens
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_tokens = self.total_prompt_tokens + self.total_completion_tokens
            
            if update_progress:
                update_progress(progress, f"[统计] 本批次使用 {batch_tokens} tokens (输入: {prompt_tokens}, 输出: {completion_tokens})，累计: {self.total_tokens} tokens")

            try:
                # 提取 JSON 内容
                translated_nodes = self._extract_json_from_response(response_text)
                return translated_nodes
            except Exception as e:
                raise Exception(f"翻译结果不是有效的 JSON 格式: {response_text}, 错误: {str(e)}")
            
        except Exception as e:
            raise Exception(f"翻译失败: {str(e)}")

    def get_available_models(self) -> List[str]:
        """获取可用的Ollama模型列表"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"获取模型列表失败，状态码: {response.status_code}")
            
            result = response.json()
            
            if "models" in result:
                return [model["name"] for model in result["models"]]
            else:
                return []
        except Exception as e:
            raise Exception(f"获取模型列表失败: {str(e)}")

    def unload_model(self, model_name: str = None) -> bool:
        """卸载Ollama模型
        
        Args:
            model_name: 要卸载的模型名称，如果为None则卸载当前模型
            
        Returns:
            bool: 卸载是否成功
        """
        try:
            target_model = model_name if model_name else self.model_id
            
            if not target_model:
                raise Exception("未指定要卸载的模型")
            
            # 构建请求数据
            data = {
                "model": target_model,
                "keep_alive": 0  # 设置为0表示立即卸载
            }
            
            # 发送请求
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                return True
            else:
                raise Exception(f"卸载模型失败，状态码: {response.status_code}")
                
        except Exception as e:
            raise Exception(f"卸载模型失败: {str(e)}")
