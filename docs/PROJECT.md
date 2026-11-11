# 案头 ANTOU

案头是一个本地办公助手：浏览器工作台连到本机 Python 服务，服务再按页面上的配置调用 Chat Completions。角色模式讨论和写作；执行模式把模型的工具调用交给 `office_tools`，用真实文件结果继续，直到写出 Excel 或 Word，或要求补充材料。

ANTOU is a local office assistant. The browser talks to a Python server on the same machine, and that server calls the Chat Completions endpoint configured in the page. Role mode discusses and drafts. Agent mode gives tool calls to `office_tools` and continues from the real file results until it writes Excel or Word, or asks for something it does not have.

完整的安装、运行、测试、接口和边界见 [README](../README.md)。v3.1 与 v3.2 当时的修改记录在 [CHANGES-v3.1.md](../CHANGES-v3.1.md) 和 [CHANGES-v3.2.md](../CHANGES-v3.2.md)。此后的仓库变更在 [CHANGELOG.md](../CHANGELOG.md)。

Install, run, test, HTTP, and limits are in the [README](../README.md). The notes written with v3.1 and v3.2 are [CHANGES-v3.1.md](../CHANGES-v3.1.md) and [CHANGES-v3.2.md](../CHANGES-v3.2.md). Later repository changes are in [CHANGELOG.md](../CHANGELOG.md).

## 演示 / Demo

页面上的「运行费用汇总演示」走 `app.py` 的 `demo()`：写入一份固定 CSV，读取、按部门和月份汇总、生成 Excel 和 Word。这条路径不调用外部模型。完成文案中的合计是 780。接入模型之后，步骤由模型的工具调用决定，演示数字不能当成你的文件的结果。

"运行费用汇总演示" calls `demo()` in `app.py`: it writes a fixed CSV, reads it, groups by department and month, and writes Excel and Word. That path does not call an external model. The completion text states a total of 780. After a model is connected, steps follow that model's tool calls. The demo total is not a result for your own files.

## 实现 / How it is put together

`app.py` 提供只绑定回环地址的 HTTP 服务和 Agent 循环。`providers.py` 负责七个预设和流式拼接。`context_budget.py` 做保守的上下文估算。`local_state.py` 把成功会话和任务历史放进工作目录里的 SQLite。页面在 `index.html` 和 `assets/`。

`app.py` is the loopback HTTP server and the agent loop. `providers.py` holds the seven presets and the stream parser. `context_budget.py` estimates context. `local_state.py` stores successful sessions and task history in SQLite under the workspace. The page is `index.html` and `assets/`.

自动化测试是 `python -m unittest`。GitHub Actions 在 Python 3.11 上为 Ubuntu 和 Windows 运行这条命令。`CHANGES-v3.2.md` 记录了作者在 Windows / Python 3.9 上的一次本地运行，以及用浏览器检查页面的过程。

Automated tests are `python -m unittest`. GitHub Actions runs that command on Python 3.11 for Ubuntu and Windows. `CHANGES-v3.2.md` records the author's earlier local run on Windows / Python 3.9 and a browser pass.
