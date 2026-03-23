"""
agents/main_agent.py — 主 Agent 编排器

"""

import json
import anthropic
from datetime import datetime
from pathlib import Path

from agents.sub_agent import run_sub_agent, load_prompt
from tools.csv_tools import save_session


def run_pipeline(file_path: str, verbose: bool = True) -> str:
    """
    完整的特征分析流水线。

    参数：
        file_path: CSV 文件路径
        verbose:   是否打印详细日志

    返回：
        报告文件路径
    """

    # ── 第一步：初始化 session ─────────────────────────────
    session_id = f"fa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_data = {
        "session_id": session_id,
        "file_path": file_path,
        "created_at": datetime.now().isoformat(),
        "schema_result": None,
        "feature_result": None,
        "status": "initialized",
    }
    save_session(session_id, session_data)

    print(f"\n{'='*60}")
    print(f"  特征分析系统启动")
    print(f"  Session ID: {session_id}")
    print(f"  文件: {file_path}")
    print(f"{'='*60}")

    # ── 第二步：调用 schema-agent ─────────────────────────
    schema_prompt = load_prompt("schema_agent")
    schema_task = f"""
请分析以下 CSV 文件的字段结构：
文件路径：{file_path}
Session ID：{session_id}

完成分析后，请用 JSON 格式输出分析结果。
"""

    schema_result_str = run_sub_agent(
        agent_name="schema-agent",
        system_prompt=schema_prompt,
        task=schema_task,
        model="claude-haiku-4-5-20251001",  # schema 分析用 haiku，省 token
        verbose=verbose,
    )

    # 解析 schema-agent 的 JSON 输出
    schema_result = _parse_json_from_text(schema_result_str)

    # 保存 schema 结果
    session_data["schema_result"] = schema_result
    session_data["status"] = "schema_done"
    save_session(session_id, session_data)

    # ── 第三步：展示结果，等用户确认 ─────────────────────
    print(f"\n{'─'*60}")
    print("  📊 Schema 分析完成，摘要如下：")
    if schema_result:
        numeric = schema_result.get("numeric_fields", [])
        categorical = schema_result.get("categorical_fields", [])
        candidates = schema_result.get("derivation_candidates", [])
        print(f"  数值型字段: {len(numeric)} 个 → {numeric}")
        print(f"  类别型字段: {len(categorical)} 个 → {categorical}")
        print(f"  衍生候选: {len(candidates)} 组")
        for c in candidates:
            print(f"    · {c.get('fields')} → {c.get('reason', '')}")
    print(f"{'─'*60}")

    user_input = input("\n是否继续进行特征设计？(直接回车继续 / 输入要求后回车): ").strip()
    extra_requirement = user_input if user_input else ""

    # ── 第四步：调用 feature-agent ────────────────────────
    feature_prompt = load_prompt("feature_agent")
    feature_task = f"""
请基于以下 schema 分析结果，为 CSV 文件设计衍生特征。

文件路径：{file_path}
Session ID：{session_id}

Schema 分析结果：
{json.dumps(schema_result, ensure_ascii=False, indent=2)}

{"用户额外要求：" + extra_requirement if extra_requirement else ""}

请设计特征、生成代码、验证每个特征，最后用 JSON 格式输出特征清单。
"""

    feature_result_str = run_sub_agent(
        agent_name="feature-agent",
        system_prompt=feature_prompt,
        task=feature_task,
        model="claude-sonnet-4-6",  # feature 设计用 sonnet，需要更强的推理
        verbose=verbose,
    )

    feature_result = _parse_json_from_text(feature_result_str)

    # 保存 feature 结果
    session_data["feature_result"] = feature_result
    session_data["status"] = "feature_done"
    save_session(session_id, session_data)

    # ── 第五步：生成报告 ──────────────────────────────────
    report_path = _generate_report(session_id, session_data, file_path)

    # ── 第六步：完成 ─────────────────────────────────────
    session_data["status"] = "completed"
    session_data["report_path"] = report_path
    save_session(session_id, session_data)

    features = feature_result.get("features", []) if feature_result else []
    print(f"\n{'='*60}")
    print(f"  ✅ 分析完成！")
    print(f"  共设计特征: {len(features)} 个")
    print(f"  报告路径: {report_path}")
    print(f"  Session 文件: sessions/{session_id}.json")
    print(f"{'='*60}\n")

    return report_path


def _parse_json_from_text(text: str) -> dict:
    """
    从 Agent 的文字输出里提取 JSON。
    Agent 可能会在 JSON 前后加一些解释文字，这里做容错处理。
    """
    if not text:
        return {}

    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 找 ```json ... ``` 代码块
    import re
    pattern = r"```(?:json)?\s*([\s\S]*?)```"
    matches = re.findall(pattern, text)
    for match in matches:
        try:
            return json.loads(match.strip())
        except Exception:
            continue

    # 找第一个 { ... } 块
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass

    # 解析失败，返回原始文字包装成 dict
    return {"raw_output": text}


