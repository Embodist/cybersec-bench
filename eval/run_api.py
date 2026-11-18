#!/usr/bin/env python3
"""Run the benchmark against any OpenAI-compatible chat completions API."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common import load_questions

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"

SYSTEM_PROMPT = (
    "你是一名网络安全专家，正在参加严格的知识评测。"
    "请独立作答，不要依赖外部工具。"
    "只输出一个 JSON 对象，不要输出 Markdown 代码块或其他文字。"
)


class APIError(RuntimeError):
    def __init__(self, message: str, retriable: bool = False) -> None:
        super().__init__(message)
        self.retriable = retriable


def build_messages(question: dict[str, Any]) -> list[dict[str, str]]:
    options = question["options"]
    option_lines = "\n".join(f"{key}. {options[key]}" for key in ("A", "B", "C", "D"))
    user_prompt = (
        f"题目：{question['question']}\n\n{option_lines}\n\n"
        "请从 A/B/C/D 中选择唯一正确答案。\n"
        '只输出如下格式的 JSON：{"answer": "A|B|C|D", "confidence": 0.0-1.0}'
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _extract_letter(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if len(text) == 1 and text in "ABCD":
        return text
    match = re.search(r"(?:^|[^A-Z])([A-D])(?:$|[^A-Z])", text)
    return match.group(1) if match else None


def _to_confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def parse_response(content: str) -> tuple[str | None, float | None]:
    text = (content or "").strip()
    if not text:
        return None, None

    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)
    candidates = [cleaned]
    object_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        answer = payload.get("answer")
        if answer is None:
            answer = payload.get("option")
        letter = _extract_letter(answer)
        if letter:
            return letter, _to_confidence(payload.get("confidence"))

    upper = text.upper()
    labelled = re.search(r"(?:答案|ANSWER)\s*(?:IS|是|为|[:：])?\s*([A-D])(?:[\s.、):：]|$)", upper)
    if labelled:
        return labelled.group(1), None
    leading = re.match(r"^\s*([A-D])(?:[\s.、):：]|$)", upper)
    if leading:
        return leading.group(1), None
    return None, None


def call_api(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        retriable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise APIError(f"HTTP {exc.code}: {detail}", retriable=retriable) from exc
    except urllib.error.URLError as exc:
        raise APIError(f"网络错误: {exc.reason}", retriable=True) from exc
    except TimeoutError as exc:
        raise APIError("请求超时", retriable=True) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise APIError(f"响应不是 JSON: {body[:300]}") from exc
    try:
        content = data["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise APIError(f"响应缺少 choices/message: {body[:300]}") from exc
    return content


def call_with_retry(
    args: argparse.Namespace,
    api_key: str,
    messages: list[dict[str, str]],
) -> str:
    last_error: APIError | None = None
    for attempt in range(args.retries):
        try:
            return call_api(
                args.base_url,
                api_key,
                args.model,
                messages,
                args.timeout,
                args.max_tokens,
                args.temperature,
            )
        except APIError as exc:
            last_error = exc
            if not exc.retriable or attempt == args.retries - 1:
                raise
            time.sleep(min(2 ** attempt, 30))
    raise last_error or APIError("请求失败")


def solve_one(
    question: dict[str, Any],
    args: argparse.Namespace,
    api_key: str,
) -> dict[str, Any]:
    started = time.monotonic()
    record: dict[str, Any] = {
        "id": question["id"],
        "category": question["category"],
        "difficulty": question["difficulty"],
        "model": args.model,
    }
    try:
        content = call_with_retry(args, api_key, build_messages(question))
        answer, confidence = parse_response(content)
        record.update(
            {
                "answer": answer,
                "confidence": confidence,
                "raw": content[:4000],
            }
        )
        if answer is None:
            record["error"] = "无法从模型输出中解析 A/B/C/D"
    except Exception as exc:  # keep per-question failures in the output file
        record.update(
            {
                "answer": None,
                "confidence": None,
                "error": str(exc)[:1000],
            }
        )
    record["latency_ms"] = int((time.monotonic() - started) * 1000)
    return record


def load_completed_ids(path: Path) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("id"):
                completed.add(str(record["id"]))
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description="用 OpenAI 兼容接口跑网络安全理解基准")
    parser.add_argument("--questions", default=str(DEFAULT_DATA), help="题目 JSONL 文件或目录")
    parser.add_argument("--out", default="predictions.jsonl", help="预测结果输出文件")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                        help="API 基址，如 https://api.deepseek.com/v1")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"), help="模型名称")
    parser.add_argument("--api-key", help="直接指定 API Key（默认从 --api-key-env 读取）")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="保存 API Key 的环境变量名")
    parser.add_argument("--concurrency", type=int, default=4, help="并发请求数")
    parser.add_argument("--timeout", type=float, default=180.0, help="单次请求超时秒数")
    parser.add_argument("--retries", type=int, default=5, help="失败重试次数")
    parser.add_argument("--max-tokens", type=int, default=512, help="最大生成 token 数")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度")
    parser.add_argument("--limit", type=int, help="只跑前 N 题，用于冒烟测试")
    parser.add_argument("--resume", action="store_true", help="跳过输出文件中已有结果的题目")
    parser.add_argument("--dry-run", action="store_true", help="只打印提示词，不调用 API")
    args = parser.parse_args()

    try:
        questions = load_questions(args.questions)
    except (OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    if args.limit:
        questions = questions[: args.limit]

    if args.dry_run:
        print(f"题目数: {len(questions)}")
        print(json.dumps(build_messages(questions[0]), ensure_ascii=False, indent=2))
        return 0

    if not args.model:
        parser.error("缺少 --model（或设置 OPENAI_MODEL 环境变量）")

    api_key = args.api_key or os.environ.get(args.api_key_env)
    if not api_key:
        if any(host in args.base_url for host in ("localhost", "127.0.0.1", "0.0.0.0")):
            api_key = "EMPTY"
        else:
            parser.error(f"缺少 API Key：请设置环境变量 {args.api_key_env} 或传入 --api-key")

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = load_completed_ids(output_path) if args.resume else set()
    pending = [question for question in questions if question["id"] not in completed]
    mode = "a" if args.resume else "w"

    print(
        f"题目 {len(questions)} 道，已完成 {len(completed)}，待跑 {len(pending)}，"
        f"并发 {args.concurrency}，模型 {args.model}",
        file=sys.stderr,
    )

    success = 0
    failed = 0
    parsed_failed = 0

    try:
        with output_path.open(mode, encoding="utf-8") as handle, ThreadPoolExecutor(
            max_workers=max(1, args.concurrency)
        ) as executor:
            futures = {
                executor.submit(solve_one, question, args, api_key): question
                for question in pending
            }
            total = len(futures)
            for index, future in enumerate(as_completed(futures), 1):
                record = future.result()
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                if record.get("answer"):
                    success += 1
                else:
                    if record.get("error"):
                        failed += 1
                    else:
                        parsed_failed += 1
                if index % 10 == 0 or index == total:
                    print(
                        f"进度 {index}/{total} | 成功 {success} | 失败 {failed + parsed_failed}",
                        file=sys.stderr,
                    )
    except KeyboardInterrupt:
        print("\n已中断，已完成的结果已写入输出文件；可使用 --resume 继续。", file=sys.stderr)
        return 130

    print(
        f"完成: 成功 {success}，请求失败 {failed}，解析失败 {parsed_failed}\n"
        f"输出: {output_path.resolve()}\n"
        f"下一步: python3 eval/score.py --predictions {output_path} --label \"{args.model}\"",
        file=sys.stderr,
    )
    if success == 0 and pending:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
