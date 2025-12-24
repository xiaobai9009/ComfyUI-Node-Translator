import os
import sys

# Fix TCL/TK environment variables for Windows/VirtualEnv compatibility
# This handles cases where incorrect environment variables (e.g. from PyInstaller) cause TclError
if "TCL_LIBRARY" in os.environ and "_MEI" in os.environ["TCL_LIBRARY"]:
    del os.environ["TCL_LIBRARY"]
if "TK_LIBRARY" in os.environ and "_MEI" in os.environ["TK_LIBRARY"]:
    del os.environ["TK_LIBRARY"]

# Ensure we point to the correct Tcl/Tk libs if possible
if sys.platform == 'win32':
    try:
        import tkinter
        # If imports work, we might still need to fix paths for TkinterDnD
        base_path = os.path.dirname(os.path.dirname(tkinter.__file__)) # Lib
        tcl_path = os.path.join(base_path, 'tcl8.6')
        if not os.path.exists(tcl_path):
             # Try sys.base_prefix
             tcl_path = os.path.join(sys.base_prefix, 'tcl', 'tcl8.6')
        
        if os.path.exists(tcl_path) and "TCL_LIBRARY" not in os.environ:
             os.environ["TCL_LIBRARY"] = tcl_path
             os.environ["TK_LIBRARY"] = tcl_path.replace('tcl8.6', 'tk8.6')
    except:
        pass

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from tkinterdnd2 import *
import threading
import json
import time
import logging
import shutil
import webbrowser
import subprocess
from typing import List, Dict, Optional

from src.node_parser import NodeParser
from src.translator import Translator
from src.file_utils import FileUtils
from src.translation_config import TranslationServices
from src.diff_tab import DiffTab
from src.ollama_translator import OllamaTranslator
from src.lmstudio_translator import LMStudioTranslator
from src.siliconflow_translator import SiliconFlowTranslator

class TextHandler(logging.Handler):
    """自定义日志处理器，支持富文本、智能滚动和性能优化"""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self._pending_messages = []
        self._update_scheduled = False
        self.auto_scroll = True
        self.last_yview = (0.0, 1.0)
        
        # 配置标签样式
        self._configure_tags()
        
        # 绑定滚动事件
        self._bind_events()

    def _configure_tags(self):
        """配置文本标签颜色"""
        try:
            # 确保 text_widget 是实际的 Text 控件
            # ScrolledText 是 Frame，需要获取内部 Text
            if isinstance(self.text_widget, scrolledtext.ScrolledText):
                self.text_impl = self.text_widget.frame.children.get('!text', self.text_widget)
            else:
                self.text_impl = self.text_widget

            self.text_widget.tag_config("timestamp", foreground="#555555")
            self.text_widget.tag_config("error", foreground="#8b0000") # 墨红色
            self.text_widget.tag_config("warning", foreground="#ffaa00") # 橙色
            self.text_widget.tag_config("success", foreground="#006400") # 墨绿色
            self.text_widget.tag_config("info", foreground="#000000") # 黑色
            self.text_widget.tag_config("step", foreground="#0066cc") # 蓝色
            self.text_widget.tag_config("node", foreground="#9933cc") # 紫色
            self.text_widget.tag_config("highlight", background="#eeeeee") # 高亮背景
        except Exception:
            pass

    def _bind_events(self):
        """绑定滚动相关事件"""
        try:
            # 绑定鼠标滚轮
            self.text_widget.bind('<MouseWheel>', self._on_scroll)
            self.text_widget.bind('<Button-4>', self._on_scroll) # Linux
            self.text_widget.bind('<Button-5>', self._on_scroll) # Linux
            
            # 绑定拖动
            self.text_widget.bind('<B1-Motion>', self._on_drag)
            
            # 绑定滚动条操作 (如果能获取到滚动条)
            if hasattr(self.text_widget, 'vbar'):
                self.text_widget.vbar.bind('<ButtonRelease-1>', self._check_scroll_position)
                self.text_widget.vbar.bind('<B1-Motion>', self._check_scroll_position)
        except Exception:
            pass

    def _on_scroll(self, event):
        """处理鼠标滚轮事件"""
        # 简单的判断：如果用户向上滚动，暂停自动滚动
        # 滚轮向下且到底部，恢复自动滚动
        try:
            if event.delta > 0 or event.num == 4: # 向上滚动
                self.auto_scroll = False
            else: # 向下滚动
                self._check_scroll_position()
        except:
            pass

    def _on_drag(self, event):
        """处理拖动事件"""
        self._check_scroll_position()

    def _check_scroll_position(self, event=None):
        """检查当前滚动位置，决定是否恢复自动滚动"""
        try:
            # yview 返回 (top, bottom) 比例，1.0 表示在底部
            pos = self.text_widget.yview()
            # 如果底部接近 1.0 (允许微小误差)，则恢复自动滚动
            if pos[1] >= 0.99:
                self.auto_scroll = True
            else:
                self.auto_scroll = False
        except:
            pass

    def _emit_deprecated(self, record):
        msg = self.format(record)
        try:
            import logging as _logging
            tags = []
            
            # 时间戳
            timestamp = time.strftime('%H:%M:%S')
            
            # 解析消息内容确定标签
            lower_msg = msg.lower()
            
            # 错误
            if record.levelno >= _logging.ERROR or any(k in msg for k in ['错误', '失败', '异常', 'Error', 'Failed']):
                tags.append("error")
                icon = '🚨'
            # 警告
            elif record.levelno >= _logging.WARNING or any(k in msg for k in ['警告', '注意', 'Warning', '策略', '限流']):
                tags.append("warning")
                icon = '⚠️'
            # 成功
            elif any(k in msg for k in ['成功', '完成', '已保存', 'Success', 'Done']):
                tags.append("success")
                icon = '✅'
            # 步骤/阶段
            elif any(k in msg for k in ['[准备]', '[翻译]', '[验证]', '[统计]', '[二次筛查]']):
                tags.append("step")
                icon = ' '
            else:
                tags.append("info")
                icon = ' '

            # 提取节点名称 (假设格式中有节点名)
            # 这里可以做更复杂的正则匹配
            
            formatted_msg = f"[{timestamp}] {icon} {msg}"
            self._pending_messages.append((formatted_msg, tags))
            
        except Exception:
            self._pending_messages.append((msg, ["info"]))
        
        # 批量更新UI
        if not self._update_scheduled:
            self._update_scheduled = True
            self.text_widget.after(50, self._flush_messages) # 提高刷新频率到 50ms
    
    def _flush_messages(self):
        """批量刷新消息到UI"""
        if self._pending_messages:
            self.text_widget.config(state='normal')
            
            # 锁定更新以减少闪烁
            for segments in self._pending_messages:
                for text, tags in segments:
                    self.text_widget.insert(tk.END, text, tuple(tags))
                self.text_widget.insert(tk.END, '\n')
            
            # 缓冲区清理
            content_end = self.text_widget.index(tk.END)
            line_count = int(content_end.split('.')[0])
            if line_count > 5000: # 限制最大行数
                self.text_widget.delete('1.0', f'{line_count - 4000}.0')
            
            if self.auto_scroll:
                self.text_widget.see(tk.END)
                
            self.text_widget.config(state='disabled')
            self._pending_messages.clear()
        self._update_scheduled = False

    def emit(self, record):
        msg = self.format(record)
        try:
            import logging as _logging
            
            timestamp = time.strftime('%H:%M:%S')
            base_tags = []
            icon = '📌'
            
            # Determine icon and base tags
            if record.levelno >= _logging.ERROR or any(k in msg for k in ['错误', '失败', '异常', 'Error', 'Failed']):
                base_tags.append("error")
                icon = '🚨'
            elif record.levelno >= _logging.WARNING or any(k in msg for k in ['警告', '注意', 'Warning', '策略', '限流']):
                base_tags.append("warning")
                icon = '⚠️'
            elif any(k in msg for k in ['成功', '完成', '已保存', 'Success', 'Done']):
                base_tags.append("success")
                icon = '✅'
            elif any(k in msg for k in ['[准备]', '[翻译]', '[验证]', '[统计]', '[二次筛查]']):
                base_tags.append("step")
                icon = '🔄'
            else:
                base_tags.append("info")
                
            formatted_segments = []
            # 添加时间戳和图标
            formatted_segments.append((f"[{timestamp}] {icon} ", ["timestamp"]))
            
            # 特殊解析：高亮翻译步骤中的节点名称
            # 假设格式: [翻译] 第 x/y 批: NodeA, NodeB
            if '[翻译]' in msg and ':' in msg:
                try:
                    prefix, nodes_str = msg.split(':', 1)
                    formatted_segments.append((prefix + ": ", base_tags))
                    
                    # 分割并高亮节点名
                    nodes = nodes_str.split(',')
                    for i, node in enumerate(nodes):
                        # 去除空白
                        node_clean = node.strip()
                        # 添加前导空格(如果原字符串有)
                        pre_space = " " if node.startswith(" ") else ""
                        formatted_segments.append((pre_space + node_clean, ["node"]))
                        if i < len(nodes) - 1:
                            formatted_segments.append((",", base_tags))
                except:
                    formatted_segments.append((msg, base_tags))
            elif "翻译任务结束" in msg:
                try:
                    # 格式: "翻译任务结束。成功: X" 或 "翻译任务结束。成功: X, 失败: Y"
                    import re
                    # 先添加前缀
                    formatted_segments.append(("翻译任务结束。", ["info"]))
                    
                    # 提取成功
                    s = re.search(r'(成功:\s*\d+)', msg)
                    if s:
                        formatted_segments.append((" " + s.group(1), ["success"]))
                        
                    # 提取失败
                    f = re.search(r'(失败:\s*\d+)', msg)
                    if f:
                        if s: formatted_segments.append((",", ["info"]))
                        formatted_segments.append((" " + f.group(1), ["error"]))
                        
                    # 如果匹配失败（预防万一），回退到默认
                    if not s and not f:
                        formatted_segments.pop() # remove prefix
                        formatted_segments.append((msg, base_tags))
                except:
                    formatted_segments.append((msg, base_tags))
            else:
                formatted_segments.append((msg, base_tags))
                
            self._pending_messages.append(formatted_segments)
            
        except Exception:
            self._pending_messages.append([(msg, ["info"])])
        
        # 批量更新UI
        if not self._update_scheduled:
            self._update_scheduled = True
            self.text_widget.after(50, self._flush_messages) # 提高刷新频率到 50ms