def _generate_report(session_id: str, session_data: dict, file_path: str) -> str:
    """生成简单的 HTML 报告"""
    import pandas as pd
    from jinja2 import Template

    schema = session_data.get("schema_result", {}) or {}
    feature_data = session_data.get("feature_result", {}) or {}
    features = feature_data.get("features", [])

    # 读原始数据做预览
    try:
        df = pd.read_csv(file_path)
        data_preview = df.head(5).to_html(classes="table", border=0, index=False)
        total_rows = len(df)
        total_cols = len(df.columns)
    except Exception:
        data_preview = "<p>数据预览失败</p>"
        total_rows = 0
        total_cols = 0

    template_str = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>特征分析报告 - {{ session_id }}</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 1000px; margin: 40px auto; padding: 0 20px; color: #333; }
  h1 { color: #1a1a2e; border-bottom: 3px solid #4a90e2; padding-bottom: 10px; }
  h2 { color: #16213e; margin-top: 40px; }
  .meta { background: #f0f4ff; border-radius: 8px; padding: 16px; margin: 20px 0; }
  .meta span { margin-right: 30px; font-size: 14px; }
  .tag { display: inline-block; background: #e3f2fd; color: #1565c0; padding: 3px 10px; border-radius: 12px; font-size: 13px; margin: 3px; }
  .feature-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin: 12px 0; }
  .feature-card h3 { margin: 0 0 8px; color: #1a1a2e; font-size: 15px; }
  .feature-card .formula { font-family: monospace; background: #f5f5f5; padding: 8px; border-radius: 4px; font-size: 13px; }
  .feature-card .hypothesis { color: #555; font-size: 14px; margin: 8px 0; border-left: 3px solid #4a90e2; padding-left: 10px; }
  .badge { display: inline-block; background: #e8f5e9; color: #2e7d32; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { background: #f5f7ff; padding: 10px; text-align: left; border-bottom: 2px solid #ddd; }
  td { padding: 8px 10px; border-bottom: 1px solid #eee; }
  .candidate { background: #fff8e1; border-left: 3px solid #ffa000; padding: 10px; margin: 8px 0; border-radius: 4px; font-size: 14px; }
</style>
</head>
<body>
<h1>📊 特征分析报告</h1>

<div class="meta">
  <span>Session: <b>{{ session_id }}</b></span>
  <span>文件: <b>{{ file_path }}</b></span>
  <span>数据: <b>{{ total_rows }}</b> 行 × <b>{{ total_cols }}</b> 列</span>
</div>

<h2>字段结构</h2>
<p>
  <b>数值型字段 ({{ schema.numeric_fields|length }}个)：</b><br>
  {% for f in schema.numeric_fields %}<span class="tag">{{ f }}</span>{% endfor %}
</p>
<p>
  <b>类别型字段 ({{ schema.categorical_fields|length }}个)：</b><br>
  {% for f in schema.categorical_fields %}<span class="tag">{{ f }}</span>{% endfor %}
</p>
{% if schema.target_field %}
<p><b>目标字段（Y列）：</b><span class="tag">{{ schema.target_field }}</span></p>
{% endif %}
{% if schema.quality_issues %}
<h2>数据质量问题</h2>
{% for issue in schema.quality_issues %}
<div class="candidate">⚠️ {{ issue.field }}: 缺失率 {{ issue.missing_rate }} — {{ issue.note }}</div>
{% endfor %}
{% endif %}

<h2>衍生特征 ({{ features|length }} 个验证通过)</h2>
{% for f in features %}
<div class="feature-card">
  <h3>{{ f.name }} <span style="font-weight:normal;color:#888;font-size:13px">{{ f.cn }}</span>
    <span class="badge" style="float:right">✅ {{ f.status }}</span>
  </h3>
  <div class="formula">{{ f.formula }}</div>
  <div class="hypothesis">{{ f.hypothesis }}</div>
  <small>缺失率: {{ f.missing_rate }}</small>
</div>
{% endfor %}

<h2>原始数据预览（前5行）</h2>
{{ data_preview }}

<p style="color:#999;font-size:12px;margin-top:40px">
  生成时间: {{ generated_at }} | Feature Analysis Agent
</p>
</body>
</html>
"""

    template = Template(template_str)
    html = template.render(
        session_id=session_id,
        file_path=file_path,
        total_rows=total_rows,
        total_cols=total_cols,
        schema=schema,
        features=features,
        data_preview=data_preview,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)
    report_path = str(report_dir / f"{session_id}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    return report_path


from datetime import datetime
