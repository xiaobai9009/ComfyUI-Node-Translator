"""翻译服务配置"""

class TranslationServiceConfig:
    """翻译服务基础配置类"""
    def __init__(self):
        self.name = ""
        self.label = ""  # UI显示名称
        self.models = []
        self.enabled = True
        self.requires_model_id = False
        self.default_model = ""
        self.base_url = ""
        self.api_key_url = ""
        self.model_selection_enabled = True

class DoubaoConfig(TranslationServiceConfig):
    """豆包(火山引擎)翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "doubao"
        self.label = "Doubao (豆包/火山)"
        self.models = []  # 火山引擎模型Endpoint ID通常是自定义的
        self.enabled = True
        self.requires_model_id = True
        self.default_model = ""
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.api_key_url = "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey"
        self.model_selection_enabled = False # 需要用户手动输入Endpoint ID

class AliyunConfig(TranslationServiceConfig):
    """阿里云(通义千问)翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "aliyun"
        self.label = "Aliyun (通义千问)"
        self.models = [
            "qwen-turbo",
            "qwen-plus", 
            "qwen-max",
            "qwen-max-longcontext"
        ]
        self.enabled = True
        self.default_model = "qwen-plus"
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_key_url = "https://dashscope.console.aliyun.com/apiKey"

class DeepSeekConfig(TranslationServiceConfig):
    """DeepSeek(深度求索)翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "deepseek"
        self.label = "DeepSeek (深度求索)"
        self.models = ["deepseek-chat", "deepseek-coder"]
        self.enabled = True
        self.default_model = "deepseek-chat"
        self.base_url = "https://api.deepseek.com"
        self.api_key_url = "https://platform.deepseek.com/api_keys"

class MoonshotConfig(TranslationServiceConfig):
    """Moonshot(Kimi)翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "moonshot"
        self.label = "Moonshot (Kimi)"
        self.models = ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]
        self.enabled = True
        self.default_model = "moonshot-v1-8k"
        self.base_url = "https://api.moonshot.cn/v1"
        self.api_key_url = "https://platform.moonshot.cn/console/api-keys"

class ZhipuConfig(TranslationServiceConfig):
    """智谱GLM翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "zhipu"
        self.label = "Zhipu (智谱GLM)"
        self.models = ["glm-4", "glm-4-air", "glm-4-flash", "glm-3-turbo"]
        self.enabled = True
        self.default_model = "glm-4-flash"
        self.base_url = "https://open.bigmodel.cn/api/paas/v4/"
        self.api_key_url = "https://open.bigmodel.cn/usercenter/apikeys"

class SiliconFlowConfig(TranslationServiceConfig):
    """SiliconFlow(硅基流动)翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "siliconflow"
        self.label = "SiliconFlow (硅基流动)"
        self.models = [
            "Qwen/Qwen2.5-7B-Instruct", 
            "Qwen/Qwen2.5-14B-Instruct", 
            "Qwen/Qwen2.5-32B-Instruct", 
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V2.5",
            "THUDM/glm-4-9b-chat"
        ]
        self.enabled = True
        self.default_model = "Qwen/Qwen2.5-72B-Instruct"
        self.base_url = "https://api.siliconflow.cn/v1"
        self.api_key_url = "https://cloud.siliconflow.cn/account/ak"

class OpenAIConfig(TranslationServiceConfig):
    """OpenAI(官方/中转)翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "openai"
        self.label = "OpenAI (官方/中转)"
        self.models = ["gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-4o-mini"]
        self.enabled = True
        self.default_model = "gpt-3.5-turbo"
        self.base_url = "https://api.openai.com/v1"
        self.api_key_url = "https://platform.openai.com/api-keys"

class OpenRouterConfig(TranslationServiceConfig):
    """OpenRouter 翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "openrouter"
        self.label = "OpenRouter"
        self.models = []
        self.enabled = True
        self.default_model = ""
        self.base_url = "https://openrouter.ai/api/v1"
        self.api_key_url = "https://openrouter.ai/keys"

 

