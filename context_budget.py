"""Conservative local context accounting; never split a tool-call/result group."""
import json


def estimate_tokens(value):
    # UTF-8 bytes are a deliberately conservative upper estimate, not a tokenizer count.
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 16


def fit_context(messages, settings, tools=None):
    limit = settings.get('context_window', 32000)
    reserved = settings.get('max_output_tokens', 6000) + 512
    schema_cost = estimate_tokens(tools) if tools else 0
    dropped = 0
    def cost():
        return estimate_tokens(messages) + schema_cost
    while cost() + reserved > limit:
        users = [i for i, m in enumerate(messages) if m.get('role') == 'user']
        if len(users) < 2:
            raise ValueError('当前任务或工具结果超出上下文预算。最新任务未被裁剪；请减少资料、分页读取，或在模型设置中填写该模型实际支持的更大预算。')
        # Keep leading system guidance and the entire latest user turn, including all tools.
        del messages[users[0]:users[1]]
        dropped += 1
    return {'estimated_input': cost(), 'reserved_output': reserved - 512,
            'context_window': limit, 'dropped_turns': dropped, 'estimate_method': 'utf8_bytes_upper_estimate'}
