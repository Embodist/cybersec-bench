# 网络安全理解基准（CyberSec Understanding Bench）

一套中文单选题基准，用于测模型对网络安全知识的“原始理解能力”：120 道题，10 个领域 × 12 题，简单 / 中等 / 困难各 40 题，正确答案在 A/B/C/D 上各 30 题。

它测的是知识与分析判断，不测真实环境里的动手渗透能力。要评估自动化渗透 agent，建议再配合 CyberGym、Cybench、CVE-Bench 这类可执行基准。

## 目录结构

```
cybersec_bench/
├── data/                  # 10 个领域，每个 12 题
│   ├── 01-network.jsonl
│   ├── 02-web.jsonl
│   ├── 03-crypto.jsonl
│   ├── 04-binary.jsonl
│   ├── 05-reverse.jsonl
│   ├── 06-forensics.jsonl
│   ├── 07-threat-intel.jsonl
│   ├── 08-cloud.jsonl
│   ├── 09-identity.jsonl
│   └── 10-detection.jsonl
├── eval/
│   ├── common.py          # 加载、答案归一化
│   ├── validate.py        # 数据校验与分布统计
│   ├── score.py           # 预测结果评分
│   └── run_api.py         # OpenAI 兼容接口跑分
└── examples/
    └── predictions.example.jsonl
```

## 领域分布

| 领域 | 标识 | 题数 |
| --- | --- | ---: |
| 网络协议与流量分析 | `network` | 12 |
| Web 安全 | `web` | 12 |
| 密码学 | `crypto` | 12 |
| 二进制与内存安全 | `binary` | 12 |
| 逆向工程 | `reverse` | 12 |
| 取证与应急响应 | `forensics` | 12 |
| 威胁情报与 ATT&CK | `threat-intel` | 12 |
| 云与容器安全 | `cloud` | 12 |
| 身份认证与 AD 安全 | `identity` | 12 |
| 检测工程与安全架构 | `detection` | 12 |

## 数据格式

每行一个 JSON 对象：

```json
{"id": "WEB-001", "category": "web", "subcategory": "sqli", "difficulty": "easy", "question": "SQL 注入漏洞产生的根本原因是？", "options": {"A": "数据库未开启加密", "B": "Web 服务器未配置 HTTPS", "C": "数据库端口暴露在公网", "D": "用户输入被当作 SQL 代码拼接，代码与数据未分离"}, "answer": "D", "explanation": "当用户输入被拼接进 SQL 语句并被数据库解释为代码时，攻击者可以改变查询语义。", "tags": ["cwe:CWE-89", "mitre:T1190"]}
```

| 字段 | 说明 |
| --- | --- |
| `id` | 全局唯一题目 ID |
| `category` | 领域标识，与 `eval/common.py` 中的映射对应 |
| `subcategory` | 细分类别，便于后续切片分析 |
| `difficulty` | `easy` / `medium` / `hard` |
| `question` | 题干 |
| `options` | 恰好 A/B/C/D 四个选项 |
| `answer` | 唯一正确选项字母 |
| `explanation` | 答案解析 |
| `tags` | 可选的 CWE / ATT&CK 标签 |

## 快速开始

```bash
cd cybersec_bench

# 1. 校验数据
python3 eval/validate.py

# 2. 查看发给模型的提示词（不调用 API）
python3 eval/run_api.py --dry-run

# 3. 跑一个模型
export OPENAI_API_KEY="你的密钥"
python3 eval/run_api.py \
  --base-url https://api.deepseek.com/v1 \
  --model deepseek-chat \
  --out results/deepseek-chat.jsonl

# 4. 评分（自动输出 Markdown，可选写出 JSON/Markdown 文件）
python3 eval/score.py \
  --predictions results/deepseek-chat.jsonl \
  --label "deepseek-chat" \
  --show-errors \
  --out-json results/deepseek-chat.json \
  --out-md results/deepseek-chat.md
```

断点续跑：

```bash
python3 eval/run_api.py --model deepseek-chat --out results/deepseek-chat.jsonl --resume
```

只跑前 10 题做冒烟测试：

```bash
python3 eval/run_api.py --model deepseek-chat --limit 10 --out results/smoke.jsonl
python3 eval/score.py --predictions results/smoke.jsonl --only-predicted
```

`--only-predicted` 只统计预测文件中出现的题目，避免部分跑分时把其余题目按未作答计入总分。

## 支持的接口

`run_api.py` 只依赖 Python 标准库，调用 OpenAI 兼容的 `/chat/completions`：

| 服务 | base-url 示例 | 说明 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | 从 `OPENAI_API_KEY` 读取密钥 |
| DeepSeek | `https://api.deepseek.com/v1` | 同上 |
| 通义千问兼容模式 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 同上 |
| 本地 vLLM | `http://localhost:8000/v1` | 无密钥时自动使用 `EMPTY` |
| Ollama | `http://localhost:11434/v1` | 无密钥时自动使用 `EMPTY` |

也可用 `--api-key` 直接传入密钥，或用 `--api-key-env` 指定其他环境变量名。推理模型响应较慢时，建议把 `--concurrency` 降到 1–2。

## 预测文件格式

`score.py` 每行读取一条预测：

```json
{"id": "NET-001", "answer": "C", "model": "demo"}
{"id": "NET-002", "answer": "53", "model": "demo"}
{"id": "WEB-001", "answer": "答案是 D", "model": "demo"}
```

`answer` 字段支持：

- 单个字母，如 `"C"`
- 选项原文，如 `"53"`
- 自然语言中包含答案，如 `"答案是 D"`

缺失记录、无法解析的答案会单独统计，并在总体准确率中按错误计算。存在重复 ID 时后者覆盖前者。

## 评分口径

- **总体准确率**：正确题数 / 全部题数，未作答按错误计算
- **已作答准确率**：正确题数 / 有效作答数，用于区分“不会做”和“答错”
- **分类 / 难度准确率**：定位能力短板
- **答案分布**：检查模型是否异常偏向某个字母

120 题在 50% 准确率附近的 95% 置信区间约为 ±9 个百分点。比较两个模型时，2–3 个百分点的差距不足以说明问题；建议多次采样、固定温度 0，或扩大题量。

## 扩展题目

1. 在 `data/` 新增 `11-your-domain.jsonl`，沿用现有字段和 ID 规则。
2. 新领域要在 `eval/common.py` 的 `CATEGORY_LABELS` 中注册，否则校验会失败。
3. 运行 `python3 eval/validate.py` 做全量校验。
4. 新题避免与公开评测集重复；如果这套数据用作评测集，就不要拿它参与训练，避免污染。

## 设计原则与限制

- 每题只有一个无歧义的正确答案，干扰项针对常见误解设计。
- 简单题考概念与术语，中等题考机制与配置，困难题考利用链、边界条件和缓解措施的适用范围。
- 不包含真实凭证、真实目标地址或可直接运行的攻击载荷。
- 题目为原创内容。公开发布后需注意训练数据污染：报告结果时应固定数据集版本，避免模型已经见过题目后仍被当作零样本评测。
- 知识理解分数高不等于能完成真实渗透；请与可执行环境基准组合评估。

## 合规

本数据集用于授权的安全测试、防御研究和教学。对真实系统进行测试前必须获得明确书面授权。
