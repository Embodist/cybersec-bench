"""Shared helpers for the cybersecurity understanding benchmark."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

CATEGORY_LABELS = {
    "network": "网络协议与流量分析",
    "web": "Web 安全",
    "crypto": "密码学",
    "binary": "二进制与内存安全",
    "reverse": "逆向工程",
    "forensics": "取证与应急响应",
    "threat-intel": "威胁情报与 ATT&CK",
    "cloud": "云与容器安全",
    "identity": "身份认证与 AD 安全",
    "detection": "检测工程与安全架构",
}

DIFFICULTY_LABELS = {
    "easy": "简单",
    "medium": "中等",
    "hard": "困难",
}


def iter_jsonl(path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: JSON 解析失败: {exc}") from exc


def load_questions(path: str | Path) -> List[Dict[str, Any]]:
    target = Path(path)
    files = sorted(target.glob("*.jsonl")) if target.is_dir() else [target]
    questions: List[Dict[str, Any]] = []
    for file_path in files:
        for _, record in iter_jsonl(file_path):
            record["_source"] = str(file_path)
            questions.append(record)
    if not questions:
        raise ValueError(f"未找到题目: {target}")
    return questions


def normalize_answer(value: Any, options: Dict[str, str]) -> str | None:
    """Turn model output or option text into a single option letter."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    upper = text.upper()
    if len(upper) == 1 and upper in options:
        return upper

    for key, option in options.items():
        if text == option.strip():
            return key

    labelled = re.search(
        r"(?:答案|ANSWER|OPTION|选项)\s*(?:IS|是|为|[:：])?\s*([A-D])(?:[\s.、):：]|$)",
        upper,
    )
    if labelled:
        return labelled.group(1)

    leading = re.match(r"^\s*([A-D])(?:[\s.、):：]|$)", upper)
    if leading:
        return leading.group(1)

    for key, option in options.items():
        option = option.strip()
        if option and option in text:
            return key
    return None
