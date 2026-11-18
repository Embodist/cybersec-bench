#!/usr/bin/env python3
"""Score predictions against the benchmark and emit JSON/Markdown reports."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import (
    CATEGORY_LABELS,
    DIFFICULTY_LABELS,
    iter_jsonl,
    load_questions,
    normalize_answer,
)

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"
PREDICTION_FIELDS = ("answer", "prediction", "response", "output")
DEFAULT_LABEL = "未命名模型"


def load_predictions(path: Path) -> tuple[dict[str, dict[str, Any]], int, int]:
    predictions: dict[str, dict[str, Any]] = {}
    malformed_lines = 0
    duplicates = 0
    for _, record in iter_jsonl(path):
        if not isinstance(record, dict) or not record.get("id"):
            malformed_lines += 1
            continue
        question_id = str(record["id"]).strip()
        if question_id in predictions:
            duplicates += 1
        predictions[question_id] = record
    return predictions, malformed_lines, duplicates


def extract_prediction(record: dict[str, Any], options: dict[str, str]) -> tuple[str | None, Any]:
    for field in PREDICTION_FIELDS:
        if field in record and record[field] is not None:
            return normalize_answer(record[field], options), record[field]
    return None, None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(1 for row in rows if row["correct"])
    answered = sum(1 for row in rows if row["predicted"] is not None)
    return {
        "total": total,
        "correct": correct,
        "answered": answered,
        "accuracy": correct / total if total else 0.0,
        "accuracy_on_answered": correct / answered if answered else 0.0,
    }


def group_summary(rows: list[dict[str, Any]], key: str, order: list[str]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    result: dict[str, dict[str, Any]] = {}
    for name in order:
        if name in grouped:
            result[name] = summarize(grouped[name])
    for name in sorted(set(grouped) - set(order)):
        result[name] = summarize(grouped[name])
    return result


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_markdown(
    report: dict[str, Any],
    rows: list[dict[str, Any]],
    show_errors: bool,
    max_errors: int,
) -> str:
    overall = report["overall"]
    lines = [
        "# 网络安全理解基准评测报告",
        "",
        f"- 评测对象: {report['label']}",
        f"- 题目数: {overall['total']}",
        f"- 有效作答: {overall['answered']}",
        f"- 正确答案数: {overall['correct']}",
        f"- 总体准确率（未作答按错）: {pct(overall['accuracy'])}",
        f"- 已作答准确率: {pct(overall['accuracy_on_answered'])}",
        f"- 未提供预测: {report['missing']}",
        f"- 预测无法解析: {report['invalid']}",
    ]
    if report["malformed_lines"]:
        lines.append(f"- 预测文件格式错误的行: {report['malformed_lines']}")
    if report["duplicates"]:
        lines.append(f"- 重复的预测记录（后者覆盖前者）: {report['duplicates']}")

    lines += [
        "",
        "## 分类准确率",
        "",
        "| 领域 | 题数 | 正确 | 准确率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, stats in report["by_category"].items():
        label = CATEGORY_LABELS.get(category, category)
        lines.append(
            f"| {label} (`{category}`) | {stats['total']} | {stats['correct']} | {pct(stats['accuracy'])} |"
        )

    lines += [
        "",
        "## 难度准确率",
        "",
        "| 难度 | 题数 | 正确 | 准确率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for difficulty, stats in report["by_difficulty"].items():
        label = DIFFICULTY_LABELS.get(difficulty, difficulty)
        lines.append(
            f"| {label} (`{difficulty}`) | {stats['total']} | {stats['correct']} | {pct(stats['accuracy'])} |"
        )

    gold = report["answer_distribution"]["gold"]
    predicted = report["answer_distribution"]["predicted"]
    lines += [
        "",
        "## 答案分布",
        "",
        "| 选项 | 正确答案 | 模型预测 |",
        "| --- | ---: | ---: |",
    ]
    for letter in "ABCD":
        lines.append(f"| {letter} | {gold.get(letter, 0)} | {predicted.get(letter, 0)} |")

    if report["unknown_ids"]:
        lines += ["", "## 未匹配的预测 ID", ""]
        for question_id in report["unknown_ids"][:10]:
            lines.append(f"- `{question_id}`")
        if len(report["unknown_ids"]) > 10:
            lines.append(f"- 其余 {len(report['unknown_ids']) - 10} 个略。")

    if show_errors:
        wrong = [row for row in rows if not row["correct"]]
        lines += ["", "## 错误明细", ""]
        if not wrong:
            lines.append("无。")
        else:
            for row in wrong[:max_errors]:
                predicted_value = row["predicted"] or "未作答/无法解析"
                lines.append(f"- `{row['id']}` 正确答案 {row['gold']}，预测 {predicted_value}")
            if len(wrong) > max_errors:
                lines.append(f"- 其余 {len(wrong) - max_errors} 题略。")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="对网络安全理解基准的预测结果打分")
    parser.add_argument("--questions", default=str(DEFAULT_DATA), help="题目 JSONL 文件或目录")
    parser.add_argument("--predictions", required=True, help="预测 JSONL 文件")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="评测对象名称，用于报告标题")
    parser.add_argument("--out-json", help="写出 JSON 报告")
    parser.add_argument("--out-md", help="写出 Markdown 报告")
    parser.add_argument("--show-errors", action="store_true", help="在报告中列出错误题目")
    parser.add_argument("--max-errors", type=int, default=30, help="错误明细最多展示多少条")
    parser.add_argument(
        "--only-predicted",
        action="store_true",
        help="只统计预测文件中出现的题目，用于冒烟测试或部分跑分",
    )
    args = parser.parse_args()

    try:
        questions = load_questions(args.questions)
        predictions, malformed_lines, duplicates = load_predictions(Path(args.predictions))
    except (OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    question_ids = {question["id"] for question in questions}
    unknown_ids = sorted(set(predictions) - question_ids)

    if args.only_predicted:
        questions = [question for question in questions if question["id"] in predictions]
        if not questions:
            print("错误: 预测文件中没有匹配任何题目", file=sys.stderr)
            return 2

    models = sorted({str(record.get("model")) for record in predictions.values() if record.get("model")})
    label = args.label
    if label == DEFAULT_LABEL and models:
        label = ", ".join(models)

    rows: list[dict[str, Any]] = []
    missing = 0
    invalid = 0
    for question in questions:
        record = predictions.get(question["id"])
        predicted = None
        if record is None:
            missing += 1
        else:
            predicted, _ = extract_prediction(record, question["options"])
            if predicted is None:
                invalid += 1
        rows.append(
            {
                "id": question["id"],
                "category": question["category"],
                "difficulty": question["difficulty"],
                "gold": question["answer"],
                "predicted": predicted,
                "correct": predicted == question["answer"],
            }
        )

    overall = summarize(rows)
    report: dict[str, Any] = {
        "label": label,
        "questions": str(Path(args.questions).resolve()),
        "predictions": str(Path(args.predictions).resolve()),
        "overall": overall,
        "missing": missing,
        "invalid": invalid,
        "malformed_lines": malformed_lines,
        "duplicates": duplicates,
        "unknown_ids": unknown_ids,
        "by_category": group_summary(rows, "category", list(CATEGORY_LABELS)),
        "by_difficulty": group_summary(rows, "difficulty", list(DIFFICULTY_LABELS)),
        "answer_distribution": {
            "gold": dict(Counter(row["gold"] for row in rows)),
            "predicted": dict(Counter(row["predicted"] for row in rows if row["predicted"])),
        },
    }

    markdown = build_markdown(report, rows, args.show_errors, args.max_errors)
    print(markdown, end="")

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text(markdown, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
