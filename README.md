# ComfyUI 节点翻译工具 (ComfyUI Node Translator)

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-Compatible-green.svg)](https://github.com/comfyanonymous/ComfyUI)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

一个功能强大的 ComfyUI 节点翻译工具，旨在帮助用户将 ComfyUI 自定义节点的界面、提示信息以及 tooltip 说明翻译成中文。支持多种 LLM 服务（Ollama、LM Studio、SiliconFlow、阿里云等），提供直观的图形界面、批量处理、结果对比和失败重译功能。

本工具原作者为 B 站 **AI-老X** 与 **班长 captain**，本版本在其基础上进行了扩展和修改。

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
**当前版本**：v1.4.0  
**功能定位**：ComfyUI 插件节点自动化翻译工具  
**适用场景**：
- ComfyUI 插件汉化开发者
- 希望使用中文界面的 ComfyUI 用户
- 需要批量处理大量插件翻译的场景
**推荐模型**: 推荐使用qwen2.5-14b-instruct类的模型,尽量不要使用带乱七八糟后缀或破限的模型

### 1.2 技术栈
- **编程语言**：Python 3.10+ (推荐 3.13)
- **GUI 框架**：Tkinter, TkinterDnD2
- **LLM 集成**：OpenAI SDK (兼容 Ollama, LM Studio, SiliconFlow, DeepSeek 等)
- **文件处理**：AST (抽象语法树解析), JSON

### 1.3 架构图
```mermaid
graph TD
    A[用户界面 (Tkinter)] --> B[控制层 (Main Controller)]
    B --> C[节点解析器 (NodeParser)]
    B --> D[翻译引擎 (Translator)]
    B --> E[文件管理器 (FileUtils)]
    
    C --> F[插件文件夹]
    F --> |读取 Python 源码| C
    
    D --> G{LLM 服务接口}
    G --> |本地| H[Ollama / LM Studio]
    G --> |云端| I[SiliconFlow / Aliyun / OpenAI]
    
    D --> J[翻译结果 JSON]
    E --> |保存| K[输出目录 / ComfyUI 目录]
```

---

## 2. 功能模块详细说明

### 2.1 批量翻译模块
**用途**：核心功能，对选定的 ComfyUI 插件进行自动化翻译。

- **使用前提**：已配置好 API Key 或本地模型服务。
- **操作步骤**：
  1. 启动程序 `启动应用.vbs`。
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

### v1.4.0 (2026-7-19)
- **✨ 新增**：
  - **Custom (自定义 OpenAI 兼容) 服务**：新增 `Custom` 服务类型,允许用户接入任何兼容 OpenAI Chat Completions 协议的端点(如本地 llama.cpp / vLLM / Ollama OpenAI 模式 / 各类代理)。服务行内提供 `服务器`、`API 密钥`、`模型` 三个字段,以及 `🔄 刷新模型` 按钮自动从 `/v1/models` 拉取可用模型列表。
  - **批次间冷却与智能限流退避**：翻译参数弹窗新增 `冷却间隔` 与 `每 N 批后冷却`,允许在每完成 N 批后暂停指定秒数,避免触发服务商限流。命中 `429` 时自动减小批次大小(最小 2)、指数退避冷却时间(2s→4s→8s→…→300s 上限),并将超额节点加入 `deferred_translation_queue` 在主循环结束后补做,避免丢批。
  - **断点续传**:`translate_nodes` 每批成功后立即将进度写入 `output/<plugin>/_temp/_checkpoint.json`;中途失败或被终止时,下次 `继续翻译` 自动从断点恢复,已翻译节点不会丢失。任务成功完成才清除 checkpoint。
  - **多轮补漏机制**:`_collect_missing` 会找出所有"未翻译"和"被占位/低质量翻译"的字段(通过新增的 `_is_valid_chinese_translation` 检测 `该参数用于设置`、`用于设置` 等填充式回答),后续轮次重新发给模型翻译,直至连续 2 轮无改进。
  - **占位翻译检测**:`_PLACEHOLDER_CN_PATTERNS` 拒绝模型返回的 `该参数用于设置 "X"`、`用于配置`、`用于控制` 等偷懒式输出,这些节点会在补漏中重新翻译。
  - **冷却倒计时 UI**:信息窗口新增深湖绿(`#144c42`)独立行,仅在触达冷却阈值时显示 `累计N批,冷却翻译M秒 (剩余X秒)`,倒计时逐秒刷新;非冷却期间清空,避免信息干扰。
  - **翻译参数集中弹窗**:将 `temperature`、`top_p`、`并发数`、`翻译轮次`、`冷却间隔`、`每批冷却`、`仅译tooltip` 全部集中到 `⚙️ 翻译参数设置` 弹窗,持久化到 `config.json.translation_params`,服务行不再横向铺开参数,默认窗口下不再显示不全。
  - **已翻译插件绿色高亮**:在 `📂 打开插件目录` 对话框中,自动扫描 `<custom_nodes>/ComfyUI-DD-Translation/zh-CN/Nodes/*.json`,匹配到的文件夹名以深绿(`#1B7A3A`)显示,一眼区分未翻译与已翻译。
  - **拖放与列表合并**:`插件选择` 区域的拖放说明与已选插件列表合并为同一个 `ScrolledText`,`📂 打开插件目录` 与 `🗑️ 清空列表` 按钮横向排列到顶部,无插件时显示使用说明,有插件时自动切换为带序号的列表。
  - **统一按钮三态**:翻译按钮统一为 `⏳ 开始翻译` / `⏵️ 继续翻译` / `🛑 终止翻译` 三态;有未完成 checkpoint 时显示 `继续翻译`,提示用户可恢复;点 `开始翻译` 则清空所有 checkpoint 从头翻译;点击运行中的按钮变 `终止翻译` 可中断任务。
  - **失败提示内联**:翻译失败后,失败列表内联到 `💡 继续翻译` 按钮旁的提示行,不再弹模态对话框打断操作。
- **🐛 修复**：
  - **未翻译内容残留**:在 ComfyUI-WanAnimatePlus 等大型插件上,部分 `inputs` / `widgets` / `tooltips` 节点未翻译,根因是模型返回 `该参数用于设置 "X"` 等占位式中文被 `_has_chinese` 误判为"已翻译"。新逻辑用 `_is_valid_chinese_translation` 严格校验,占位文本被识别为缺失并在补漏中重新翻译。
  - **429 限流拆分丢失节点**:旧版在 429 时修改 `node_items` 列表造成 `start_idx` 错位,部分节点永远不被取到。改为把超额节点加入 `deferred_translation_queue`,主循环跑完后用更小批次单独处理并落盘 checkpoint,确保不丢节点。
  - **过早退出补漏**:多轮补漏的退出条件从 `consecutive_no_improve >= 1` 放宽为 `>= 2`,给模型留出重新思考的机会,避免在模型偶发空泛回答时错失修复。
  - **错误重试策略残留日志**:彻底移除 `error_policy` 参数及 `[策略] 重试策略: exponential, 最大重试: 5` 等日志输出,重试策略已统一为批次级 + 429 自动退避。
  - **`tk.Listbox` 没有 `tag_configure`**:之前用 `tag_configure` 给已翻译插件设色会抛 `AttributeError`,改为通过 `itemconfig(idx, {"fg": "#1B7A3A"})` 直接给单行设置前景色。
  - **插件列表倒序显示**:`_render_drop_area` 之前用 `insert('1.0', ...)` 反复插入到开头,导致编号倒序;改为 `insert(tk.END, ...)` 追加到末尾,保持自然顺序。
  - **温度与 top_p 在多服务下的 UI 重复**:`temperature` / `top_p` 已统一到翻译参数弹窗,服务行不再保留对应输入框,避免配置不一致。
  - **服务行内 `error_policy` 调用残留**:`Translator` 构造与 `_translate_batch` 中所有 `self.error_policy.get(...)` 调用点已清理。
- **⚡ 优化**：
  - **多轮补漏并发策略**:补漏阶段也复用相同的 `dynamic_cooldown` 与 429 退避逻辑,补漏期间同样避免限流。
  - **checkpoint 持久化粒度**:每批成功即落盘,即使程序崩溃也只丢失当前批次。
  - **UI 自适应**:主窗口默认尺寸下不再因翻译参数横向铺开而显示不全,关键按钮(开始/继续/终止)始终可见。
  - **占位模式与说明**:新增的 `_PLACEHOLDER_CN_PATTERNS` 与 `_is_valid_chinese_translation` 集中维护,未来新增需要拦截的占位句式只需追加列表。
  - **帮助文档同步**:`使用说明` 中 `选择文件夹` 同步更新为 `打开插件目录`,与 UI 一致。

### v1.3.0 (2025-12-24)
- **✨ 新增**：
  - **静默启动器**：引入 `启动应用.vbs`，通过 VBScript 彻底解决 Windows 环境下启动时的黑色命令行窗口闪烁问题，提升用户交互体验。
- **🐛 修复**：
  - **复选框样式修正**：将“仅译tooltip”复选框更换为原生 `tk.Checkbutton`，修复了选中时显示为“X”而非标准对勾的视觉问题。
  - **翻译过滤逻辑**：严格落实“仅译tooltip”功能，确保开启该选项时，系统仅处理以 `tooltip` 结尾的字段，避免误伤其他非 tooltip 文本。
- **⚡ 优化**：
  - **代码瘦身**：清理了翻译引擎核心模块中 100 余行不可达（Dead Code）代码，提升了项目的代码质量与可维护性。
  - **文档同步**：同步更新 README 使用指南，推荐使用新的静默启动方式。

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
*文档生成日期：2025-12-24*
