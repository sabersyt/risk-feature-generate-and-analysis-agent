# Feature Analysis Agent

一个基于 Claude 的多 Agent 特征分析系统，自动分析 CSV 数据集的字段结构，设计并验证衍生特征，生成 HTML 报告。

## 架构

```
用户输入 CSV
      ↓
主 Agent（编排）
      ↓           ↓            ↓
schema-agent   feature-agent  report
分析字段结构   设计衍生特征   生成HTML报告
(haiku)        (sonnet)
```

每个 Sub-agent 都是独立的对话上下文，通过工具调用真正操作数据，主 Agent 只负责调度。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 API Key
export ANTHROPIC_API_KEY=your-key-here

# 运行
python run.py sample_data/loan_data.csv
```

## 项目结构

```
├── agents/
│   ├── sub_agent.py      # Sub-agent 通用执行器（工具调用循环）
│   └── main_agent.py     # 主 Agent 编排逻辑
├── tools/
│   └── csv_tools.py      # 工具函数（相当于 MCP Server）
├── prompts/
│   ├── main_agent.md     # 主 Agent system prompt
│   ├── schema_agent.md   # schema-agent system prompt
│   └── feature_agent.md  # feature-agent system prompt
├── sessions/             # 运行时中间状态（context.json）
├── reports/              # 生成的 HTML 报告
└── sample_data/          # 示例数据
```


