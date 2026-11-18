#!/usr/bin/env python3
"""Validate benchmark structure and print distribution statistics."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from common import CATEGORY_LABELS, DIFFICULTY_LABELS, load_questions

REQUIRED_FIELDS = ("id", "category", "difficulty", "question", "options", "answer", "explanation")
OPTION_KEYS = {"A", "B", "C", "D"}


def main() -> int:
    parser = argparse.ArgumentParser(description="校验网络安全理解基准数据")
    parser.add_argument("questions", nargs="?", default=str(Path(__file__).resolve().parent.parent / "data"),
                        help="题目 JSONL 文件或目录")
    args = parser.parse_args()

    try:
        questions = load_questions(args.questions)
    except ValueError as exc:
        print(f"加载失败: {exc}", file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    categories = Counter()
    difficulties = Counter()
    answers = Counter()

    for index, question in enumerate(questions, 1):
        location = f"{question.get('_source', '?')}:{question.get('id', f'#{index}')}"

        for field in REQUIRED_FIELDS:
            if field not in question:
                errors.append(f"{location}: 缺少字段 {field}")
        if errors and location.startswith("?"):
            continue

        question_id = question.get("id")
        if not isinstance(question_id, str) or not question_id.strip():
            errors.append(f"{location}: id 必须是非空字符串")
        elif question_id in seen_ids:
            errors.append(f"{location}: id 重复")
        else:
            seen_ids.add(question_id)

        category = question.get("category")
        if category not in CATEGORY_LABELS:
            errors.append(f"{location}: 未知 category {category!r}")
        else:
            categories[category] += 1

        difficulty = question.get("difficulty")
        if difficulty not in DIFFICULTY_LABELS:
            errors.append(f"{location}: 未知 difficulty {difficulty!r}")
        else:
            difficulties[difficulty] += 1

        for field in ("question", "explanation"):
            value = question.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{location}: {field} 必须是非空字符串")

        options = question.get("options")
        if not isinstance(options, dict):
            errors.append(f"{location}: options 必须是对象")
        else:
            keys = set(options)
            if keys != OPTION_KEYS:
                errors.append(f"{location}: options 必须恰好包含 A/B/C/D，实际为 {sorted(keys)}")
            option_texts = [str(value).strip() for value in options.values()]
            if any(not text for text in option_texts):
                errors.append(f"{location}: 存在空选项")
            if len(option_texts) != len(set(option_texts)):
                errors.append(f"{location}: 选项文本重复")

            answer = question.get("answer")
            if answer not in OPTION_KEYS:
                errors.append(f"{location}: answer 必须是 A/B/C/D")
            elif answer not in options:
                errors.append(f"{location}: answer {answer} 不在 options 中")
            else:
                answers[answer] += 1

        tags = question.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            errors.append(f"{location}: tags 必须是字符串数组")

    print(f"题目文件: {Path(args.questions).resolve()}")
    print(f"题目总数: {len(questions)}")
    print("\n分类分布:")
    for key, label in CATEGORY_LABELS.items():
        print(f"  {key:<12} {label:<24} {categories.get(key, 0):>3}")
    print("\n难度分布:")
    for key, label in DIFFICULTY_LABELS.items():
        print(f"  {key:<12} {label:<8} {difficulties.get(key, 0):>3}")
    print("\n答案分布:")
    for key in sorted(OPTION_KEYS):
        print(f"  {key}: {answers.get(key, 0)}")

    if warnings:
        print("\n警告:")
        for warning in warnings:
            print(f"  - {warning}")

    if errors:
        print(f"\n校验失败，共 {len(errors)} 个问题:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("\n校验结果: 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
