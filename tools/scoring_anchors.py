# -*- coding: utf-8 -*-
"""评分锚点规范数据的加载与结构校验。"""

import json
from pathlib import Path

try:
    from .common import DIMS
except ImportError:  # 支持 `python tools/...` 直接执行路径。
    from common import DIMS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "scoring_anchors.json"
EXPECTED_KEYS = ["likelihood", *DIMS]
EXPECTED_SCORES = [1, 2, 3, 4, 5]


def load_scoring_anchors(path=None):
    """读取 UTF-8 锚点真源，并确保维度顺序和 1~5 分档完整。"""
    source_path = Path(path) if path is not None else DEFAULT_PATH
    try:
        groups = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"评分锚点文件不存在: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"评分锚点 JSON 无法解析: {source_path}: {exc.msg}") from exc

    if not isinstance(groups, list):
        raise ValueError("评分锚点必须是按规范顺序排列的组列表")
    keys = [group.get("key") if isinstance(group, dict) else None for group in groups]
    if keys != EXPECTED_KEYS:
        raise ValueError(f"评分锚点组顺序必须为 {EXPECTED_KEYS}，实际为 {keys}")
    for group in groups:
        key = group["key"]
        if not isinstance(group.get("label"), str) or not group["label"].strip():
            raise ValueError(f"评分锚点组 {key} 缺少非空 label")
        rows = group.get("rows")
        if not isinstance(rows, list):
            raise ValueError(f"评分锚点组 {key} 的 rows 必须为列表")
        scores = [row.get("score") if isinstance(row, dict) else None for row in rows]
        if scores != EXPECTED_SCORES:
            raise ValueError(f"评分锚点组 {key} 的 score 必须完整且顺序为 {EXPECTED_SCORES}，实际为 {scores}")
        for row in rows:
            for field in ("anchor", "source"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError(f"评分锚点组 {key} 的 score {row['score']} 缺少非空 {field}")
    return groups
