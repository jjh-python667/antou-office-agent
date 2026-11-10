"""Small, explicit adapters for Chat Completions compatible providers."""
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

PROVIDERS = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "env": "DEEPSEEK_API_KEY", "model_env": "DEEPSEEK_MODEL", "default_model": "deepseek-flash", "requires_key": True},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY", "model_env": "OPENAI_MODEL", "default_model": "", "requires_key": True},
    {"id": "qwen", "name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "env": "DASHSCOPE_API_KEY", "model_env": "QWEN_MODEL", "default_model": "", "requires_key": True},
    {"id": "kimi", "name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "env": "MOONSHOT_API_KEY", "model_env": "KIMI_MODEL", "default_model": "", "requires_key": True},
    {"id": "siliconflow", "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1", "env": "SILICONFLOW_API_KEY", "model_env": "SILICONFLOW_MODEL", "default_model": "", "requires_key": True},
    {"id": "ollama", "name": "Ollama · 本地", "base_url": "http://127.0.0.1:11434/v1", "env": "OLLAMA_API_KEY", "model_env": "OLLAMA_MODEL", "default_model": "", "requires_key": False},
    {"id": "custom", "name": "自定义兼容接口", "base_url": "", "env": "CUSTOM_API_KEY", "model_env": "CUSTOM_MODEL", "default_model": "", "requires_key": False},
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def origin(url):
    """Scheme, host and port: the unit an environment key is bound to."""
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return (parsed.scheme.lower(), parsed.hostname.lower(), port or {"https": 443, "http": 80}.get(parsed.scheme.lower()))


def official_endpoint(preset, base):
    """Environment keys are only sent to the preset's official host; custom never uses them."""
    return preset["id"] != "custom" and bool(preset["base_url"]) and origin(base) == origin(preset["base_url"])


def public_providers():
    return [{**{k: v for k, v in item.items() if k not in ("env", "model_env")},
             "has_key": item["id"] != "custom" and bool(os.environ.get(item["env"])),
             "env_key_scope": "official_host",
             "default_model": os.environ.get(item["model_env"], item["default_model"])} for item in PROVIDERS]


def config(body):
    provider_id = body.get("provider", "deepseek")
    preset = next((p for p in PROVIDERS if p["id"] == provider_id), None)
    if preset is None:
        raise ValueError("未知模型服务商。")
    # Endpoint override is explicit, allowing region/workspace-specific Qwen endpoints.
    base = body.get("base_url", "").strip() or preset["base_url"]
    parsed = urlparse(base)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("请输入不含密钥、查询参数的 API Base URL。")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("远程接口必须使用 HTTPS；HTTP 仅用于本机服务。")
    official = official_endpoint(preset, base)
    explicit = body.get("api_key", "").strip()
    env_key = os.environ.get(preset["env"], "") if official else ""
    key = explicit or env_key
    if preset["requires_key"] and not key:
        if not official and os.environ.get(preset["env"]):
            raise ValueError("已修改 %s 接口地址：环境变量中的 Key 只发送到官方地址，请在设置中填写该地址对应的 API Key。" % preset["name"])
        raise ValueError("请先填写 %s API Key；也可以先运行本地演示。" % preset["name"])
    if "\r" in key or "\n" in key:
        raise ValueError("API Key 格式错误。")
    model = body.get("model", "").strip() or os.environ.get(preset["model_env"], preset["default_model"])
    thinking = body.get("thinking", False)
    if not isinstance(thinking, bool):
        raise ValueError("思考模式必须是布尔值。")
    max_output = body.get("max_output_tokens", 6000)
    context_window = body.get("context_window", 32000)
    if isinstance(max_output, bool) or not isinstance(max_output, int) or not 256 <= max_output <= 16000:
        raise ValueError("最大输出应为 256–16000 tokens。")
    if isinstance(context_window, bool) or not isinstance(context_window, int) or not 4096 <= context_window <= 1000000:
        raise ValueError("上下文预算应为 4096–1000000 tokens。")
    if max_output + 512 >= context_window:
        raise ValueError("上下文预算必须大于最大输出加 512 tokens。")
    return {"provider": provider_id, "name": preset["name"], "base_url": base.rstrip("/"), "api_key": key, "model": model,
            "key_source": "ui" if explicit else "env" if key else "none", "thinking": thinking,
            "max_output_tokens": max_output, "context_window": context_window}


KEY_PATTERN = re.compile(r"(sk-|Bearer\s+)[A-Za-z0-9._\-]{6,}")


def upstream_detail(error, api_key=""):
    """Short, key-free provider error text, so users can tell context-length from bad parameters."""
    try:
        raw = error.read(8192).decode("utf-8", "replace")
    except Exception:
        return ""
    text = raw
    try:
        data = json.loads(raw)
        err = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(err, dict):
            text = err.get("message") or err.get("msg") or err.get("code") or json.dumps(err, ensure_ascii=False)
        elif isinstance(err, str):
            text = err
        if isinstance(data, dict) and not text:
            text = data.get("message", "")
    except (ValueError, AttributeError):
        pass
    text = str(text)
    if api_key:
        text = text.replace(api_key, "***")
    text = KEY_PATTERN.sub(lambda m: m.group(1) + "***", text)
    text = " ".join(text.split())
    return text[:300] + ("…" if len(text) > 300 else "")


def provider_error(settings, error):
    # The raised RuntimeError keeps this response as __context__. Close it so
    # urllib's half-closed client socket does not leak until process shutdown.
    try:
        reasons = {400: "模型名或请求参数不受支持", 401: "API Key 无效或与接口地域不匹配", 402: "余额不足", 403: "接口访问受限", 404: "接口地址或模型不存在", 429: "请求过于频繁"}
        if 300 <= error.code < 400:
            return RuntimeError(settings['name'] + '：接口发生重定向，请填写最终 API 地址')
        detail = upstream_detail(error, settings['api_key'])
        lowered = detail.lower()
        reason = '超出模型上下文长度，请新建会话或减少资料' if error.code in (400, 413) and 'context' in lowered and ('length' in lowered or 'token' in lowered) else reasons.get(error.code, 'HTTP ' + str(error.code))
        return RuntimeError(settings['name'] + '：' + reason + ('（服务商返回：' + detail + '）' if detail else ''))
    finally:
        error.close()


def request_json(settings, suffix, payload=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings["api_key"]:
        headers["Authorization"] = "Bearer " + settings["api_key"]
    req = urllib.request.Request(settings["base_url"] + suffix, headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        method="POST" if payload is not None else "GET")
    try:
        # Never forward a credential to a redirected host.
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=120 if payload else 25) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise provider_error(settings, error) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("无法连接 " + settings["name"] + "，请检查接口地址、网络和服务状态。") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("接口没有返回有效 JSON；请检查 Base URL 是否为 API 地址。") from None


def list_models(settings):
    data = request_json(settings, "/models")
    models = sorted({str(item["id"]) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")})
    return {"models": models[:1000], "provider": settings["provider"], "count": len(models),
            "message": "模型列表接口已连通。对话与工具调用能力需使用相应模型验证。"}


def build_payload(messages, settings, tools=None, stream=False):
    if not settings["model"]:
        raise ValueError("请先读取模型列表并选择，或手动填写模型名称。")
    payload = {"model": settings["model"], "messages": messages, "stream": stream}
    limit = settings.get("max_output_tokens", 6000)
    if settings["provider"] == "openai":
        payload["max_completion_tokens"] = limit
    else:
        payload["max_tokens"] = limit
    if settings["provider"] == "deepseek":
        payload["thinking"] = {"type": "enabled" if settings.get("thinking") else "disabled"}
    if settings["provider"] == "qwen":
        payload["enable_thinking"] = settings.get("thinking", False)
    if tools:
        payload["tools"] = tools
    return payload


def completion(messages, settings, tools=None):
    payload = build_payload(messages, settings, tools)
    data = request_json(settings, "/chat/completions", payload)
    if not data.get("choices"):
        raise RuntimeError("接口未返回有效对话结果，请确认所选模型支持 Chat Completions。")
    if data["choices"][0].get("finish_reason") == "length":
        raise RuntimeError("模型达到输出长度上限，请缩小任务后重试。")
    return data["choices"][0]["message"]


def stream_completion(messages, settings, tools=None, on_delta=None):
    """Assemble SSE content and fragmented tool calls; never expose reasoning text as an answer."""
    payload = build_payload(messages, settings, tools, stream=True)
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if settings["api_key"]:
        headers["Authorization"] = "Bearer " + settings["api_key"]
    request = urllib.request.Request(settings["base_url"] + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    message = {"role": "assistant", "content": ""}
    calls, terminal = {}, False
    def consume(data):
        nonlocal terminal
        if data.get("error"):
            raise RuntimeError("模型流返回错误，当前回答未完成。")
        for choice in data.get("choices", [])[:1]:
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise RuntimeError("输出达到上限或被服务商截断；已显示的内容尚未提交为完整会话。")
            if choice.get("finish_reason"):
                terminal = True
            delta = choice.get("delta", {})
            content = delta.get("content")
            if isinstance(content, str) and content:
                message["content"] += content
                if len(message["content"]) > 200000:
                    raise RuntimeError("模型输出过长，请缩小任务。")
                if on_delta:
                    on_delta(content)
            reasoning = delta.get("reasoning_content")
            if isinstance(reasoning, str):
                message["reasoning_content"] = message.get("reasoning_content", "") + reasoning
                if len(message["reasoning_content"]) > 300000:
                    raise RuntimeError("模型思考输出过长，请关闭思考模式或缩小任务。")
            for part in delta.get("tool_calls", []):
                index = part.get("index", 0)
                if not isinstance(index, int) or not 0 <= index < 8:
                    raise RuntimeError("模型工具调用数量或格式不受支持。")
                call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if part.get("id"):
                    call["id"] = part["id"]
                for field in ("name", "arguments"):
                    call["function"][field] += part.get("function", {}).get(field) or ""
                if len(call["function"]["arguments"]) > 200000:
                    raise RuntimeError("模型工具参数过长。")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
            if "application/json" in response.headers.get("Content-Type", ""):
                data = json.load(response)
                choice = data.get("choices", [{}])[0]
                if choice.get("finish_reason") == "length":
                    raise RuntimeError("模型输出达到上限，当前回答未完成。")
                final = choice.get("message")
                if not isinstance(final, dict):
                    raise RuntimeError("接口没有返回有效对话。")
                if on_delta and final.get("content"):
                    on_delta(final["content"])
                return final
            frame = []
            for raw in response:
                line = raw.decode("utf-8-sig").rstrip("\r\n")
                if len(line) > 1000000:
                    raise RuntimeError("模型流事件过大。")
                if line.startswith("data:"):
                    frame.append(line[5:].lstrip())
                elif not line and frame:
                    event = "\n".join(frame); frame = []
                    if event == "[DONE]":
                        break
                    consume(json.loads(event))
            if frame and "\n".join(frame) != "[DONE]":
                consume(json.loads("\n".join(frame)))
        if not terminal:
            raise RuntimeError("模型流提前中断；当前回答没有完整结束，不会写入会话。")
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
            if any(not c["id"] or not c["function"]["name"] for c in message["tool_calls"]):
                raise RuntimeError("模型工具调用不完整。")
        return message
    except urllib.error.HTTPError as error:
        raise provider_error(settings, error) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("模型连接中断或超时；可检查已显示的部分内容后重试。") from None
    except (json.JSONDecodeError, UnicodeError):
        raise RuntimeError("模型流格式无效，当前回答未完成。") from None
