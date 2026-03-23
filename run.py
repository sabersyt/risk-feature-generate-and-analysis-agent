"""
run.py — 项目入口

用法：
  python run.py sample_data/loan_data.csv
  python run.py sample_data/loan_data.csv --quiet
"""

import sys
import os
from pathlib import Path

# 把项目根目录加进 Python 路径，确保 import 能找到 agents/ tools/
sys.path.insert(0, str(Path(__file__).parent))

from agents.main_agent import run_pipeline


def main():
    # 解析参数
    if len(sys.argv) < 2:
        print("用法: python run.py <csv文件路径> [--quiet]")
        print("示例: python run.py sample_data/loan_data.csv")
        sys.exit(1)

    file_path = sys.argv[1]
    verbose = "--quiet" not in sys.argv

    # 检查文件存在
    if not Path(file_path).exists():
        print(f"❌ 文件不存在: {file_path}")
        sys.exit(1)

    # 检查 API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ 请设置环境变量 ANTHROPIC_API_KEY")
        print("   export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    # 启动流水线
    report_path = run_pipeline(file_path, verbose=verbose)
    print(f"报告已生成: {report_path}")


if __name__ == "__main__":
    main()
