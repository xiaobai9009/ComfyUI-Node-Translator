# ComfyUI 节点翻译工具 (ComfyUI Node Translator)

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-Compatible-green.svg)](https://github.com/comfyanonymous/ComfyUI)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

一个功能强大的 ComfyUI 节点翻译工具，旨在帮助用户将 ComfyUI 自定义节点的界面、提示信息以及 tooltip 说明翻译成中文。支持多种 LLM 服务（Ollama、LM Studio、SiliconFlow、阿里云等），提供直观的图形界面、批量处理、结果对比和失败重译功能。

本工具原作者为 B 站 **AI-老X** 与 **班长 captain**，本版本在其基础上进行了扩展和修改。
<img width="1806" height="1265" alt="e7a28c58621ce9c6" src="https://github.com/user-attachments/assets/e055feb8-7cde-4e8a-8118-b3f0aac9477e" />

---

## 📚 目录

1. [项目概述](#1-项目概述)
2. [功能模块详细说明](#2-功能模块详细说明)
3. [环境配置指南](#3-环境配置指南)
4. [部署运行说明](#4-部署运行说明)
5. [测试验证方案](#5-测试验证方案)
6. [常见问题解答](#6-常见问题解答)
7. [版本更新记录](#7-版本更新记录)

---

## 1. 项目概述

### 1.1 项目简介
**项目名称**：ComfyUI Node Translator  
**当前版本**：v1.2.0  
**功能定位**：ComfyUI 插件节点自动化翻译工具  
**适用场景**：
- ComfyUI 插件汉化开发者
- 希望使用中文界面的 ComfyUI 用户
- 需要批量处理大量插件翻译的场景

### 1.2 技术栈
- **编程语言**：Python 3.10+ (推荐 3.13)
- **GUI 框架**：Tkinter, TkinterDnD2
- **LLM 集成**：OpenAI SDK (兼容 Ollama, LM Studio, SiliconFlow, DeepSeek 等)
- **文件处理**：AST (抽象语法树解析), JSON

### 1.3 架构图

graph TD
    A[用户界面 (Tkinter)] --> B[控制层 (Main Controller)]
    
    %% 控制层关联模块
    B --> C[节点解析器 (NodeParser)]
    B --> D[翻译引擎 (Translator)]
    B --> E[文件管理器 (FileUtils)]
    
    %% 节点解析器流程
    C --> F[插件文件夹]
    F -- 读取 Python 源码 --> C
    
    %% 翻译引擎流程
    D --> G{LLM 服务接口}
    G -- 本地部署 --> H[Ollama / LM Studio]
    G -- 云端服务 --> I[SiliconFlow / Aliyun / OpenAI]
    D --> J[翻译结果 JSON]
    
    %% 文件管理器流程
    E -- 保存文件 --> K[输出目录 / ComfyUI 目录]
```

---

## 2. 功能模块详细说明

### 2.1 批量翻译模块
**用途**：核心功能，对选定的 ComfyUI 插件进行自动化翻译。

- **使用前提**：已配置好 API Key 或本地模型服务。
- **操作步骤**：
  1. 启动程序 `启动界面.bat`。
  2. 在 "翻译服务配置" 区域选择服务商（如 SiliconFlow）并填写 API Key。
  3. 将 `ComfyUI/custom_nodes` 下的插件文件夹拖入 "插件选择" 区域（支持多选）。
  4. 点击 "执行检测" 扫描节点。
  5. 点击 "开始翻译" 启动任务。
- **参数说明**：
  - `并发数`：建议 5-8，过高可能触发 API 限流。
  - `翻译轮次`：建议 1-2，用于优化翻译质量。
- **输出**：生成 `*_translation.json` 文件并自动复制到相对路径下 `ComfyUI\\custom_nodes\\ComfyUI-DD-Translation\\zh-CN\\Nodes`。
  - 同时也会保存一份到本工具的 `output` 目录
  - 点击“查看结果”可打开 `ComfyUI-DD-Translation\\zh-CN\\Nodes` 的结果文件进行手动修改

### 2.2 失败重译机制
**用途**：处理批量翻译过程中因网络或模型原因导致的失败任务。

- **触发条件**：批量翻译任务中有插件标记为 "失败"。
- **操作步骤**：
  1. 翻译任务结束后，若存在失败项，"失败重译" 按钮将激活。
  2. 点击 "失败重译"，弹出失败列表详情（包含错误原因）。
  3. 勾选需要重译的插件（支持全选/部分选择）。
  4. 可调整主界面的 API 设置或并发参数。
  5. 点击 "开始重译"。
- **典型场景**：API 余额不足充值后重试、网络波动后重试。

### 2.3 节点检测与解析
**用途**：智能识别 Python 源码中的 ComfyUI 节点定义。

- **工作原理**：使用 Python AST（抽象语法树）静态分析代码，提取 `NODE_CLASS_MAPPINGS`、`NODE_DISPLAY_NAME_MAPPINGS`、`INPUT_TYPES` 等关键信息。
- **输出**：生成中间格式的 JSON 文件，包含待翻译的 Title, Inputs, Widgets, Outputs。

### 2.4 结果对比功能
**用途**：对比新旧翻译文件或不同版本的节点定义。

- **操作步骤**：
  1. 切换到 "对比功能" 标签页。
  2. 选择 "旧版本节点文件"（JSON）。
  3. 选择 "新版本节点文件"（JSON）。
 4. 点击 "比较节点"，结果将显示新增或变更的节点信息。

### 2.5 结果处理
- 翻译完成后，结果会自动复制一份到相对路径下的 `ComfyUI\\custom_nodes\\ComfyUI-DD-Translation\\zh-CN\\Nodes` 文件夹
- 同时也会保存一份到本工具的 `output` 目录
- 点击“查看结果”可打开 `ComfyUI-DD-Translation\\zh-CN\\Nodes` 的结果文件进行手动修改

---

## 3. 环境配置指南

### 3.1 开发环境要求
- **操作系统**：Windows 10/11 (推荐), Linux/macOS (需自行处理 TkinterDnD 依赖)
- **Python**：3.10 或更高版本 (默认优先使用项目内置python环境)
- **依赖库**：见 `requirements.txt`


### 3.2 配置文件
复制 `config.template.json` 为 `config.json` 并修改：

```json
{
    "current_service": "siliconflow",
    "api_keys": {
        "siliconflow": "sk-xxxxxxxx",
        "aliyun": "sk-xxxxxxxx"
    },
    "api_configs": {
        "ollama": {
            "base_url": "http://localhost:11434"
        }
    }
}
```

---

## 4. 部署运行说明

### 4.1 本地启动
**使用批处理 (Windows)**
直接双击 `启动界面.bat`。

**或使用 Python 命令**
```bash
# 激活虚拟环境后
python main.py
```

### 4.2 生产环境部署
本工具为桌面端 GUI 应用，通常以源码形式分发或打包为 EXE。
若需打包为 EXE (使用 PyInstaller):
```bash
pyinstaller --noconsole --add-data "src;src" --add-data "tkdnd2_files;tkinterdnd2" main.py
```
*(注：需自行处理 tkinterdnd2 的路径依赖)*

### 4.3 监控与日志
- **界面日志**：主界面下方实时滚动显示关键日志。
- **控制台日志**：切换到 "控制台" 标签页查看详细 debug 信息。
- **文件日志**：翻译失败时会记录详细错误到 `output/report_*.json`。

---

## 5. 测试验证方案

### 5.1 功能验证流程
1. **解析验证**：
   - 找一个包含复杂节点的插件。
   - 运行检测，检查生成的 `nodes.json` 是否包含所有 `INPUT_TYPES` 和 `RETURN_TYPES`。
2. **翻译验证**：
   - 使用 Ollama (低成本) 跑通一次小批量翻译。
   - 检查生成的 JSON 文件格式是否符合 ComfyUI 语言包标准。
3. **UI 验证**：
   - 测试 API Key 的显示/隐藏切换。
   - 测试失败重译流程：人为断网导致失败，恢复网络后点击重译。

---

## 6. 常见问题解答 (FAQ)

### Q1: 程序启动报错 `TclError` 或 `DLL load failed`
**原因**：Tkinter 或 TkinterDnD 环境路径问题。
**解决**：确保使用 `启动界面.bat` 启动，脚本内包含了环境变量修复逻辑。

### Q2: 翻译进度卡住不动
**原因**：并发数过高导致 API 阻塞或报错。
**解决**：
1. 点击 "终止翻译"。
2. 将并发数调低至 3-5。
3. 点击 "失败重译" 继续处理剩余项。

### Q3: 无法拖拽文件夹
**原因**：Windows 权限隔离或库未正确加载。
**解决**：不要以管理员身份运行 IDE 或 CMD，普通用户权限即可。确保 `tkinterdnd2` 已正确安装。

### Q4: 错误代码对照
- `401 Unauthorized`: API Key 错误或过期。
- `429 Too Many Requests`: 并发过高，请降低并发数。
- `ConnectionError`: 本地 Ollama 未启动或网络不通。

---

## 7. 版本更新记录

### v1.2.0 (2025-12-09)
- **✨ 新增**：
  - 失败重译机制：支持记录失败任务并提供重试界面。
  - 翻译报告生成：任务结束后生成包含成功/失败统计的 JSON 报告。
  - API Key 隐私保护：支持点击眼睛图标切换密钥的明文/密文显示。
- **🐛 修复**：
  - 修复了批量翻译时部分 UI 状态更新滞后的问题。
- **⚡ 优化**：
  - 优化了节点解析器的 AST 匹配逻辑，支持更多种类的节点定义写法。

### v1.1.0
- **✨ 新增**：
  - 支持 SiliconFlow 云端 API。
  - 添加 "对比功能" 标签页。
- **⚡ 优化**：
  - 界面主题美化 (暗色模式)。

### v1.0.0
- 初始版本发布，支持 Ollama 和 LM Studio 本地翻译。

---
*文档生成日期：2025-12-09*