class ComfyUITranslator:
    def __init__(self, root):
        self.root = root
        self.root.title("comfyui插件翻译-ZYF修改版")
        
        # 设置暗色主题
        self._setup_theme()
        
        # 设置最小窗口大小
        self.root.minsize(900, 800)
        
        # 获取屏幕尺寸
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # 设置窗口初始大小为屏幕的 70%
        window_width = int(screen_width * 0.7)
        window_height = int(screen_height * 0.7)
        
        # 确保窗口不小于最小尺寸
        window_width = max(window_width, 900)
        window_height = max(window_height, 800)
        
        # 计算窗口位置使其居中
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        # 设置窗口大小和位置
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # 配置根窗口的网格权重
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # 创建主框架
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # 加载配置
        self.config = self._load_config()
        self.translation_services = TranslationServices()
        
        # 创建标签页
        self.tab_control = ttk.Notebook(self.main_frame)
        self.tab_control.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # 创建标签页内容
        self.translation_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.translation_tab, text="翻译功能")
        
        self.diff_tab = DiffTab(self.tab_control)
        self.tab_control.add(self.diff_tab, text="对比功能")
        
        self.console_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.console_tab, text="控制台")
        self.setup_console_ui()
        
        self.help_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.help_tab, text="操作说明")
        self.setup_help_ui()

        # 初始化属性
        self.translating = False
        self.detected_nodes = {}
        self.json_window = None
        self.work_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
        os.makedirs(self.work_dir, exist_ok=True)
        
        self.folder_path = tk.StringVar()
        self.plugin_folders = []
        self.failed_records = [] # 记录失败的插件信息

        # 初始化UI
        self.setup_translation_ui()

    def _setup_theme(self):
        """配置暗色主题"""
        style = ttk.Style()
        
        # 使用 clam 主题作为基础，因为它支持较好的自定义
        try:
            style.theme_use('clam')
        except:
            pass
            
        # 配色：主背景 #8fa5b1，显示框背景 #87baab
        bg_color = "#8fa5b1"
        fg_color = "#000000"
        field_bg = "#87baab"
        select_bg = "#4b6eaf"
        panel_bg = "#8fa5b1"
        
        # 配置全局样式
        style.configure(".", 
            background=bg_color, 
            foreground=fg_color,
            fieldbackground=field_bg,
            troughcolor=bg_color,
            selectbackground=select_bg
        )
        
        # 配置特定组件
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, foreground=fg_color)
        style.configure("TButton", 
            background=field_bg, 
            foreground=fg_color,
            borderwidth=1,
            focusthickness=3,
            focuscolor=select_bg
        )
        # 专用于图标按钮，移除额外内边距和焦点粗边框以使图标居中
        style.configure("Icon.TButton",
            background=field_bg,
            foreground=fg_color,
            padding=(4, 2),
            focusthickness=0,
            anchor="center"
        )
        style.map("TButton",
            background=[("active", "#4c5052"), ("pressed", "#5c6164")],
            foreground=[("disabled", "#808080")]
        )
        
        style.configure("TEntry", 
            fieldbackground=field_bg,
            foreground=fg_color,
            insertcolor=fg_color
        )
        
        style.configure("TCombobox", 
            fieldbackground=field_bg,
            background=field_bg,
            foreground=fg_color,
            arrowcolor=fg_color
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", field_bg)],
            selectbackground=[("readonly", select_bg)],
            selectforeground=[("readonly", fg_color)]
        )
        
        style.configure("TLabelframe", 
            background=bg_color, 
            foreground=fg_color,
            labelmargins=(5, 0)
        )
        style.configure("TLabelframe.Label", 
            background=bg_color, 
            foreground=fg_color
        )
        
        style.configure("TNotebook", background=bg_color, tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab", 
            background=field_bg, 
            foreground=fg_color, 
            padding=[10, 2]
        )
        style.map("TNotebook.Tab", 
            background=[["selected", field_bg]], 
            expand=[["selected", [1, 1, 1, 0]]]
        )

        # 设置根窗口背景
        self.root.configure(bg=bg_color)

    def center_toplevel(self, window, width, height):
        """居中显示弹窗"""
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        window.geometry(f"{width}x{height}+{x}+{y}")

    def setup_translation_ui(self):
        """设置翻译功能的用户界面"""
        # 服务选择框架
        service_frame = ttk.LabelFrame(self.translation_tab, text="翻译服务配置", padding=5)
        service_frame.pack(fill=tk.X, padx=10, pady=5)

        # 服务类型选择
        service_select_frame = ttk.Frame(service_frame)
        service_select_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(service_select_frame, text="服务类型:").pack(side=tk.LEFT)
        
        # 获取服务列表和标签
        self.service_map = {s.label: name for name, s in self.translation_services.services.items()}
        service_labels = list(self.service_map.keys())
        if not service_labels:
            enabled = self.translation_services.get_enabled_services()
            self.service_map = {s.label: s.name for s in enabled}
            service_labels = [s.label for s in enabled]
        
        self.service_label_var = tk.StringVar()
        self.service_combobox = ttk.Combobox(
            service_select_frame, 
            textvariable=self.service_label_var,
            values=service_labels,
            state="readonly",
            width=30
        )
        self.service_combobox.pack(side=tk.LEFT, padx=5)
        self.service_combobox.bind('<<ComboboxSelected>>', self.on_service_change)
        self.service_combobox['values'] = service_labels
        
        # API URL 链接
        self.api_url_label = ttk.Label(service_select_frame, text="获取API Key", cursor="hand2", foreground="#4b6eaf")
        self.api_url_label.pack(side=tk.LEFT, padx=10)
        self.api_url_label.bind("<Button-1>", lambda e: self.open_api_url())
        
        # 卸载模型按钮 (动态显示)
        self.unload_model_btn = ttk.Button(
            service_select_frame, 
            text="🗑️ 卸载模型", 
            width=12, 
            command=self.unload_model
        )
        
        # 服务配置区域容器
        self.service_configs = ttk.Frame(service_frame)
        self.service_configs.pack(fill=tk.X, padx=5, pady=5)
        
        # 初始化各服务配置控件
        self.service_widgets = {} # 存储各服务的控件变量
        self.service_frames = {}  # 存储各服务的Frame
        
        for name, service in self.translation_services.services.items():
            frame = ttk.Frame(self.service_configs)
            self.service_frames[name] = frame
            
            widgets = {}
            
            # 1. 基础URL/服务器地址 (针对本地服务 Ollama/LMStudio)
            if name in ["ollama", "lmstudio"]:
                ttk.Label(frame, text="服务器:", width=8).pack(side=tk.LEFT)
                default_base = getattr(service, "api_base", service.base_url or ("http://localhost:1234" if name == "lmstudio" else "http://localhost:11434"))
                host_var = tk.StringVar(value=self.config.get("api_configs", {}).get(name, {}).get("base_url", default_base))
                host_entry = ttk.Entry(frame, textvariable=host_var, width=40)
                host_entry.pack(side=tk.LEFT, padx=5)
                widgets["host"] = host_var
            
            # 2. API Key (针对非本地服务)
            elif name != "ollama" and name != "lmstudio":
                ttk.Label(frame, text="API密钥:", width=8).pack(side=tk.LEFT)
                key_var = tk.StringVar(value=self.config.get("api_keys", {}).get(name, ""))
                key_entry = ttk.Entry(frame, textvariable=key_var, width=50)
                try:
                    key_entry.configure(show="*")
                except Exception:
                    pass
                key_entry.pack(side=tk.LEFT, padx=5)
                # 使用闭包捕获 toggle_btn 变量
                toggle_btn = ttk.Button(frame, text="🙈", width=3, style="Icon.TButton")
                toggle_btn.configure(command=lambda e=key_entry, b=toggle_btn: self.toggle_api_key_visibility(e, b))
                toggle_btn.pack(side=tk.LEFT, padx=6)
                widgets["api_key"] = key_var

            # 3. 模型选择/输入
            ttk.Label(frame, text="模型:", width=6).pack(side=tk.LEFT, padx=(10, 0))
            model_var = tk.StringVar(value=self.config.get("model_ids", {}).get(name, service.default_model))
            widgets["model"] = model_var
            
            # 本地服务始终创建下拉框（即使为空，刷新后填充）
            if name in ["ollama", "lmstudio"]:
                model_combo = ttk.Combobox(frame, textvariable=model_var, values=service.models or [], width=30)
                model_combo.pack(side=tk.LEFT, padx=5)
                widgets["model_combo"] = model_combo
            else:
                history_values = self.config.get("model_history", {}).get(name, [])
                initial_values = history_values if history_values else (service.models if service.models else ([service.default_model] if service.default_model else []))
                model_combo = ttk.Combobox(frame, textvariable=model_var, values=initial_values, width=30)
                model_combo.pack(side=tk.LEFT, padx=5)
                widgets["model_combo"] = model_combo
                remove_btn = ttk.Button(frame, text="移除", width=8, command=lambda n=name: self.remove_model_history_entry(n))
                remove_btn.pack(side=tk.LEFT, padx=5)
                widgets["remove_btn"] = remove_btn
            
            if name in ["ollama", "lmstudio"]:
                refresh_btn = ttk.Button(frame, text="🔄 刷新模型", width=12, 
                                       command=lambda n=name: self.refresh_models(n))
                refresh_btn.pack(side=tk.LEFT, padx=5)
                widgets["refresh_btn"] = refresh_btn

            

            # 5. 生成参数（每个服务可独立设置）
            ttk.Label(frame, text="temperature:").pack(side=tk.LEFT, padx=(10, 0))
            temp_default = self.config.get("api_configs", {}).get(name, {}).get("temperature", 0.3)
            temp_var = tk.StringVar(value=str(temp_default))
            ttk.Entry(frame, textvariable=temp_var, width=6).pack(side=tk.LEFT, padx=5)
            widgets["temperature"] = temp_var

            ttk.Label(frame, text="top_p:").pack(side=tk.LEFT, padx=(10, 0))
            topp_default = self.config.get("api_configs", {}).get(name, {}).get("top_p", 0.95)
            topp_var = tk.StringVar(value=str(topp_default))
            ttk.Entry(frame, textvariable=topp_var, width=6).pack(side=tk.LEFT, padx=5)
            widgets["top_p"] = topp_var

            self.service_widgets[name] = widgets

        # 操作按钮区域
        btn_frame = ttk.Frame(service_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.test_api_btn = ttk.Button(btn_frame, text="⚙️ 测试API", width=15, command=self.test_api)
        self.test_api_btn.pack(side=tk.LEFT, padx=5)
        
        # 文件夹选择区域
        folder_frame = ttk.LabelFrame(self.translation_tab, text="插件选择", padding=5)
        folder_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 拖放区域
        drop_frame = ttk.Frame(folder_frame)
        drop_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.drop_area = tk.Text(drop_frame, height=4, width=60, bg="#87baab", fg="#000000")
        self.drop_area.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.drop_area.insert('1.0', 
            "第一步：打开comfyui\\custom_nodes文件夹\n"
            "第二步：选择需要翻译的插件文件夹，拖入该区域\n"
            "·可以多选后一次性拖入"
        )
        self.drop_area.configure(state='disabled')
        
        # 注册拖放
        try:
            self.drop_area.drop_target_register(DND_FILES)
            self.drop_area.dnd_bind('<<Drop>>', self.on_drop)
        except Exception as e:
            print(f"拖放功能初始化失败: {e}")

        # 文件夹显示和操作
        list_frame = ttk.Frame(folder_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.folder_path.set("未选择文件夹")
        path_label = ttk.Label(list_frame, textvariable=self.folder_path)
        path_label.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        
        self.plugins_text = scrolledtext.ScrolledText(list_frame, height=6, width=60, bg="#87baab", fg="#000000")
        self.plugins_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        list_btn_frame = ttk.Frame(list_frame)
        list_btn_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        ttk.Button(list_btn_frame, text="📂 选择文件夹", command=self.select_batch_folder, width=12).pack(pady=2)
        self.clear_folders_btn = ttk.Button(list_btn_frame, text="🗑️ 清空列表", command=self.clear_selected_folders, state=tk.DISABLED, width=12)
        self.clear_folders_btn.pack(pady=2)

        # 翻译控制区域
        control_frame = ttk.Frame(self.translation_tab)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 左侧按钮
        left_btn_frame = ttk.Frame(control_frame)
        left_btn_frame.pack(side=tk.LEFT)
        
        self.detect_btn = ttk.Button(left_btn_frame, text="🔍 执行检测", width=12, command=self.detect_nodes, state=tk.DISABLED)
        self.detect_btn.pack(side=tk.LEFT, padx=5)
        
        self.view_json_btn = ttk.Button(left_btn_frame, text="📄 查看JSON", width=12, command=self.view_json, state=tk.DISABLED)
        self.view_json_btn.pack(side=tk.LEFT, padx=5)
        
        self.start_btn = ttk.Button(left_btn_frame, text="⏳ 开始翻译", width=12, command=self.toggle_translation, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.retry_btn = ttk.Button(left_btn_frame, text="🔄 失败重译", width=12, command=self.retry_failed_translation, state=tk.DISABLED)
        self.retry_btn.pack(side=tk.LEFT, padx=5)
        
        self.view_btn = ttk.Button(left_btn_frame, text="📊 查看结果", width=12, command=self.view_results, state=tk.DISABLED)
        self.view_btn.pack(side=tk.LEFT, padx=5)
        
        # 右侧设置
        batch_frame = ttk.LabelFrame(control_frame, text="翻译参数", padding=5)
        batch_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        ttk.Label(batch_frame, text="并发数:").pack(side=tk.LEFT, padx=5)
        self.batch_size = tk.StringVar(value="6")
        ttk.Entry(batch_frame, textvariable=self.batch_size, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Label(batch_frame, text="(建议5-8)").pack(side=tk.LEFT)

        ttk.Label(batch_frame, text="翻译轮次:").pack(side=tk.LEFT, padx=10)
        self.rounds = tk.StringVar(value="2")
        ttk.Entry(batch_frame, textvariable=self.rounds, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Label(batch_frame, text="(1-5)").pack(side=tk.LEFT)
        
        self.only_tooltips = tk.BooleanVar(value=False)
        # 使用 tk.Checkbutton 替代 ttk.Checkbutton，以解决 clam 主题下勾选显示为叉号(X)的问题
        self.only_tooltips_cb = tk.Checkbutton(
            batch_frame, 
            text="仅译tooltip", 
            variable=self.only_tooltips,
            background="#8fa5b1",      # 与主背景色保持一致
            foreground="#000000",
            activebackground="#8fa5b1",
            activeforeground="#000000",
            selectcolor="#FFFFFF",     # 选中框内部为白色
            highlightthickness=0,
            bd=0
        )
        self.only_tooltips_cb.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(batch_frame, text="⚙️ 错误策略设置", command=self.open_error_policy_settings).pack(side=tk.LEFT, padx=10)
        
        # 日志区域
        log_frame = ttk.Frame(self.translation_tab)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, bg="#87baab", fg="#000000")
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        self.detail_text = scrolledtext.ScrolledText(log_frame, height=15) # 隐藏的详细日志
        self.strategy_status = tk.StringVar()
        ttk.Label(log_frame, text="策略状态:").pack(anchor=tk.W, padx=5, pady=2)
        self.strategy_label = ttk.Label(log_frame, textvariable=self.strategy_status)
        self.strategy_label.pack(fill=tk.X, padx=5, pady=2)

        self._load_saved_service_selection()

    def open_error_policy_settings(self):
        top = tk.Toplevel(self.root)
        top.title("错误策略设置")
        
        # 主题色
        bg_color = "#8fa5b1"
        field_bg = "#87baab"
        top.configure(bg=bg_color)
        
        # 居中显示
        self.center_toplevel(top, 450, 600)
        
        policy = self._load_error_policy()
        
        # 1. 重试策略
        ttk.Label(top, text="重试策略", background=bg_color).pack(anchor=tk.W, padx=10, pady=(10, 2))
        strategy_map = {"exponential": "指数退避", "fixed": "线性重试", "none": "不重试"}
        rev_strategy_map = {v: k for k, v in strategy_map.items()}
        
        current_strategy = policy.get("strategy", "exponential")
        strategy_var = tk.StringVar(value=strategy_map.get(current_strategy, "指数退避"))
        
        cb = ttk.Combobox(top, textvariable=strategy_var, values=list(strategy_map.values()), state="readonly")
        cb.pack(fill=tk.X, padx=10)
        
        # 2. 最大重试次数 (滑块)
        ttk.Label(top, text="最大重试次数", background=bg_color).pack(anchor=tk.W, padx=10, pady=(10, 2))
        retries_frame = ttk.Frame(top)
        retries_frame.pack(fill=tk.X, padx=10)
        
        retries_val = tk.IntVar(value=policy.get("max_retries", 5))
        retries_label = ttk.Label(retries_frame, text=str(retries_val.get()), width=3, background=bg_color)
        retries_label.pack(side=tk.RIGHT)
        
        def update_retries_label(val):
            retries_label.config(text=str(int(float(val))))
            
        retries_scale = ttk.Scale(retries_frame, from_=0, to=20, variable=retries_val, orient=tk.HORIZONTAL, command=update_retries_label)
        retries_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 3. 基础间隔 (滑块)
        ttk.Label(top, text="基础间隔(秒)", background=bg_color).pack(anchor=tk.W, padx=10, pady=(10, 2))
        delay_frame = ttk.Frame(top)
        delay_frame.pack(fill=tk.X, padx=10)
        
        delay_val = tk.IntVar(value=policy.get("base_delay_sec", 2))
        delay_label = ttk.Label(delay_frame, text=f"{delay_val.get()}s", width=4, background=bg_color)
        delay_label.pack(side=tk.RIGHT)
        
        def update_delay_label(val):
            delay_label.config(text=f"{int(float(val))}s")
            
        delay_scale = ttk.Scale(delay_frame, from_=0, to=60, variable=delay_val, orient=tk.HORIZONTAL, command=update_delay_label)
        delay_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 4. 备用模型优先级
        ttk.Label(top, text="备用模型优先级(当前服务)", background=bg_color).pack(anchor=tk.W, padx=10, pady=(10, 5))
        label = self.service_combobox.get()
        service_name = self.service_map.get(label)
        backups = self.config.get("backup_models", {}).get(service_name, [])
        hist = self.config.get("model_history", {}).get(service_name, [])
        items = backups if backups else hist
        
        lb = tk.Listbox(top, bg=field_bg, fg="#000000", selectmode=tk.SINGLE, height=10)
        for m in items:
            lb.insert(tk.END, m)
        lb.pack(fill=tk.BOTH, expand=True, padx=10)
        
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, padx=10, pady=10)
        
        def move_up():
            sel = lb.curselection()
            if not sel: return
            i = sel[0]
            if i == 0: return
            text = lb.get(i)
            lb.delete(i)
            lb.insert(i-1, text)
            lb.selection_set(i-1)
        
        def move_down():
            sel = lb.curselection()
            if not sel: return
            i = sel[0]
            if i >= lb.size()-1: return
            text = lb.get(i)
            lb.delete(i)
            lb.insert(i+1, text)
            lb.selection_set(i+1)
            
        ttk.Button(btns, text="上移", command=move_up).pack(side=tk.LEFT)
        ttk.Button(btns, text="下移", command=move_down).pack(side=tk.LEFT, padx=10)
        
        def save_policy():
            try:
                new_policy = {
                    "strategy": rev_strategy_map.get(strategy_var.get(), "exponential"),
                    "max_retries": int(retries_scale.get()),
                    "base_delay_sec": int(delay_scale.get())
                }
                self.config["error_policy"] = new_policy
                arr = [lb.get(i) for i in range(lb.size())]
                if "backup_models" not in self.config: self.config["backup_models"] = {}
                self.config["backup_models"][service_name] = arr
                
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=4, ensure_ascii=False)
                messagebox.showinfo("已保存", "错误策略与备用模型优先级已保存")
                top.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")
                
        ttk.Button(btns, text="保存", command=save_policy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="取消", command=top.destroy).pack(side=tk.RIGHT, padx=10)

    def _load_saved_service_selection(self):
        """加载保存的服务选择"""
        saved_service = self.config.get("current_service", "doubao")
        # 尝试匹配并加载
        found = False
        for label, name in self.service_map.items():
            if name == saved_service:
                try:
                    self.service_label_var.set(label)
                    self.service_combobox.set(label)
                    self.on_service_change()
                    found = True
                    api_cfg = self.config.get("api_configs", {}).get(saved_service, {})
                    if api_cfg and hasattr(self, "only_tooltips"):
                        self.only_tooltips.set(bool(api_cfg.get("only_tooltips")))
                except Exception as e:
                    self.log(f"加载服务 {saved_service} 失败: {e}")
                break
        
        if not found and self.service_map:
            # 默认选择第一个
            try:
                first_label = list(self.service_map.keys())[0]
                self.service_label_var.set(first_label)
                self.service_combobox.set(first_label)
                self.on_service_change()
                api_cfg = self.config.get("api_configs", {}).get(first_label, {})
                if api_cfg and hasattr(self, "only_tooltips"):
                    self.only_tooltips.set(bool(api_cfg.get("only_tooltips")))
            except Exception as e:
                self.log(f"加载默认服务失败: {e}")

    def on_service_change(self, event=None):
        """处理服务切换"""
        try:
            label = self.service_combobox.get()
            if not label: return
            
            service_name = self.service_map.get(label)
            if not service_name: return
            
            # 1. 隐藏所有配置Frame
            for frame in self.service_frames.values():
                frame.pack_forget()
                
            # 2. 显示当前服务Frame
            if service_name in self.service_frames:
                self.service_frames[service_name].pack(fill=tk.X)
                
            # 3. 更新API链接
            service_config = self.translation_services.get_service(service_name)
            if service_config and service_config.api_key_url:
                self.api_url_label.config(text=f"获取 {service_config.name} API Key", state="normal", cursor="hand2")
                self.current_api_url = service_config.api_key_url
            else:
                self.api_url_label.config(text="", state="disabled", cursor="")
                self.current_api_url = ""

            # 4. 卸载按钮显示
            if service_name in ["ollama", "lmstudio"]:
                self.unload_model_btn.pack(side=tk.LEFT, padx=5)
            else:
                self.unload_model_btn.pack_forget()
        except Exception as e:
            self.log(f"切换服务失败: {e}")

    def open_api_url(self):
        """打开API获取链接"""
        if hasattr(self, 'current_api_url') and self.current_api_url:
            webbrowser.open(self.current_api_url)

    def refresh_models(self, service_name):
        """刷新模型列表"""
        widgets = self.service_widgets.get(service_name)
        if not widgets or "refresh_btn" not in widgets: return
        
        btn = widgets["refresh_btn"]
        btn.config(state="disabled", text="刷新中...")
        
        def task():
            try:
                models = []
                if service_name == "ollama":
                    host = widgets["host"].get().strip()
                    translator = OllamaTranslator(base_url=host, model_id="")
                    models = translator.get_available_models()
                elif service_name == "lmstudio":
                    host = widgets["host"].get().strip()
                    translator = LMStudioTranslator(base_url=host, model_id="")
                    models = translator.get_available_models()
                
                
                def update_ui():
                    if models and "model_combo" in widgets:
                        widgets["model_combo"]['values'] = models
                        if not widgets["model"].get():
                            widgets["model"].set(models[0])
                        self.log(f"已刷新 {len(models)} 个模型")
                    else:
                        self.log("未找到可用模型")
                    btn.config(state="normal", text="刷新模型")
                
                self.root.after(0, update_ui)
            except Exception as e:
                err_msg = str(e)
                def on_error():
                    messagebox.showerror("错误", f"刷新失败: {err_msg}")
                    btn.config(state="normal", text="刷新模型")
                self.root.after(0, on_error)
                
        threading.Thread(target=task, daemon=True).start()

    def update_history_combobox(self, service_name):
        widgets = self.service_widgets.get(service_name)
        if not widgets: return
        if service_name not in ["ollama", "lmstudio"] and "model_combo" in widgets:
            values = self.config.get("model_history", {}).get(service_name, [])
            widgets["model_combo"]['values'] = values

    def remove_model_history_entry(self, service_name):
        widgets = self.service_widgets.get(service_name)
        if not widgets or "model_combo" not in widgets: return
        selected = widgets["model_combo"].get().strip()
        if not selected:
            self.log("未选择历史模型")
            return
        hist_map = self.config.get("model_history", {})
        hist = hist_map.get(service_name, [])
        if selected in hist:
            hist = [m for m in hist if m != selected]
            self.config.setdefault("model_history", {})[service_name] = hist
            try:
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=4, ensure_ascii=False)
            except Exception as e:
                self.log(f"保存配置失败: {e}")
            self.update_history_combobox(service_name)
            if widgets.get("model") and widgets["model"].get().strip() == selected:
                widgets["model"].set("")
            self.log(f"已移除模型 {selected}")
        else:
            self.log("模型不在历史列表中")

    def get_current_service_config(self):
        """获取当前UI配置的服务参数"""
        label = self.service_combobox.get()
        service_name = self.service_map.get(label)
        if not service_name: return None
        
        widgets = self.service_widgets.get(service_name)
        config = {
            "name": service_name,
            "model_id": widgets["model"].get().strip(),
            "base_url": None,
            "api_key": None,
            "temperature": None,
            "top_p": None
        }
        
        service_def = self.translation_services.get_service(service_name)
        
        if "host" in widgets:
            config["base_url"] = widgets["host"].get().strip()
        else:
            config["base_url"] = service_def.base_url
            
        if "api_key" in widgets:
            config["api_key"] = widgets["api_key"].get().strip()

        # 读取生成参数（服务级）
        try:
            t = float(widgets.get("temperature").get())
        except Exception:
            t = 0.3
        try:
            p = float(widgets.get("top_p").get())
        except Exception:
            p = 0.95
        config["temperature"] = t
        config["top_p"] = p
        config["only_tooltips"] = bool(getattr(self, "only_tooltips", None) and self.only_tooltips.get())
        # 错误策略设置
        policy = self._load_error_policy()
        config["error_policy"] = policy
        # 备用模型优先级
        backups = self.config.get("backup_models", {}).get(service_name, [])
        hist = self.config.get("model_history", {}).get(service_name, [])
        fallback_models = [m for m in backups if m and m != config["model_id"]]
        if not fallback_models:
            fallback_models = [m for m in hist if m and m != config["model_id"]]
        config["fallback_models"] = fallback_models
        
        return config

    def test_api(self):
        """测试API连接"""
        cfg = self.get_current_service_config()
        if not cfg: return
        
        if cfg["name"] not in ["ollama", "lmstudio"] and not cfg["api_key"]:
            messagebox.showerror("错误", "请输入API Key")
            return
            
        self.test_api_btn.config(state="disabled", text="测试中...")
        
        def task():
            try:
                # 使用通用Translator测试
                # 注意：Ollama/LMStudio/SiliconFlow 原本有专门的类，但如果它们兼容OpenAI格式，
                # 我们可以尝试使用通用Translator。如果不兼容，则需要保留特殊处理。
                # 鉴于之前有专门的Translator类，为了稳妥，我们根据类型判断。
                
                success = False
                if cfg["name"] == "ollama":
                    t = OllamaTranslator(base_url=cfg["base_url"], model_id=cfg["model_id"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    success = t.test_connection()
                elif cfg["name"] == "lmstudio":
                    t = LMStudioTranslator(base_url=cfg["base_url"], model_id=cfg["model_id"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    success = t.test_connection()
                elif cfg["name"] == "siliconflow":
                    t = SiliconFlowTranslator(api_key=cfg["api_key"], model_id=cfg["model_id"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    success = t.test_connection()
                else:
                    # 通用 OpenAI 兼容测试
                    t = Translator(api_key=cfg["api_key"], model_id=cfg["model_id"], base_url=cfg["base_url"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    success = t.test_connection()
                
                def on_finish():
                    if success:
                        self.log("API 连接测试成功！")
                        self._save_config() # 保存配置
                    else:
                        self.log("API 连接测试失败")
                    self.test_api_btn.config(state="normal", text="测试API")
                self.root.after(0, on_finish)
                
            except Exception as e:
                def on_error():
                    self.log(f"测试出错: {str(e)}")
                    self.test_api_btn.config(state="normal", text="测试API")
                self.root.after(0, on_error)
        
        threading.Thread(target=task, daemon=True).start()

    def _save_config(self):
        """保存当前配置到 config.json"""
        cfg = self.get_current_service_config()
        if not cfg: return
        
        # 更新 self.config
        if "api_keys" not in self.config: self.config["api_keys"] = {}
        if "model_ids" not in self.config: self.config["model_ids"] = {}
        if "api_configs" not in self.config: self.config["api_configs"] = {}
        if "model_history" not in self.config: self.config["model_history"] = {}
        
        name = cfg["name"]
        self.config["current_service"] = name
        self.config["model_ids"][name] = cfg["model_id"]
        self._add_model_to_history(name, cfg["model_id"])
        
        if cfg["api_key"]:
            self.config["api_keys"][name] = cfg["api_key"]
            
        if name in ["ollama", "lmstudio"]:
            if name not in self.config["api_configs"]: self.config["api_configs"][name] = {}
            self.config["api_configs"][name]["base_url"] = cfg["base_url"]
            
        # 保存服务级生成参数
        if cfg["name"] not in self.config["api_configs"]:
            self.config["api_configs"][cfg["name"]] = {}
        self.config["api_configs"][cfg["name"]]["temperature"] = cfg.get("temperature", 0.3)
        self.config["api_configs"][cfg["name"]]["top_p"] = cfg.get("top_p", 0.95)
        self.config["api_configs"][cfg["name"]]["only_tooltips"] = bool(cfg.get("only_tooltips"))
        # 保存错误策略
        self.config["error_policy"] = cfg.get("error_policy", self.config.get("error_policy", {}))
        # 保存备用模型优先级
        if "backup_models" not in self.config: self.config["backup_models"] = {}
        self.config["backup_models"][name] = cfg.get("fallback_models", self.config["backup_models"].get(name, []))

        try:
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

        self.update_history_combobox(name)

    def _load_error_policy(self):
        policy = self.config.get("error_policy", {})
        if "max_retries" not in policy: policy["max_retries"] = 5
        if "base_delay_sec" not in policy: policy["base_delay_sec"] = 2
        if "strategy" not in policy: policy["strategy"] = "exponential"
        return policy

    def _parse_error_info(self, err_text: str) -> dict:
        info = {"code": None, "provider": None, "raw": None}
        try:
            import re
            m = re.search(r'Error code:\s*(\d+)', err_text)
            if m: info["code"] = int(m.group(1))
            p = re.search(r"provider_name['\"]?:\s*['\"]([^'\"]+)['\"]", err_text)
            if p: info["provider"] = p.group(1)
            r = re.search(r"raw['\"]?:\s*['\"](.*?)['\"]", err_text)
            if r: info["raw"] = r.group(1)
        except Exception:
            pass
        return info

    def _add_model_to_history(self, service_name, model_id):
        if not model_id: return
        hist = self.config.setdefault("model_history", {}).get(service_name, [])
        if model_id not in hist:
            hist.append(model_id)
            self.config["model_history"][service_name] = hist

    # --- 以下方法保持原有逻辑，只需做少量适配 ---

    def log(self, message):
        """添加日志"""
        # 基于关键词添加图标前缀，以提升辨识度
        icon = '📌'
        mlow = message.lower()
        if any(k in message for k in ['错误', '失败', '异常']) or any(k in mlow for k in ['error', 'failed']):
            icon = '🚨'
            logging.error(message)
        elif any(k in message for k in ['警告', '注意']) or 'warn' in mlow:
            icon = '⚠️'
            logging.warning(message)
        elif any(k in message for k in ['成功', '完成', '已保存', '已生成']) or any(k in mlow for k in ['success', 'done']):
            icon = '😊'
            logging.info(message)
        else:
            logging.info(message)
        self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {icon} {message}\n")
        self.log_text.see(tk.END)

    def toggle_api_key_visibility(self, entry_widget, btn_widget=None):
        try:
            current = entry_widget.cget("show")
            if current == "*":
                entry_widget.configure(show="")
                if btn_widget: btn_widget.configure(text="👁️")
            else:
                entry_widget.configure(show="*")
                if btn_widget: btn_widget.configure(text="🙈")
        except Exception:
            pass

    def select_folder(self): # 单文件夹选择 (保留兼容性)
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)
            self.plugin_folders = [folder]
            self.display_plugin_list()
            self.detect_btn.config(state=tk.NORMAL)
            self.clear_folders_btn.config(state=tk.NORMAL)

    def select_batch_folder(self):
        try:
            top = tk.Toplevel(self.root)
            top.title("选择多个插件文件夹")
            # 居中显示
            self.center_toplevel(top, 700, 800)
            # 主题色
            bg_color = "#8fa5b1"
            field_bg = "#87baab"
            btn_hover_bg = "#7a95a1"  # 悬停颜色
            top.configure(bg=bg_color)
            
            root_var = tk.StringVar()
            init_dir = self.config.get("last_open_dir", "")
            if not init_dir or not os.path.isdir(init_dir):
                init_dir = self.folder_path.get()
            if not init_dir or not os.path.isdir(init_dir):
                init_dir = os.path.expanduser("~")
            root_var.set(init_dir)
            
            # 加载保存的排序状态
            sort_state = self.config.get("sort_state", {"field": "default", "direction": "asc"})
            current_sort = {
                "field": sort_state.get("field", "default"),
                "direction": sort_state.get("direction", "asc")
            }

            frm = ttk.Frame(top)
            frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # 顶部地址栏区域
            top_bar = ttk.Frame(frm)
            top_bar.pack(fill=tk.X, pady=(0, 4))
            ttk.Label(top_bar, text="根目录").pack(side=tk.LEFT)
            
            def browse_root():
                d = filedialog.askdirectory(title="选择根目录")
                if d:
                    root_var.set(d)
                    load_dirs()
            
            ttk.Button(top_bar, text="浏览", command=browse_root).pack(side=tk.RIGHT)
            entry = ttk.Entry(top_bar, textvariable=root_var)
            entry.pack(fill=tk.X, padx=5)

            # 排序工具栏
            sort_frame = ttk.Frame(frm)
            sort_frame.pack(fill=tk.X, pady=4)
            
            # 列表数据容器
            # items结构: [{'path': full_path, 'name': basename, 'mtime': timestamp}]
            self.list_items = [] 
            
            def get_sort_icon(field):
                if current_sort["field"] != field:
                    return ""
                return "↑" if current_sort["direction"] == "asc" else "↓"

            def update_sort_buttons():
                name_icon = get_sort_icon("name")
                time_icon = get_sort_icon("time")
                name_sort_btn.config(text=f"名称 {name_icon}")
                time_sort_btn.config(text=f"修改时间 {time_icon}")

            def sort_action(field):
                # 状态流转: Default -> Asc -> Desc -> Default
                # 但如果是切换字段，则直接设为 Asc
                
                if current_sort["field"] == field:
                    if current_sort["direction"] == "asc":
                        current_sort["direction"] = "desc"
                    elif current_sort["direction"] == "desc":
                        current_sort["field"] = "default"
                        current_sort["direction"] = "asc"
                    else:
                        # Should not happen if logic is strict, but reset to asc
                        current_sort["direction"] = "asc"
                else:
                    current_sort["field"] = field
                    current_sort["direction"] = "asc"
                
                # 保存状态
                self.config["sort_state"] = current_sort
                try:
                    with open('config.json', 'w', encoding='utf-8') as f:
                        json.dump(self.config, f, indent=4, ensure_ascii=False)
                except:
                    pass
                
                update_sort_buttons()
                refresh_list_view()

            # 排序按钮样式与悬停效果
            def create_hover_btn(parent, text, command):
                btn = tk.Button(parent, text=text, command=command, 
                              bg=bg_color, relief=tk.FLAT, padx=10)
                btn.bind("<Enter>", lambda e: btn.config(bg=btn_hover_bg))
                btn.bind("<Leave>", lambda e: btn.config(bg=bg_color))
                return btn

            name_sort_btn = create_hover_btn(sort_frame, "名称", lambda: sort_action("name"))
            name_sort_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            time_sort_btn = create_hover_btn(sort_frame, "修改时间", lambda: sort_action("time"))
            time_sort_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 列表区域
            lb = tk.Listbox(frm, selectmode=tk.EXTENDED, bg=field_bg, fg="#000000")
            sb = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=8)
            sb.pack(side=tk.LEFT, fill=tk.Y)
            
            # 当前显示的路径列表（对应Listbox中的行）
            current_paths = []

            def refresh_list_view():
                # 保存当前选中项的路径
                selected_paths = set()
                cur_sel = lb.curselection()
                for i in cur_sel:
                    if i < len(current_paths):
                        selected_paths.add(current_paths[i])
                
                # 排序
                sorted_items = list(self.list_items)
                field = current_sort["field"]
                direction = current_sort["direction"]
                
                if field == "name":
                    sorted_items.sort(key=lambda x: x["name"].lower(), reverse=(direction == "desc"))
                elif field == "time":
                    sorted_items.sort(key=lambda x: x["mtime"], reverse=(direction == "desc"))
                else:
                    # Default: sort by name asc (base order)
                    sorted_items.sort(key=lambda x: x["name"].lower())

                # 更新显示
                lb.delete(0, tk.END)
                current_paths.clear()
                
                first_sel_index = -1
                
                for idx, item in enumerate(sorted_items):
                    lb.insert(tk.END, item["name"])
                    current_paths.append(item["path"])
                    # 恢复选中
                    if item["path"] in selected_paths:
                        lb.select_set(idx)
                        if first_sel_index == -1:
                            first_sel_index = idx
                
                # 确保选中项可见
                if first_sel_index != -1:
                    lb.see(first_sel_index)

            def load_dirs():
                self.list_items.clear()
                base = root_var.get()
                if not base or not os.path.isdir(base):
                    return
                try:
                    # 获取文件列表并缓存元数据
                    raw_items = os.listdir(base)
                    for name in raw_items:
                        full_path = os.path.join(base, name)
                        try:
                            mtime = os.path.getmtime(full_path)
                        except:
                            mtime = 0
                        self.list_items.append({
                            "name": name,
                            "path": full_path,
                            "mtime": mtime
                        })
                    
                    refresh_list_view()
                except Exception:
                    pass

            def select_all(event=None):
                lb.select_set(0, tk.END)
                return "break"
            lb.bind("<Control-a>", select_all)

            btns = ttk.Frame(frm)
            btns.pack(fill=tk.X, pady=8)
            
            def do_confirm():
                sel = lb.curselection()
                if not sel:
                    top.destroy()
                    return
                added = 0
                for i in sel:
                    p = current_paths[i]
                    if os.path.isfile(p):
                        p = os.path.dirname(p)
                    if p not in self.plugin_folders:
                        self.plugin_folders.append(p)
                        added += 1
                self.display_plugin_list()
                self.folder_path.set(f"已选择 {len(self.plugin_folders)} 个插件文件夹")
                self.detect_btn.config(state=tk.NORMAL)
                self.clear_folders_btn.config(state=tk.NORMAL)
                # 记忆路径
                self.config["last_open_dir"] = root_var.get()
                try:
                    with open('config.json', 'w', encoding='utf-8') as f:
                        json.dump(self.config, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass
                top.destroy()

            ttk.Button(btns, text="全选", command=select_all).pack(side=tk.LEFT)
            ttk.Button(btns, text="确定", command=do_confirm).pack(side=tk.RIGHT)
            ttk.Button(btns, text="取消", command=top.destroy).pack(side=tk.RIGHT, padx=8)
            
            # 初始化
            update_sort_buttons()
            load_dirs()
            
        except Exception as e:
            messagebox.showerror("错误", f"选择失败: {e}")

    def display_plugin_list(self):
        self.plugins_text.delete('1.0', tk.END)
        if self.plugin_folders:
            self.plugins_text.insert(tk.END, "待处理插件列表:\n\n")
            for i, folder in enumerate(self.plugin_folders, 1):
                self.plugins_text.insert(tk.END, f"{i}. {os.path.basename(folder)}\n   路径: {folder}\n\n")
        else:
            self.plugins_text.insert(tk.END, "未选择任何插件文件夹")

    def clear_selected_folders(self):
        self.plugin_folders = []
        self.folder_path.set("未选择文件夹")
        self.display_plugin_list()
        self.detect_btn.config(state=tk.DISABLED)
        self.clear_folders_btn.config(state=tk.DISABLED)

    def on_drop(self, event):
        try:
            data = event.data
            paths = self.root.tk.splitlist(data)
            added = False
            for path in paths:
                if os.path.isdir(path):
                    if path not in self.plugin_folders:
                        self.plugin_folders.append(path)
                        added = True
                elif os.path.isfile(path):
                    d = os.path.dirname(path)
                    if d not in self.plugin_folders:
                        self.plugin_folders.append(d)
                        added = True
            
            if added:
                self.display_plugin_list()
                self.folder_path.set(f"已选择 {len(self.plugin_folders)} 个插件文件夹")
                self.detect_btn.config(state=tk.NORMAL)
                self.clear_folders_btn.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("错误", f"拖放失败: {e}")

    def detect_nodes(self):
        if not self.plugin_folders:
            messagebox.showerror("错误", "请先选择插件文件夹")
            return
        
        self.detect_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.DISABLED)
        self.view_json_btn.config(state=tk.DISABLED)
        
        threading.Thread(target=self.batch_detection_task, daemon=True).start()

    def batch_detection_task(self):
        try:
            total = len(self.plugin_folders)
            base_output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
            os.makedirs(base_output, exist_ok=True)
            # 本次会话的临时检测目录
            self.session_temp_dir = os.path.join(base_output, "_session_temp_" + time.strftime("%Y%m%d_%H%M%S"))
            nodes_dir = os.path.join(self.session_temp_dir, "nodes_to_translate")
            os.makedirs(nodes_dir, exist_ok=True)
            
            self.log(f"开始检测 {total} 个插件...")
            
            self.detected_nodes = {}
            for i, folder in enumerate(self.plugin_folders, 1):
                name = os.path.basename(folder)
                self.log(f"[{i}/{total}] 检测插件: {name}")
                
                parser = NodeParser(folder)
                nodes = parser.parse_folder(folder)
                nodes = parser.optimize_node_info(nodes)
                
                outfile = os.path.join(nodes_dir, f'{name}_nodes.json')
                FileUtils.save_json(nodes, outfile)
                
                self.detected_nodes.update(nodes)
                self.log(f"  - 发现 {len(nodes)} 个节点")
            
            self.log(f"检测完成，共 {len(self.detected_nodes)} 个节点")
            
            if self.detected_nodes:
                self.root.after(0, lambda: [
                    self.detect_btn.config(state=tk.NORMAL),
                    self.start_btn.config(state=tk.NORMAL),
                    self.view_json_btn.config(state=tk.NORMAL)
                ])
                
        except Exception as e:
            self.log(f"检测失败: {e}")
            self.root.after(0, lambda: self.detect_btn.config(state=tk.NORMAL))

    def toggle_translation(self):
        if self.translating:
            self.stop_translation()
        else:
            self.start_translation()

    def start_translation(self):
        cfg = self.get_current_service_config()
        if not cfg: return
        if self.translating:
            return
        
        # 简单验证
        if cfg["name"] not in ["ollama", "lmstudio"] and not cfg["api_key"]:
            messagebox.showerror("错误", "请输入API Key")
            return
            
        try:
            batch_size = int(self.batch_size.get())
            if batch_size < 1: raise ValueError
        except:
            messagebox.showerror("错误", "请输入有效的并发数")
            return

        try:
            rounds = int(self.rounds.get())
            if rounds < 1 or rounds > 5: raise ValueError
        except:
            messagebox.showerror("错误", "翻译轮次需为1-5的整数")
            return

        # 验证 temperature 和 top_p
        try:
            temperature = float(cfg.get("temperature", 0.3))
            if not (0.0 <= temperature <= 2.0):
                raise ValueError
        except:
            messagebox.showerror("错误", "temperature需为0.0-2.0之间的数字")
            return
        try:
            top_p = float(cfg.get("top_p", 0.95))
            if not (0.0 <= top_p <= 1.0):
                raise ValueError
        except:
            messagebox.showerror("错误", "top_p需为0.0-1.0之间的数字")
            return
        
        self._save_config()
        
        self.translating = True
        self.start_btn.config(text="🛑 终止翻译", state=tk.NORMAL)
        self.detect_btn.config(state=tk.DISABLED)
        
        threading.Thread(
            target=self.batch_translation_task,
            args=(cfg, batch_size, rounds),
            daemon=True
        ).start()

    def batch_translation_task(self, cfg, batch_size, rounds, target_folders=None):
        try:
            # 使用已存在的 current_output_dir 或新建
            base_output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
            os.makedirs(base_output, exist_ok=True)
                
            self.log("开始批量翻译...")
            
            successful = []
            failed = []
            curr_batch_size = batch_size
            
            folders_to_process = target_folders if target_folders is not None else self.plugin_folders

            # 如果是全新的翻译任务（非重译），清空失败记录
            if target_folders is None:
                self.failed_records = []
                self.root.after(0, lambda: self.retry_btn.config(state=tk.DISABLED))

            total_folders = len(folders_to_process)
            
            for i, folder in enumerate(folders_to_process, 1):
                if not self.translating: break
                
                name = os.path.basename(folder)
                self.log(f"[{i}/{total_folders}] 正在翻译插件: {name}")
                
                try:
                    # 1. 解析
                    parser = NodeParser(folder)
                    nodes = parser.parse_folder(folder)
                    nodes = parser.optimize_node_info(nodes)
                    
                    if not nodes:
                        self.log(f"插件 {name} 无待翻译节点，跳过")
                        continue
                        
                    # 2. 翻译
                    # 根据服务类型实例化 Translator
                    if cfg["name"] == "ollama":
                        translator = OllamaTranslator(base_url=cfg["base_url"], model_id=cfg["model_id"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    elif cfg["name"] == "lmstudio":
                        translator = LMStudioTranslator(base_url=cfg["base_url"], model_id=cfg["model_id"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    elif cfg["name"] == "siliconflow":
                        translator = SiliconFlowTranslator(api_key=cfg["api_key"], model_id=cfg["model_id"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95))
                    else:
                        translator = Translator(api_key=cfg["api_key"], model_id=cfg["model_id"], base_url=cfg["base_url"], temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95), error_policy=cfg.get("error_policy"), fallback_models=cfg.get("fallback_models"), service_name=cfg["name"])
                    setattr(translator, "only_tooltips", bool(cfg.get("only_tooltips")))
                    
                    # 进度回调
                    def progress_cb(curr, total, msg=None):
                        # 兼容不同类型的回调参数
                        # 如果是 (curr, msg) 形式
                        if isinstance(curr, int) and isinstance(total, str):
                            msg = total
                            progress = curr
                        # 如果是 (curr, total, msg) 形式
                        elif isinstance(curr, int) and isinstance(total, int):
                            progress = int((curr / total) * 100)
                        else:
                            progress = 0
                            
                        if msg and ("[翻译]" in msg or "[验证]" in msg or "[完成]" in msg or "[统计]" in msg or "[限流]" in msg or "[策略]" in msg):
                            self.log(f"  > {msg}")
                        if msg and ("[限流]" in msg or "[策略]" in msg):
                            self.strategy_status.set(msg)
                            
                    translated = translator.translate_nodes(nodes, folder, batch_size=curr_batch_size, update_progress=progress_cb, temp_dir=None, rounds=rounds)
                    
                    # 3. 后处理 (移除tooltip并保存)
                    
                    plugin_output = os.path.join(base_output, name)
                    os.makedirs(plugin_output, exist_ok=True)
                    result_file = os.path.join(plugin_output, f"{name}.json")
                    FileUtils.save_json(translated, result_file)
                    
                    # 尝试保存到 ComfyUI 目录
                    try:
                        comfy_file = FileUtils.save_to_comfyui_translation(folder, translated, name)
                        self.log(f"已保存到: {comfy_file}")
                    except Exception as e:
                        self.log(f"保存到ComfyUI目录失败: {e}")
                        
                    successful.append(name)
                    
                except Exception as e:
                    err_text = str(e)
                    info = self._parse_error_info(err_text)
                    # 自动切换备用模型
                    fallback_models = cfg.get("fallback_models", [])
                    switched = False
                    for m in fallback_models:
                        try:
                            if not messagebox.askyesno("确认切换", f"检测到限制或失败，是否切换到备用模型：{m}？"):
                                continue
                            self.log(f"[策略] 切换备用模型: {m}")
                            self.strategy_status.set(f"[策略] 切换备用模型: {m}")
                            translator = Translator(api_key=cfg.get("api_key"), model_id=m, base_url=cfg.get("base_url"), temperature=cfg.get("temperature", 0.3), top_p=cfg.get("top_p", 0.95), error_policy=cfg.get("error_policy"), fallback_models=[x for x in fallback_models if x != m], service_name=cfg["name"])
                            setattr(translator, "only_tooltips", bool(cfg.get("only_tooltips")))
                            translated = translator.translate_nodes(nodes, folder, batch_size=curr_batch_size, update_progress=progress_cb, temp_dir=None, rounds=rounds)
                            plugin_output = os.path.join(base_output, name)
                            os.makedirs(plugin_output, exist_ok=True)
                            result_file = os.path.join(plugin_output, f"{name}.json")
                            FileUtils.save_json(translated, result_file)
                            try:
                                comfy_file = FileUtils.save_to_comfyui_translation(folder, translated, name)
                                self.log(f"已保存到: {comfy_file}")
                            except Exception as se:
                                self.log(f"保存到ComfyUI目录失败: {se}")
                            successful.append(name)
                            switched = True
                            break
                        except Exception as se:
                            err_text = str(se)
                            continue
                    if switched:
                        continue
                    self.log(f"插件 {name} 翻译失败: {err_text}")
                    failed.append(name)
                    localized = None
                    try:
                        from src.translation_config import TranslationConfig
                        localized = TranslationConfig.localize_error(info.get("code") or 0, info.get("provider") or "", info.get("raw") or err_text)
                        if (localized.get("code") == 429):
                            new_size = max(3, int(curr_batch_size) - 2)
                            if new_size != curr_batch_size:
                                self.log(f"  > [策略] 触发限流，自动将并发数从 {curr_batch_size} 降为 {new_size}")
                                curr_batch_size = new_size
                        if localized and localized.get("title"):
                            self.log(f"  > [错误解析] 代码 {localized.get('code')}: {localized.get('title')}（{localized.get('reason')}）")
                            sol = localized.get("solution")
                            if sol:
                                self.log(f"  > [建议] {sol}")
                            params = localized.get("params")
                            if isinstance(params, dict):
                                for k, v in params.items():
                                    self.log(f"  > [参数说明] {k}: {v}")
                            # 指导建议（并发/间隔）
                            key = cfg["name"]
                            if key == "openrouter":
                                prov = (info.get("provider") or "").lower()
                                if "google" in prov:
                                    key = "openrouter:google"
                                else:
                                    key = "openrouter:general"
                            rl = TranslationConfig.RATE_LIMIT_RULES.get(key)
                            if rl:
                                self.log(f"  > [限制建议] 推荐并发: {rl['suggested_concurrency']}，最小间隔: {rl['min_interval_sec']}秒（{rl['notes']}）")
                                self.strategy_status.set(f"并发建议: {rl['suggested_concurrency']}，间隔≥{rl['min_interval_sec']}s")
                            if (localized.get("code") == 429):
                                self.log("  > [预测] 该路由当前拥堵，通常在5-10分钟内恢复，请稍后重试或切换备用模型")
                    except Exception:
                        localized = None
                    self.failed_records.append({
                        "name": name,
                        "folder": folder,
                        "error": err_text,
                        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "localized": localized,
                        "strategy_log": getattr(translator, "strategy_log", []),
                        "policy": cfg.get("error_policy", {})
                    })
                    
            if failed:
                self.log(f"翻译任务结束。成功: {len(successful)}, 失败: {len(failed)}")
            else:
                self.log(f"翻译任务结束。成功: {len(successful)}")
            
            # 仅在存在失败时生成报告
            if failed:
                try:
                    timestamp = time.strftime('%Y%m%d_%H%M%S')
                    report_content = {
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "total": len(successful) + len(failed),
                        "success_count": len(successful),
                        "failed_count": len(failed),
                        "successful_plugins": successful,
                        "failed_plugins": failed,
                        "failed_details": self.failed_records
                    }
                    try:
                        # 汇总分析
                        error_counts = {}
                        retry_stats = {"rate_limit_retry": 0, "switch_single_user": 0, "split_batch": 0}
                        for rec in self.failed_records:
                            loc = rec.get("localized") or {}
                            code = loc.get("code")
                            if code is not None:
                                error_counts[str(code)] = error_counts.get(str(code), 0) + 1
                            for evt in rec.get("strategy_log", []):
                                t = evt.get("type")
                                if t in retry_stats:
                                    retry_stats[t] += 1
                        report_content["analysis"] = {
                            "error_counts": error_counts,
                            "strategy_stats": retry_stats
                        }
                        # 建议配置
                        from src.translation_config import TranslationConfig
                        curr_service = self.config.get("current_service", "")
                        key = curr_service
                        if key == "openrouter":
                            # 粗略判断是否为Google路由
                            prov = None
                            for rec in self.failed_records:
                                loc = rec.get("localized") or {}
                                p = (loc.get("provider") or "").lower()
                                if p:
                                    prov = p
                                    break
                            if prov and "google" in prov:
                                key = "openrouter:google"
                            else:
                                key = "openrouter:general"
                        rl = TranslationConfig.RATE_LIMIT_RULES.get(key)
                        if rl:
                            report_content["recommendations"] = {
                                "suggested_concurrency": rl["suggested_concurrency"],
                                "min_interval_sec": rl["min_interval_sec"],
                                "notes": rl["notes"]
                            }
                    except Exception:
                        pass

                    # 如果只处理了一个插件，则将报告保存在该插件的输出目录
                    if len(self.plugin_folders) == 1:
                        single_name = os.path.basename(self.plugin_folders[0])
                        plugin_output = os.path.join(base_output, single_name)
                        os.makedirs(plugin_output, exist_ok=True)
                        report_file = os.path.join(plugin_output, f"report_{timestamp}.json")
                        with open(report_file, 'w', encoding='utf-8') as f:
                            json.dump(report_content, f, indent=4, ensure_ascii=False)
                        self.log(f"翻译失败报告已生成: {report_file}")
                    else:
                        # 生成总失败报告
                        summary_file = os.path.join(base_output, f"report_{timestamp}.json")
                        with open(summary_file, 'w', encoding='utf-8') as f:
                            json.dump(report_content, f, indent=4, ensure_ascii=False)
                        self.log(f"翻译失败总报告已生成: {summary_file}")

                        # 为每个失败插件生成精简报告
                        for rec in self.failed_records:
                            name = rec.get("name")
                            folder = rec.get("folder", "")
                            plugin_output = os.path.join(base_output, os.path.basename(folder) or name)
                            os.makedirs(plugin_output, exist_ok=True)
                            plugin_report = {
                                "timestamp": report_content["timestamp"],
                                "plugin": name,
                                "status": "failed",
                                "failed_detail": rec
                            }
                            report_path = os.path.join(plugin_output, f"report_{timestamp}.json")
                            with open(report_path, 'w', encoding='utf-8') as f:
                                json.dump(plugin_report, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    self.log(f"生成失败报告失败: {e}")

            # 如果有失败记录，启用重译按钮并显示详情
            if self.failed_records:
                 self.root.after(0, lambda: self.retry_btn.config(state=tk.NORMAL))
                 self.root.after(0, self.show_failed_dialog)

            # 清理本次会话的检测临时目录
            try:
                import shutil
                if hasattr(self, 'session_temp_dir') and os.path.isdir(self.session_temp_dir):
                    shutil.rmtree(self.session_temp_dir, ignore_errors=True)
            except Exception:
                pass
            if successful:
                self.root.after(0, lambda: self.view_btn.config(state=tk.NORMAL))
                
        except Exception as e:
            self.log(f"任务出错: {e}")
        finally:
            self.translating = False
            self.root.after(0, lambda: [
                self.start_btn.config(state=tk.NORMAL, text="⏳ 开始翻译"),
                self.detect_btn.config(state=tk.NORMAL)
            ])

    def retry_failed_translation(self):
        self.show_failed_dialog()

    def show_failed_dialog(self):
        if not self.failed_records:
            messagebox.showinfo("提示", "没有失败的记录")
            return
            
        top = tk.Toplevel(self.root)
        top.title("翻译失败列表 - 选择要重译的插件")
        # 居中显示
        self.center_toplevel(top, 700, 500)
        
        # 设置主题颜色
        top.configure(bg="#8fa5b1")
        
        # 顶部说明
        ttk.Label(top, text=f"共 {len(self.failed_records)} 个插件翻译失败，请选择要重译的插件:", background="#8fa5b1").pack(padx=10, pady=5, anchor="w")
        
        # 滚动容器
        canvas = tk.Canvas(top, bg="#87baab", highlightthickness=0)
        scrollbar = ttk.Scrollbar(top, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        scrollbar.pack(side="right", fill="y", pady=5)
        
        # 变量跟踪选择
        self.retry_vars = []
        
        style = ttk.Style()
        style.configure("Retry.TCheckbutton", background="#87baab")
        
        for i, record in enumerate(self.failed_records):
            var = tk.BooleanVar(value=True) # 默认选中
            self.retry_vars.append((record, var))
            
            frame = ttk.Frame(scrollable_frame, style="TFrame")
            frame.pack(fill="x", padx=5, pady=2)
            # 手动设置Frame背景以匹配Canvas
            try: frame.configure(bootstyle="secondary") 
            except: pass
            
            chk = tk.Checkbutton(
                scrollable_frame,
                text=f"{record['name']}",
                variable=var,
                bg="#87baab",
                fg="#000000",
                activebackground="#87baab",
                selectcolor="#87baab"
            )
            chk.pack(anchor="w", padx=5)
            
            info_frame = tk.Frame(scrollable_frame, bg="#87baab")
            info_frame.pack(fill="x", padx=25)
            
            tk.Label(info_frame, text=f"路径: {record['folder']}", bg="#87baab", anchor="w").pack(fill="x")
            tk.Label(info_frame, text=f"原因: {record['error']}", fg="#8b0000", bg="#87baab", anchor="w").pack(fill="x")
            tk.Label(info_frame, text=f"时间: {record['time']}", fg="#333333", bg="#87baab", anchor="w").pack(fill="x")
            
            ttk.Separator(scrollable_frame, orient="horizontal").pack(fill="x", pady=5)

        # 按钮区域
        btn_frame = ttk.Frame(top)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        def do_retry():
            selected_records = [r for r, v in self.retry_vars if v.get()]
            if not selected_records:
                messagebox.showwarning("提示", "请至少选择一个插件")
                return
            
            # 验证配置
            cfg = self.get_current_service_config()
            if not cfg: return
            
            cfg["only_tooltips"] = self.only_tooltips.get()
            
            if cfg["name"] not in ["ollama", "lmstudio"] and not cfg["api_key"]:
                messagebox.showerror("错误", "请输入API Key")
                return

            try:
                batch_size = int(self.batch_size.get())
                if batch_size < 1: raise ValueError
            except:
                messagebox.showerror("错误", "请输入有效的并发数")
                return

            try:
                rounds = int(self.rounds.get())
                if rounds < 1 or rounds > 5: raise ValueError
            except:
                messagebox.showerror("错误", "翻译轮次需为1-5的整数")
                return
            
            folders = [r['folder'] for r in selected_records]
            folders = list(set(folders)) # 去重
            
            # 从失败记录中移除将要重译的（避免重复）
            # 或者我们在这里不移除，等重译开始时，如果重译成功则不加回失败列表
            # 但为了UI状态更新，最好是先移除，如果再次失败会由batch_translation_task添加
            
            retrying_paths = set(folders)
            self.failed_records = [r for r in self.failed_records if r['folder'] not in retrying_paths]
            
            if not self.failed_records:
                self.retry_btn.config(state=tk.DISABLED)
            
            top.destroy()
            
            # 启动重译
            self.translating = True
            self.start_btn.config(state=tk.NORMAL, text="🛑 终止翻译")
            self.detect_btn.config(state=tk.DISABLED)
            
            threading.Thread(
                target=self.batch_translation_task,
                args=(cfg, batch_size, rounds, folders),
                daemon=True
            ).start()

        ttk.Button(btn_frame, text="关闭", command=top.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="开始重译", command=do_retry).pack(side=tk.RIGHT, padx=5)
        
        def select_all(state):
            for _, var in self.retry_vars:
                var.set(state)
                
        ttk.Button(btn_frame, text="全选", command=lambda: select_all(True)).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="全不选", command=lambda: select_all(False)).pack(side=tk.LEFT, padx=5)


    def stop_translation(self):
        if not self.translating:
            return
        self.translating = False
        self.log("正在停止翻译...")
        self.start_btn.config(text="⏳ 开始翻译", state=tk.NORMAL)

    def view_json(self):
        if hasattr(self, 'session_temp_dir'):
            path = os.path.join(self.session_temp_dir, "nodes_to_translate")
            if os.path.exists(path):
                os.startfile(path)

    def view_results(self):
        try:
            if self.plugin_folders and len(self.plugin_folders) == 1:
                plugin_folder = self.plugin_folders[0]
                plugin_name = os.path.basename(plugin_folder.rstrip(os.path.sep))
                norm = os.path.normpath(plugin_folder)
                parts = norm.split(os.sep)
                if 'custom_nodes' in parts:
                    idx = parts.index('custom_nodes')
                    custom_nodes_path = os.sep.join(parts[:idx + 1])
                    target_dir = os.path.join(custom_nodes_path, 'ComfyUI-DD-Translation', 'zh-CN', 'Nodes')
                    target_file = os.path.join(target_dir, f"{plugin_name}.json")
                    if os.path.exists(target_file):
                        subprocess.Popen(['notepad.exe', target_file])
                        return
                    if os.path.exists(target_dir):
                        os.startfile(target_dir)
                        return
            if self.plugin_folders and len(self.plugin_folders) > 1:
                roots = []
                for folder in self.plugin_folders:
                    norm = os.path.normpath(folder)
                    parts = norm.split(os.sep)
                    if 'custom_nodes' in parts:
                        idx = parts.index('custom_nodes')
                        custom_nodes_path = os.sep.join(parts[:idx + 1])
                        target_dir = os.path.join(custom_nodes_path, 'ComfyUI-DD-Translation', 'zh-CN', 'Nodes')
                        roots.append(target_dir)
                if roots:
                    os.startfile(roots[0])
                    return
            base_output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
            if os.path.exists(base_output):
                os.startfile(base_output)
        except Exception as e:
            try:
                messagebox.showerror("错误", f"打开结果失败: {e}")
            except Exception:
                pass

    def unload_model(self):
        # 简化版卸载逻辑
        cfg = self.get_current_service_config()
        if not cfg or cfg["name"] not in ["ollama", "lmstudio"]: return
        
        self.log(f"正在卸载模型 {cfg['model_id']}...")
        def task():
            try:
                if cfg["name"] == "ollama":
                    OllamaTranslator(cfg["base_url"], "").unload_model(cfg["model_id"])
                else:
                    LMStudioTranslator(cfg["base_url"], "").unload_model(cfg["model_id"])
                self.log("卸载完成")
            except Exception as e:
                self.log(f"卸载失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _load_config(self) -> dict:
        try:
            if not os.path.exists('config.json'):
                return {}
            with open('config.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except:
            return {}

    def setup_console_ui(self): # 简单占位，保持结构完整
        text = scrolledtext.ScrolledText(self.console_tab, bg="#87baab", fg="#000000")
        text.pack(fill=tk.BOTH, expand=True)
        # 将日志重定向到这里
        logging.getLogger().addHandler(TextHandler(text))
        
    def setup_help_ui(self):
        text = scrolledtext.ScrolledText(self.help_tab, bg="#87baab", fg="#000000", font=("微软雅黑", 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        help_content = """
本工具在原作者B站AI-老X，班长captain更改后的版本基础上进行修改优化，支持tooltip值的翻译和生成(tooltip值就是鼠标悬停在节点选项上的说明文档)

使用说明:

1. 选择插件
   - 将ComfyUI custom_nodes目录下的插件文件夹拖入"插件选择"区域
   - 或者点击"选择文件夹"按钮进行批量选择
   - 支持同时处理多个插件

2. 配置翻译服务
   - 在"翻译服务配置"中选择服务商 (如 Doubao, DeepSeek, OpenAI 等)
   - 点击"获取API Key"链接去官网申请密钥(很多在线服务商都有很多免费模型可以调用)
   - 填入API Key和模型ID (部分服务支持自动刷新模型列表)
   - 点击"测试API"确保连接正常(模型名称会在测试成功后保存在下拉列表)

3. 执行翻译
   - 点击"执行检测"扫描插件中的节点
   - 点击"开始翻译"启动自动翻译任务
   - 翻译过程中可随时点击"终止翻译"

4. 结果处理
   - 翻译完成后，结果会自动复制一份到相对路径下的 ComfyUI\\custom_nodes\\ComfyUI-DD-Translation\\zh-CN\\Nodes 文件夹
   - 同时也会保存一份到本工具的 output 目录
   - 点击"查看结果"可打开 ComfyUI-DD-Translation\\zh-CN\\Nodes 的结果文件进行手动调整修改

注意事项:
- 请确保网络连接正常，部分服务需要科学上网
- 建议并发数设置为 5-8，过高可能导致API限流
- 翻译结果会自动应用，重启ComfyUI即可生效
- API密钥保存在本项目根目录下的 config.json 文件中，请勿分享此文件

错误策略设置说明:
- 重试策略:
  * 指数退避: 每次重试间隔翻倍 (如 2s, 4s, 8s...)，适合应对临时性网络波动。
  * 线性重试: 每次重试间隔固定 (如 2s, 2s, 2s...)，适合稳定的错误恢复。
  * 不重试: 遇到错误直接失败，不进行重试。
- 最大重试次数: 单个任务失败后尝试重新执行的最大次数 (0-20次)。
- 基础间隔: 首次重试前的等待时间 (0-60秒)。
"""
        text.insert('1.0', help_content)
        text.configure(state='disabled')

if __name__ == "__main__":
    print("Starting application...")
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    try:
        print("Initializing TkinterDnD...")
        root = TkinterDnD.Tk()
        print("Initializing ComfyUITranslator...")
        app = ComfyUITranslator(root)
        print("Entering mainloop...")
        root.mainloop()
        print("Mainloop exited.")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        try:
            messagebox.showerror("启动失败", f"程序启动失败:\n{e}")
        except Exception:
            pass
