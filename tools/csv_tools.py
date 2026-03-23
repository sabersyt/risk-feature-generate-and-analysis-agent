"""
csv_tools.py — 工具函数

"""

import pandas as pd
import json
from pathlib import Path


def load_csv(file_path: str) -> dict:
    """
    加载 CSV 文件，返回基础信息。
    """
    try:
        df = pd.read_csv(file_path)
        return {
            "status": "success",
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": df.columns.tolist(),
            "file_path": file_path,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_column_stats(file_path: str, columns: list = None) -> dict:
    """
    计算字段的统计信息：类型、缺失率、唯一值、数值分布。
    这是 schema-agent 最依赖的工具，相当于原项目里查缺失率的 SQL。
    """
    try:
        df = pd.read_csv(file_path)

        # 如果没指定列，分析全部列
        if columns is None:
            columns = df.columns.tolist()

        result = {}
        for col in columns:
            if col not in df.columns:
                continue

            series = df[col]
            col_info = {
                "dtype": str(series.dtype),
                "missing_count": int(series.isna().sum()),
                "missing_rate": round(series.isna().sum() / len(df), 4),
                "unique_count": int(series.nunique()),
            }

            # 数值型字段：计算分布统计
            if pd.api.types.is_numeric_dtype(series):
                col_info["type"] = "numeric"
                col_info["stats"] = {
                    "min": round(float(series.min()), 4),
                    "max": round(float(series.max()), 4),
                    "mean": round(float(series.mean()), 4),
                    "median": round(float(series.median()), 4),
                    "std": round(float(series.std()), 4),
                }

            # 类别型字段：统计取值分布
            else:
                col_info["type"] = "categorical"
                value_counts = series.value_counts(dropna=False)
                col_info["value_distribution"] = {
                    str(k): int(v)
                    for k, v in value_counts.head(10).items()
                }

            result[col] = col_info

        return {"status": "success", "stats": result}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def execute_feature_code(file_path: str, code: str) -> dict:
    """
    执行 feature-agent 生成的 Pandas 代码，验证特征是否能正常计算。

    这是整个系统最关键的工具：
    - Agent 设计特征、写出代码
    - 这个函数真正执行代码
    - 把执行结果（成功/报错/样本值）返回给 Agent
    - Agent 根据结果判断特征是否可用

    相当于原项目里 sql-executor 的角色。
    """
    try:
        df = pd.read_csv(file_path)

        # 在受控环境里执行代码
        # exec_globals 里放 df 和 pd，代码可以用这两个变量
        exec_globals = {"df": df, "pd": pd}
        exec(code, exec_globals)

        # 执行完之后，从 exec_globals 里把新生成的列找出来
        new_df = exec_globals.get("df")
        original_cols = set(pd.read_csv(file_path).columns)
        new_cols = [c for c in new_df.columns if c not in original_cols]

        if not new_cols:
            return {
                "status": "warning",
                "message": "代码执行成功，但没有检测到新增列",
            }

        # 返回新特征的样本值和基础统计
        preview = {}
        for col in new_cols:
            series = new_df[col]
            preview[col] = {
                "sample_values": series.dropna().head(5).tolist(),
                "missing_rate": round(series.isna().sum() / len(new_df), 4),
                "dtype": str(series.dtype),
            }
            if pd.api.types.is_numeric_dtype(series):
                preview[col]["mean"] = round(float(series.mean()), 4)

        return {
            "status": "success",
            "new_columns": new_cols,
            "preview": preview,
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "hint": "请检查代码语法，确认列名存在于 df 中",
        }


def save_session(session_id: str, data: dict, sessions_dir: str = "sessions") -> dict:
    """保存 session 中间状态到文件，对应原项目的 context.json 机制"""
    try:
        path = Path(sessions_dir) / f"{session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"status": "success", "path": str(path)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def load_session(session_id: str, sessions_dir: str = "sessions") -> dict:
    """读取 session 中间状态"""
    try:
        path = Path(sessions_dir) / f"{session_id}.json"
        if not path.exists():
            return {"status": "not_found"}
        with open(path, encoding="utf-8") as f:
            return {"status": "success", "data": json.load(f)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
