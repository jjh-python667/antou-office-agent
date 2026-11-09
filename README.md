# ANTOU® 案头 / Make work flow.

[![Tests](https://github.com/jjh-python667/antou-office-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/jjh-python667/antou-office-agent/actions/workflows/tests.yml)

**一个能讨论思路，也能连续调用工具交付 Excel / Word 的本地办公助手。**

[项目介绍](docs/PROJECT.md) · [v3.2 改动](CHANGES-v3.2.md) · [作者作品集](https://jjh-python667.github.io/)

![案头首页](docs/screenshots/home.png)

## 快速开始

安装 Python 3.9+，下载或克隆项目，Windows 双击 `start.cmd`。先点“无需 Key 的演示”，确认本地文件处理可用；需要模型能力时，在页面填写自己的 API Key。

```sh
git clone https://github.com/jjh-python667/antou-office-agent.git
cd antou-office-agent
python -m pip install -r requirements.txt
python app.py
```

![真实本地费用汇总演示](docs/screenshots/workbench.png)

截图是本机界面与固定演示流程，不代表真实云端模型联调通过。当前提供本地运行源码，没有公网 Agent 后端。


当前版本 **v3.2**，开发基线为 `office-agent-v3.1-source.zip`。原包 SHA256：`29ea6654d8566fde779477f96ff460399bbdfe7f1a1f6c15430bf0f55883fa8f`。v3.1 的全部修复保留；没有基于旧 v3 回退修改。公开仓库只包含源码、文档与演示截图，不包含工作资料、数据库、日志或密钥。

## v3.2 的 P1 更新

1. **正文流式输出**：角色对话和 Agent 的最终正文可逐步显示，工具调用参数在完整拼接后才执行。生成结束后统一排版；停止或异常时把已显示内容标为未完成。设置中可关闭流式，兼容只返回 JSON 的网关也会回退显示完整回复。
2. **服务商参数适配**：DeepSeek 使用 `thinking.type`，通义千问使用顶层 `enable_thinking`；OpenAI 使用 `max_completion_tokens`，其余兼容接口使用 `max_tokens`。只对支持的两个预设显示思考开关，不向其他服务商注入这些专有字段。默认关闭思考；不显示 reasoning_content 为正文，工具历史中按协议保留。某些仅思考或特殊模型仍需按真实服务商要求设置并验证。
3. **上下文预算**：可设置最大输出与上下文预算；默认分别为 6000 / 32000。按 UTF-8 字节做保守 token 上界估算，包含工具 schema 和输出预留，不是服务商精确计数。超预算时只移除最早的完整用户轮次，不拆开 assistant/tool 消息。会显示省略提示；当前任务或工具链本身过大时，在调用模型前报错，要求减少资料或提高到模型实际支持的预算。
4. **本机会话保存**：成功轮次的上下文、正文和必要连接参数原子保存到 `workspace/.antou/state.sqlite3`。刷新或重启后可在历史中手动恢复；未知或不可恢复的会话继续沿用 v3.1 的失效提示，不自动调用模型。取消、失败和不完整流不会提交为成功会话。API Key、请求鉴权头不写入状态库。
5. **任务历史**：工作台“历史”可查看成功、停止、报错、中断和失效任务，下载成品、恢复成功会话，或把原任务放回输入框由用户确认后发送。停止任务的部分正文单独标识；服务重启时，上次未结束的任务标为中断。

恢复会话使用原服务商、地址和模型配置；Key 需要在页面重新填写或符合 v3.1 的官方地址环境变量规则。思考内容不展示，但模型协议上下文可能包含它并保存在本机。对话、角色要求、读取的资料片段和任务正文会存入本机状态库，因此备份与分享源码时必须排除整个 workspace。状态库当前不加密、不自动删除记录；“新建会话”只切换当前会话，不删除磁盘历史。未发送草稿仍只保留在当前页面，刷新后不恢复。

可自行修改的本地办公助手：角色对话 + 连续工具调用 Agent。当前版本在 7 种模型 API 与 GSAP 创意机构风格前端上，进一步优化了日常办公交互。不依赖 Cherry Studio，不需要前端构建步骤。

## 本次体验优化

- **专注模式**：工作台右上角进入，快捷键 Ctrl/Cmd + K；Esc 退出，手机上一屏内完成主要操作。浏览首页时提供回到工作台的快捷入口。
- **开场不挡路**：保留完整 opening，可点击跳过或按 Esc；同一标签页会话内不反复播放，右上角可手动重播。
- **保留上下文**：角色助手与执行 Agent 分别保留当前页面内的对话、草稿和执行记录；切换不会清空。新建会话后可通过提示条撤销，开始编辑或新任务后撤销失效。
- **设置可放弃**：只有点击“应用设置”才生效；关闭设置会放弃本次修改。缺少模型配置时先引导设置，任务草稿保留，不会自动付费重发。
- **记住非敏感偏好**：服务商、Base URL 与模型名保存在浏览器，可在设置中清除。API Key、角色要求、任务和聊天内容不写入浏览器持久存储；密钥刷新后需重新填写。Ctrl/Cmd + 逗号打开模型设置。
- **明确选资料**：上传后自动选入本次任务，也可在文件列表勾选或在输入框上方取消选择；每次最多 10 份。资料路径随任务发送给 Agent，请求它优先处理。该选择是任务上下文，不是工具权限隔离。
- **文件更好找**：按最近修改排序、显示数量和时间、支持名称搜索；批量上传时无效文件不会阻止其他文件上传。
- **执行有反馈**：显示任务阶段、等待耗时、可理解的工具名称和完成状态。失败后提供手动重试和模型设置入口；不会自动重试付费请求。
- **结果更易用**：基础 Markdown 安全排版、正文复制、成品下载链接和结果定位。模型返回的 HTML 按文本呈现，不执行。
- **工作台里也能试用**：欢迎区可直接运行无需 Key 的本地演示，不必回到上方展示页。

## v3.1 修复

- **可以停止任务**：任务运行时输入框旁出现“停止任务 ■”。停止、刷新或关闭页面后，模型等待可快速放弃并释放执行锁；正在执行的单个工具需等它结束，再停止后续步骤。已生成文件保留，被停止的整轮不提交为成功会话。已经发出的那次模型请求仍可能计费。
- **会话失效会明确提示**：无法从内存或本机状态库恢复时，旧会话不会被悄悄替换；页面提示“上下文已失效”，把任务放回输入框，由你确认后在新会话中发送。v3.2 中成功会话可以从磁盘恢复，内存淘汰不再等于永久失效。
- **环境变量 Key 只发往官方地址**：修改了 Base URL（含自定义接口）时，必须在设置中填写 Key，不会回退使用环境变量。
- **Excel 更可用**：明细页金额写为数值，金额列显示两位小数；超过 Excel 15 位有效数字的金额按文本保存精确值并注明；未计算的公式标记为“公式未计算”。
- **报错更清楚**：显示服务商返回的错误原文（去除密钥、截断到 300 字）；表格读取按字符上限分页。

成功会话可从本机任务历史恢复；未发送草稿只保留在当前页面内。任务开始前选定资料，执行中保留当前任务配置。重试前请检查已生成文件，避免重复生成不必要的结果。

## 启动

Windows 安装 Python 3.9 或更新版本，将整个项目解压到可写目录，双击 `start.cmd`。首次启动会创建 `.venv` 并安装两个 Python 依赖，需要联网；浏览器自动打开本地页面，关闭终端停止服务。

默认端口 `8765` 不可用时会自动选择空闲端口，以实际打开的地址为准。也可用 `OFFICE_PORT` 环境变量指定端口。数据默认保存在 `workspace/inputs` 和 `workspace/outputs`，可用 `OFFICE_WORKSPACE` 指定工作目录。

手动启动：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## 新前端与动效

- 首屏：字标分字遮罩进场、黑色双幕揭开、标题压缩和位移后归位，约 4.3 秒完成；首次访问完整播放，右上角可重播，跳过按钮或 Escape 可立即结束。
- 滚动：模块英文大标题先大幅移入，卡片随后错峰展开；插画遮罩揭开，图片轻微视差；无弹跳缓动。
- 动画以 transform、clip-path 为主，滚动监听统一使用 ScrollTrigger；不使用滚动劫持、持续粒子或视频背景。SVG 插画为本项目原创。
- GSAP 与 ScrollTrigger 3.15.1 随源码本地打包，无外部 CDN 依赖，见 `assets/THIRD-PARTY.txt`。
- 适配 `prefers-reduced-motion`，关闭开场和滚动位移动效。动画库失效时显示完整页面，办公功能独立运行。
- 下方工作台保留上传、对话、工具记录和文件下载；支持手机屏幕与拖入文件。

## 7 种模型接口

在页面“连接模型”模块或工作台顶部点击模型按钮，打开设置。每家服务商有独立的密钥、模型与地址配置。已应用的地址与模型名可以记住，密钥仅在页面内存保存，不写入 localStorage、sessionStorage 或日志。sessionStorage 仅记录开场动画是否已播放。

1. **DeepSeek**：默认 `https://api.deepseek.com`，保留默认模型 `deepseek-flash`；环境变量 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`。
2. **OpenAI**：默认 `https://api.openai.com/v1`；环境变量 `OPENAI_API_KEY` / `OPENAI_MODEL`。
3. **通义千问 / 百炼**：默认北京地域共享地址 `https://dashscope.aliyuncs.com/compatible-mode/v1`；支持修改为对应地域或工作空间地址。Key 与地域需匹配；环境变量 `DASHSCOPE_API_KEY` / `QWEN_MODEL`。
4. **Kimi**：默认 `https://api.moonshot.cn/v1`；环境变量 `MOONSHOT_API_KEY` / `KIMI_MODEL`。
5. **硅基流动**：默认 `https://api.siliconflow.cn/v1`；环境变量 `SILICONFLOW_API_KEY` / `SILICONFLOW_MODEL`。
6. **Ollama 本地**：默认 `http://127.0.0.1:11434/v1`，Key 可留空。需先自行安装并启动 Ollama、下载模型；环境变量 `OLLAMA_MODEL`。
7. **自定义兼容接口**：填写 Chat Completions 兼容的 Base URL、模型和可选 Key；Key 需在页面填写（不读取环境变量），可用 `CUSTOM_MODEL` 预设模型名。

环境变量中的 Key 只发送到该服务商预设的官方主机（协议、主机、端口一致）；修改接口地址后需在页面填写对应 Key。

除 DeepSeek 保留现有默认值外，其他服务商模型名由“读取列表”或手动填写确定，不把静态模型推荐当作当前可用列表。列表接口可能包含非对话模型，需选择支持对话的模型；执行 Agent 还需要模型支持 `tools` 函数调用。

“读取列表”验证模型列表接口；“测试对话连接”会真实调用所选模型，可能消耗少量额度。模型列表成功不代表全部模型支持 Agent。应用设置后才切换当前服务商；更换服务商、地址或模型会开始独立会话，避免混用不兼容历史。

本项目调用 `/chat/completions`，不是 Responses、Anthropic 原生或 Gemini 原生协议客户端。需要这些服务时，应接入确实提供兼容协议的服务地址。远程接口必须用 HTTPS；HTTP 仅允许本机地址。密钥不跟随 HTTP 重定向转发。

## 两种模式与办公工具

**角色助手**：可自定义角色要求，用于写作、问答、表格设计。保留当前会话上下文，不启用文件工具。上传后需切换执行 Agent 才能读取资料。

**执行 Agent**：模型返回工具调用 → 程序校验参数并执行 → 将真实结果交回模型 → 继续选择工具或交付。每次任务最多 10 轮，每轮最多 8 次工具调用。工具错误会反馈给模型；不会将失败结果保存为已完成会话。

- `list_files`：列出输入文件和生成结果。
- `read_file`：读取 TXT、MD、CSV、XLSX、DOCX，支持分页。
- `summarize_table`：完整读取表格，用 Decimal 分组计算金额，检查异常并生成 Excel。
- `create_spreadsheet`：生成一个或多个工作表，保存后重新读取校验。
- `write_document`：生成 Word 报告或纪要，保存后重读检查结构。

表格首行需为不重复、非空的字段名。金额需为普通数字，不自动猜测逗号和货币符号的含义。缺失或非数字金额不计入，重复行保留并计入，缺少分组字段的有效金额归入空分组，异常在原始数据页标记。空行保留，以保持真实源行号。不同币种需预先分开。

XLSX 公式读取已有缓存值；本项目不提供公式计算引擎。生成表格中的文本按文本保存，不执行输入中包含的公式。最多 50000 行、200 列，单个上传文件 20MB。Word 使用 A4 与中文字体，校验包括结构重读，未实现页面渲染校验。

## 先试运行

点击“运行费用汇总演示”。这是明确标记的固定本地流程，不调用外部模型，不消耗 API 额度。会读取演示数据、按部门和月份汇总、生成 Excel 与 Word，合计金额为 780，保留并标记重复与缺失记录。

之后配置自己的接口，上传脱敏资料，向执行 Agent 发送：

> 请检查我上传的费用表字段，按部门、月份汇总金额，生成 Excel 和 Word 说明，列出异常、处理口径，并核对总额。

在工作台右侧核对真实执行记录、下载文件。原始文件会保留，同名输出会自动生成新文件名。

## 源码与 HTTP API

- `app.py`：本地 HTTP 服务、会话和 Agent 循环。
- `providers.py`：7 种服务商配置、模型发现、连接测试、对话适配。
- `office_tools.py`：文件范围限制、统计和 Excel / Word 生成。
- `context_budget.py`：保守上下文估算、按完整用户轮次裁剪。
- `local_state.py`：本机 SQLite 会话与任务历史，成功轮次原子提交。
- `index.html`：页面结构。
- `assets/styles.css` / `assets/ux.css`：响应式视觉设计与专注模式、状态、资料选择等交互样式。
- `assets/ui.js`：模型设置、上传、对话、文件和工具记录。
- `assets/motion.js`：开场时间线、ScrollTrigger、减少动态效果和失效回退。
- `test_app.py` / `test_providers.py` / `test_ux.py`：本地工具、模型协议及资料选择、文件元数据测试。
- `test_v31.py`：任务取消与断线释放锁、会话失效、Key 作用域、Excel 数值与精度、公式未计算、上游错误原文、读取字符上限。
- `test_v32.py`：流式输出与工具参数拼接、上下文预算、会话持久化、任务历史、流式取消、真正的应用进程重启与密钥脱敏。
- `assets/p1.css`：高级设置与任务历史界面；原有主视觉样式、动效脚本和插画未改。

只监听本机 `127.0.0.1`。写接口要求页面令牌 `X-Office-Token` 和合法来源；不是可直接公开部署的多用户服务。

- `GET /api/health`：服务状态。
- `GET /api/providers`：服务商公开配置，只有密钥是否存在的布尔值。
- `GET /api/config`：基础配置，兼容第一版。
- `GET /api/files`：工作文件列表。
- `GET /api/history?limit=50&offset=0`：本机任务列表，支持分页。
- `GET /api/history/{task_id}`：任务详情、结果和部分正文。
- `GET /api/sessions/{session_id}`：成功会话正文与不含密钥的连接设置，供恢复使用。
- `POST /api/models`：读取所选服务商模型。
- `POST /api/test`：测试所选模型对话。
- `POST /api/chat`：角色对话或 Agent 执行，NDJSON 事件流。首个事件为 `task`（含 `task_id`）；旧会话不存在时返回 `session_expired` 且不调用模型；停止后返回 `cancelled`。
- `POST /api/cancel`：参数 `task_id`，停止正在运行的任务。
- `POST /api/upload`：上传文件。
- `POST /api/demo`：本地演示，NDJSON 事件流。
- `GET /download?path=outputs/...`：下载工作文件。

模型接口参数为 `provider`、`base_url`、`api_key`、`model`，可选 `thinking`（布尔）、`max_output_tokens`（256–16000）与 `context_window`（4096–1000000，且需大于输出预留）。对话另含 `text`、`mode`、`session_id`、`stream`（布尔，UI 默认 true）、可选 `role_prompt` 与 `attachments` 文件路径数组（最多 10 项，仅 Agent 模式）。文件路径会先做范围与存在性校验，再交给模型。不要将 Key 放在 URL 中。

新增事件 `answer_delta`（正文增量，含 reply_id）、`reply_end`（工具执行前的步骤说明结束）与 `context_budget`（估算和省略轮数）。`answer` 为完整正文，`done` 才表示整轮成功。客户端仍只在 done 后采用新 session_id。思考片段不通过 answer_delta 发送。

## 验证与边界

安装依赖后运行 `python -m unittest -v`。47 项测试（v3.1 原有 30 项保持原样 + v3.2 新增 17 项）覆盖文件工具、真实本地 HTTP 上游协议、跨模型会话隔离、流式与非流式工具调用、上下文预算、任务历史、密钥隔离、重定向处理、Excel 精度及本机状态恢复，不调用收费模型。已在 Windows / Python 3.9 上运行，包括真正终止并重启应用进程的续接测试。原有断线测试偶尔出现已关闭 socket 的 ResourceWarning，不影响断言。

本次还用 Edge / Playwright 检查了开场跳过与重播、设置放弃与应用、配置前引导、两种模式的历史与草稿保留、安全文本排版、复制、耗时反馈、失败重试、真实本地演示、混合格式上传、任务资料选择、文件搜索、新会话撤销、桌面与手机专注布局，以及记住配置时不保存密钥。云端服务商未使用真实账户 Key 联调，兼容程度与费用以实际模型和服务商为准。

分析资料时，任务与读取的文件内容可能发送到所选服务商。成功会话、任务历史、上传和输出文件都保存在本机磁盘；API Key 不保存。尚无 PDF/OCR、邮件发送、定时任务、任意脚本执行、多用户登录或公网部署能力。单个工具执行过程中仍不能强制打断；取消前已发出的模型请求仍可能计费。没有进行真实云端 Key 联调，也没有用 Microsoft Excel / Word 应用做版式实测。

接口依据：

- DeepSeek：https://api-docs.deepseek.com/guides/tool_calls/
- OpenAI：https://developers.openai.com/api/reference/chat-completions/overview
- 百炼：https://help.aliyun.com/en/model-studio/base-url
- Kimi：https://platform.kimi.com/docs/api/chat
- 硅基流动：https://api-docs.siliconflow.cn/docs/userguide/quickstart
- Ollama：https://docs.ollama.com/api/openai-compatibility