class LMStudioConfig(TranslationServiceConfig):
    """LM Studio翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "lmstudio"
        self.label = "LM Studio (本地运行)"
        self.models = []  # 模型列表将通过API动态获取
        self.enabled = True
        self.requires_model_id = False
        self.default_model = ""
        self.model_selection_enabled = True
        self.host = "http://localhost"
        self.port = "1234"
        self.api_key_url = "https://lmstudio.ai/"
        
    @property
    def api_base(self) -> str:
        """获取API基础URL"""
        return f"{self.host}:{self.port}"

class OllamaConfig(TranslationServiceConfig):
    """Ollama本地大模型翻译服务配置"""
    def __init__(self):
        super().__init__()
        self.name = "ollama"
        self.label = "Ollama (本地运行)"
        self.models = []  # 模型列表将通过API动态获取
        self.enabled = True
        self.requires_model_id = False
        self.default_model = ""
        self.model_selection_enabled = True
        self.host = "http://localhost"
        self.port = "11434"
        self.api_key_url = "https://ollama.com/" # Ollama usually doesn't need key, but link to site
        
    @property
    def api_base(self) -> str:
        """获取API基础URL"""
        return f"{self.host}:{self.port}"

class TranslationServices:
    """翻译服务管理器"""
    def __init__(self):
        self.services = {
            "doubao": DoubaoConfig(),
            "aliyun": AliyunConfig(),
            "deepseek": DeepSeekConfig(),
            "moonshot": MoonshotConfig(),
            "zhipu": ZhipuConfig(),
            "siliconflow": SiliconFlowConfig(),
            "openai": OpenAIConfig(),
            "openrouter": OpenRouterConfig(),
            "ollama": OllamaConfig(),
            "lmstudio": LMStudioConfig(),
        }
    
    def get_service(self, name: str) -> TranslationServiceConfig:
        """获取指定服务的配置"""
        return self.services.get(name)
    
    def get_enabled_services(self) -> list:
        """获取所有启用的服务"""
        return [s for s in self.services.values() if s.enabled]

class TranslationConfig:
    """翻译配置类"""
    
    # 需要保持原样的大写类型值
    PRESERVED_TYPES = {
        'IMAGE', 'MASK', 'MODEL', 'CROP_DATA', 'ZIP', 'PDF', 'CSV',
        'INT', 'FLOAT', 'BOOLEAN', 'STRING', 'BBOX_LIST'
    }
    
    # 需要保持原样的技术参数键名
    PRESERVED_KEYS = {
        'width', 'height', 'width_old', 'height_old', 'job_id', 'user_id',
        'base64_string', 'image_quality', 'image_format'
    }
    
    # 通用参数翻译映射
    COMMON_TRANSLATIONS = {
        'image': '图像',
        'mask': '遮罩',
        'model': '模型',
        'processor': '处理器',
        'device': '设备',
        'bbox': '边界框',
        'samples': '样本',
        'operation': '操作',
        'guide': '引导图',
        'source': '源',
        'destination': '目标',
        'threshold': '阈值',
        'radius': '半径',
        'epsilon': 'epsilon',
        'contrast': '对比度',
        'brightness': '亮度',
        'saturation': '饱和度',
        'hue': '色调',
        'gamma': '伽马值',
        'index': '索引',
        'position': '位置',
        'size': '大小',
        'scale': '缩放',
        'dilation': '膨胀',
        'count': '计数',
        'result': '结果'
    }
    ERROR_LOCALIZATION = {
        400: {"title": "请求参数不合法", "reason": "请求格式或参数不符合接口要求", "solution": "检查模型是否支持该参数，减少请求体大小，确保JSON结构有效", "params": {"建议": "移除缩进、分批发送、验证JSON"}},
        401: {"title": "认证失败", "reason": "API密钥无效、过期或未授权", "solution": "更新或重新配置API密钥，确认Key与服务匹配", "params": {"建议": "在设置中重新输入并保存API Key"}},
        403: {"title": "权限不足", "reason": "账户或密钥缺少执行该操作的权限", "solution": "为密钥开通相应权限或更换具备权限的密钥", "params": {"建议": "检查控制台的Key权限范围"}},
        404: {"title": "资源不存在", "reason": "模型ID或接口地址无效", "solution": "确认模型ID是否正确，检查Base URL设置", "params": {"建议": "使用服务提供商的兼容API地址"}},
        408: {"title": "请求超时", "reason": "服务响应过慢或网络不稳定", "solution": "延长超时时间，降低并发，重试请求", "params": {"建议": "调整超时为300秒以上并分批"}},
        409: {"title": "请求冲突", "reason": "短时间内重复或相互冲突的请求", "solution": "错峰发送请求，避免重复提交", "params": {"建议": "序列化批次或使用去重策略"}},
        413: {"title": "请求体过大", "reason": "发送的内容超过提供商限制", "solution": "减少单批节点数量，移除缩进与冗余字段", "params": {"建议": "批次大小设为3-6，移除indent"}},
        429: {"title": "请求过于频繁", "reason": "触发速率限制或配额用尽", "solution": "采用退避重试，降低并发或切换备用模型", "params": {"建议": "指数退避2-4-8-...秒；并发≤4"}},
        500: {"title": "服务内部错误", "reason": "提供商服务异常", "solution": "稍后重试或切换到健康的备用模型", "params": {"建议": "记录时间窗口并避开高峰期"}},
        502: {"title": "网关错误", "reason": "上游服务不可用或路由故障", "solution": "重试或更换提供商路由", "params": {"建议": "切换至稳定路由"}},
        503: {"title": "服务不可用", "reason": "服务暂时停运或拥堵", "solution": "延长重试间隔或切换备用模型", "params": {"建议": "间隔≥10秒，并发≤2"}},
        504: {"title": "网关超时", "reason": "上游响应超时", "solution": "增加超时和间隔，减少负载", "params": {"建议": "超时≥300秒，批次≤4"}}
    }
    RATE_LIMIT_RULES = {
        "openrouter:google": {"suggested_concurrency": 3, "min_interval_sec": 2, "notes": "免费路由易限流，建议绑定上游密钥或使用备用模型"},
        "openrouter:general": {"suggested_concurrency": 4, "min_interval_sec": 2, "notes": "保持批次适中并采用退避重试"},
        "siliconflow": {"suggested_concurrency": 5, "min_interval_sec": 1, "notes": "建议使用Qwen或DeepSeek系列以获得稳定JSON输出"},
        "zhipu": {"suggested_concurrency": 6, "min_interval_sec": 1, "notes": "优先选择glm-4-flash进行结构化翻译"},
        "aliyun": {"suggested_concurrency": 5, "min_interval_sec": 1, "notes": "qwen-plus较适合批量JSON"},
        "moonshot": {"suggested_concurrency": 3, "min_interval_sec": 2, "notes": "建议降低批次，避免长文本一次性发送"},
        "deepseek": {"suggested_concurrency": 5, "min_interval_sec": 1, "notes": "返回可能包含思考过程，注意解析"},
        "openai": {"suggested_concurrency": 4, "min_interval_sec": 2, "notes": "遵循官方速率限制文档"},
        "ollama": {"suggested_concurrency": 2, "min_interval_sec": 0, "notes": "本地模型受硬件限制，建议序列化批次"},
        "lmstudio": {"suggested_concurrency": 2, "min_interval_sec": 0, "notes": "本地模型受硬件限制，建议序列化批次"}
    }
    @staticmethod
    def localize_error(code: int, provider: str = "", raw: str = "") -> dict:
        info = TranslationConfig.ERROR_LOCALIZATION.get(code, None)
        if not info:
            return {"code": code, "title": "未知错误", "reason": "未识别的错误类型", "solution": "查看原始信息并联系提供商或更换模型", "params": {"原始信息": raw}, "provider": provider}
        return {"code": code, **info, "provider": provider, "raw": raw}
    
    # 人体部位翻译映射
    BODY_PART_TRANSLATIONS = {
        'background': '背景',
        'skin': '皮肤',
        'nose': '鼻子',
        'eye': '眼睛',
        'eye_g': '眼镜',
        'brow': '眉毛',
        'ear': '耳朵',
        'mouth': '嘴巴',
        'lip': '嘴唇',
        'hair': '头发',
        'hat': '帽子',
        'neck': '脖子',
        'cloth': '衣服'
    }
    
    # 方向和位置翻译映射
    DIRECTION_TRANSLATIONS = {
        # 前缀
        'l_': '左',
        'r_': '右',
        'u_': '上',
        'b_': '下',
        # 后缀
        '_l': '左',
        '_r': '右',
        '_t': '上',
        '_b': '下'
    }
    
    @classmethod
    def get_translation(cls, text: str) -> str:
        """获取文本的翻译
        
        Args:
            text: 要翻译的文本
            
        Returns:
            str: 翻译后的文本，如果没有找到翻译则返回原文
        """
        # 1. 检查是否是保留类型
        if text.upper() in cls.PRESERVED_TYPES:
            return text
            
        # 2. 检查是否在通用翻译中
        if text.lower() in cls.COMMON_TRANSLATIONS:
            return cls.COMMON_TRANSLATIONS[text.lower()]
            
        # 3. 检查是否是人体部位
        if text in cls.BODY_PART_TRANSLATIONS:
            return cls.BODY_PART_TRANSLATIONS[text]
            
        # 4. 检查是否包含方向前缀/后缀
        for prefix, direction in cls.DIRECTION_TRANSLATIONS.items():
            if text.startswith(prefix) or text.endswith(prefix):
                base = text.replace(prefix, '')
                if base in cls.BODY_PART_TRANSLATIONS:
                    return f"{direction}{cls.BODY_PART_TRANSLATIONS[base]}"
                    
        return text
    
    @classmethod
    def should_preserve_key(cls, key: str) -> bool:
        """检查是否应该保持键名不变
        
        Args:
            key: 键名
            
        Returns:
            bool: 是否应该保持不变
        """
        return key.lower() in cls.PRESERVED_KEYS
