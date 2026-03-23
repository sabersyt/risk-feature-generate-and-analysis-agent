"""
agents/sub_agent.py — Sub-agent 通用执行器

"""

import json
import anthropic
from pathlib import Path

# 导入所有工具函数
from tools.csv_tools import (
    load_csv,
    get_column_stats,
    execute_feature_code,
    save_session,
    load_session,
)

# ── 工具注册表 ──────────────────────────────────────────────
# key = 工具名（Claude 会用这个名字调用）
# value = 对应的 Python 函数
TOOL_REGISTRY = {
    "load_csv": load_csv,
    "get_column_stats": get_column_stats,
    "execute_feature_code": execute_feature_code,
    "save_session": save_session,
    "load_session": load_session,
}

# ── 工具定义（告诉 Claude 每个工具的参数格式）────────────────
# 这是发给 Claude API 的 tools 参数
# Claude 读了这些定义，才知道怎么调用每个工具
TOOL_DEFINITIONS = [
    {
        "name": "load_csv",
        "description": "加载 CSV 文件，返回基础信息（行数、列数、字段名）",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "CSV 文件路径",
                }
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "get_column_stats",
        "description": "计算字段的统计信息：类型、缺失率、唯一值数量、数值分布或类别分布",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "CSV 文件路径",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要分析的列名列表，不传则分析全部列",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "execute_feature_code",
        "description": "执行 Pandas 代码，验证衍生特征能否正确计算，返回新列的样本值和统计",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "CSV 文件路径",
                },
                "code": {
                    "type": "string",
                    "description": "要执行的 Pandas 代码，必须操作变量 df，新特征赋值到 df['feature_name']",
                },
            },
            "required": ["file_path", "code"],
        },
    },
    {
        "name": "save_session",
        "description": "保存中间状态到 session 文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "data": {"type": "object", "description": "要保存的数据"},
                "sessions_dir": {"type": "string", "default": "sessions"},
            },
            "required": ["session_id", "data"],
        },
    },
    {
        "name": "load_session",
        "description": "读取 session 中间状态",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "sessions_dir": {"type": "string", "default": "sessions"},
            },
            "required": ["session_id"],
        },
    },
]


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    根据工具名找到对应函数并执行。
    返回 JSON 字符串（塞回 messages 时必须是字符串）。
    """
    if tool_name not in TOOL_REGISTRY:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

    func = TOOL_REGISTRY[tool_name]
    try:
        result = func(**tool_input)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def run_sub_agent(
    agent_name: str,
    system_prompt: str,
    task: str,
    model: str = "claude-haiku-4-5-20251001",
    max_turns: int = 10,
    verbose: bool = True,
) -> str:
    """
    运行一个 Sub-agent，直到它完成任务（不再调用工具）。

    参数：
        agent_name:    Sub-agent 名字（只用于日志打印）
        system_prompt: 从 prompts/*.md 读取的 system prompt
        task:          主 Agent 给这个 Sub-agent 的具体任务描述
        model:         使用的模型（schema-agent 用 haiku 省 token）
        max_turns:     最多循环多少轮，防止死循环
        verbose:       是否打印每一步的工具调用

    返回：
        Sub-agent 的最终文字输出
    """
    client = anthropic.Anthropic()

    messages = [
        {"role": "user", "content": task}
    ]

    if verbose:
        print(f"\n{'='*50}")
        print(f"▶ 启动 {agent_name}")
        print(f"  任务: {task[:80]}...")
        print(f"{'='*50}")

    for turn in range(max_turns):
        # ── 调用 Claude API ────────────────────────────────
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if verbose:
            print(f"\n  [轮次 {turn+1}] stop_reason: {response.stop_reason}")

        # ── 把 assistant 的回复加入 messages ──────────────
        # 注意：不管有没有工具调用，都要把 assistant 回复加进去
        # 否则下一轮 API 会报错（历史不完整）
        messages.append({
            "role": "assistant",
            "content": response.content,
        })

        # ── 如果没有工具调用，说明 Sub-agent 完成了 ─────────
        if response.stop_reason == "end_turn":
            # 找到最后一段文字输出
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
            if verbose:
                print(f"\n  ✅ {agent_name} 完成")
            return final_text

        # ── 有工具调用：执行每个工具，收集结果 ──────────────
        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                if verbose:
                    print(f"  🔧 调用工具: {tool_name}")
                    print(f"     参数: {json.dumps(tool_input, ensure_ascii=False)[:100]}")

                result_str = execute_tool(tool_name, tool_input)

                if verbose:
                    print(f"     结果: {result_str[:100]}...")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,  # 必须和 tool_use 的 id 对应
                    "content": result_str,
                })

            messages.append({
                "role": "user",
                "content": tool_results,
            })

    # 超过最大轮次
    return f"[{agent_name}] 超过最大轮次 ({max_turns})，任务未完成"


def load_prompt(agent_name: str) -> str:
    """从 prompts/ 目录读取 system prompt"""
    prompt_path = Path("prompts") / f"{agent_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"找不到 prompt 文件: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
