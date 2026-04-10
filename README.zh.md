<div align="center">

# ⚔️ AI Colosseum debate

**多智能体辩论竞技场 — 让 AI 模型一较高下**

*让多个模型智能体在同一个任务上对决，冻结共享上下文包，*
*独立生成方案，进行以证据为先的辩论，并产出由裁判背书的判决。*

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

**🌐 Language / 언어 / 语言:** [English](README.md) · [한국어](README.ko.md) · **中文**

---

🏛️ **公平** · 🔍 **可追溯** · 💰 **成本可控** · 📊 **证据优先** · 🔌 **可扩展**

</div>

<br>

## 🎯 为什么选择 Colosseum？

> 它不是又一个聊天机器人 UI — Colosseum 是为真实工作流设计的**结构化辩论平台**。

| 痛点 | AI Colosseum debate 的答案 |
|---|---|
| "哪个模型给出的方案更好？" | 在**完全相同的冻结上下文**上并列运行 |
| "怎样才能公平地比较？" | 独立的方案生成 — 任何智能体都不会先看到其他智能体的方案 |
| "辩论无休止地兜圈子" | 带**新颖度检查**、收敛检测和预算上限的有界轮次 |
| "我无法追踪决策是怎么作出的" | 完整的产物链：方案、轮次、裁判议程、采纳论点、判决 |
| "我希望能控制评判方式" | 三种模式可选：**自动**、**AI 裁判**、**人类裁判** |
| "我需要的是代码评审，不是单纯的辩论" | 多阶段**代码评审**，6 个可配置的评审阶段 |
| "我希望多个 AI 智能体并行 QA 我的项目" | **QA 集成模式** — 斗士们在 disjoint GPU 切片上并行运行，裁判把发现合并为一份去重后的报告 |

---

## ✨ 功能特性

<table>
<tr>
<td width="50%" valign="top">

### 🧊 冻结上下文包
每个智能体都获得完全相同的输入 — 文本、文件、目录、URL 与图像 — 在规划开始之前一次性冻结。

### 🤖 多供应商支持
Claude · Codex · Gemini · Ollama · 自定义 CLI
可在同一场辩论中混搭多家供应商。

### 🎭 角色系统
20+ 内置角色（Karpathy、Andrew Ng、Elon Musk 等），可由问卷生成角色，或自定义编写。

### 📝 多阶段代码评审
6 个可配置的评审阶段：项目规则、实现、架构、安全/性能、测试覆盖率，以及红队对抗测试。

### 🧪 QA 集成模式
多个斗士在 **disjoint GPU 切片**上并行运行**目标项目自带的 `/qa` 技能**。裁判把发现合并为一份 canonical、去重、REPRODUCED-only 的 QA 报告。协作式，无胜者。

</td>
<td width="50%" valign="top">

### ⚖️ 三种裁判模式
**自动**启发式裁判、**AI 驱动**的裁判（任意模型），或**人类**裁判（带暂停/恢复流程）。

### 📈 证据优先的辩论
论点必须有依据。无依据的断言会被扣分。裁判按轮次跟踪证据质量。

### 💎 高管级报告
AI 综合的最终报告，包含核心结论、判决说明、辩论亮点，可导出为 **PDF** 或 **Markdown**。

### 💰 Token 与成本追踪
从供应商输出获取真实 token 数，按智能体细分成本。CLI 结果中常驻显示。

### 📺 实时监控
基于 tmux 的实时监控面板，可实时观察辩论与 QA 集成运行。QA 模式会为每位斗士自动启动一个 watcher 面板。

### 🪄 内置向导技能
首次运行时四个 Claude Code 向导技能自动安装到 `~/.claude/skills/`：`/colosseum`、`/colosseum_code_review`、`/colosseum_qa`、`/update_docs`。

</td>
</tr>
</table>

---

## 🎬 实际效果

### 第 1 步：在真实架构决策上让 Claude 与 Gemini 对决

```bash
colosseum debate \
  -t "10 人初创团队应该选微服务还是单体架构？" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -j claude:claude-opus-4-6
```

> 两个模型获得**完全相同的冻结上下文**，并在看到对方工作之前独立生成方案。裁判按轮次跟踪新颖度与证据质量 — 杜绝循环辩论。

### 第 2 步：用本地模型运行 — 无需 API 密钥

```bash
colosseum debate \
  -t "实时分析的最佳数据库是什么？" \
  -g ollama:llama3.3 ollama:qwen2.5 \
  --depth 2
```

> Colosseum 自动检测 GPU，通过 `llmfit` 检查模型适配性，并管理 Ollama 守护进程。完全离线，完全免费。

### 第 3 步：打开 Web 竞技场，享受可视化体验

```bash
colosseum serve
```

> 在 **http://127.0.0.1:8000/** 打开 — 选择模型、分配角色、设定裁判模式，并通过 SSE 实时流观看辩论展开。

### 第 4 步：对任何带 `/qa` 技能的项目运行 QA 集成

```bash
colosseum qa \
  -t "发布前回归扫描" \
  --target /path/to/your/target-project \
  -g claude:claude-opus-4-6 claude:claude-sonnet-4-6 \
  -j claude:claude-opus-4-6 \
  --gpus-per-gladiator 2
```

> 每位斗士作为带自己的 disjoint GPU 切片的真实 `claude --print` 子进程运行（无冲突）。非 Claude 斗士通过 mediated executor 运行。所有斗士完成后，裁判将报告合并为一份 canonical REPRODUCED-only QA 报告。在 tmux 内部，watcher 面板会自动启动 — 每位斗士一个。

---

## 🌟 AI Colosseum debate 的不同之处

| 其他工具 | AI Colosseum debate |
|---|---|
| 模型在响应前可以看到彼此的输出 | **冻结上下文** — 每个智能体都基于同一快照独立规划 |
| 辩论一直持续到有人放弃 | 带新颖度检查、收敛检测与预算上限的**有界轮次** |
| 判决依靠"感觉" | **证据优先评判** — 无依据的论断扣分；采纳的论点会被记录 |
| 无法复现结果 | **完整的产物链**：方案、轮次记录、裁判议程、采纳论点、判决 |
| 一种裁判，一种模式 | 三种裁判模式：启发式**自动**、任意模型 **AI 裁判**、**人类暂停/恢复** |
| QA 工具一次只用一个智能体顺序运行 | **QA 集成** — 多个斗士在 disjoint GPU 切片上并行运行，裁判把发现合并为一份报告 |

- **vs ChatGPT Arena / lmsys**：那些平台把单一提示发给两个模型并让人类投票。AI Colosseum debate 在你定义的话题、用你的上下文上运行*结构化的多轮辩论*，并产出可追溯、有证据支撑的判决。
- **内置角色**：将 Karpathy、Andrew Ng、安全研究员或你自定义的角色分配给每位斗士 — 这些声音会显著改变论证的框架。
- **代码评审模式**：六个可配置阶段（规范 → 实现 → 架构 → 安全 → 测试 → 红队）把辩论引擎变成多评审者代码审计。
- **QA 集成模式**：从 N 位斗士并行驱动任意项目自带的 `.claude/skills/qa` 技能，并合并发现的并集 — 协作式而非竞争式。Claude 斗士原生分派子智能体；Gemini/Codex 通过 mediated executor 运行。
- **你的基础设施**：云 API 与本地 Ollama 模型可互换使用。除非你主动选择云供应商，否则数据不会离开你的设备。

---

## 🤝 社区与支持

如果 AI Colosseum debate 对你有帮助，在 GitHub 上给一颗 ⭐ 是莫大的鼓励。

- **Bug 反馈与功能请求** → [GitHub Issues](https://github.com/Bluear7878/AI-Colosseum-Debate/issues)
- **欢迎贡献** — 新的供应商适配器、角色、裁判模式、QA 执行器与 UI 改进 PR 都受欢迎。开始之前请阅读 [`docs/architecture/overview.md`](docs/architecture/overview.md)。

---

## 🧭 文档地图

README 是面向产品的概述。规范的工程文档位于 `docs/`。

| 文档 | 说明 |
|---|---|
| [`docs/colosseum_spec.md`](docs/colosseum_spec.md) | 规范索引和入口 |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | 分层架构模型 |
| [`docs/architecture/design-philosophy.md`](docs/architecture/design-philosophy.md) | 核心设计原则与非目标 |
| [`docs/specs/runtime-protocol.md`](docs/specs/runtime-protocol.md) | 运行生命周期、流式协议、成本追踪 |
| [`docs/specs/agent-governance.md`](docs/specs/agent-governance.md) | 智能体、角色与供应商边界 |
| [`docs/specs/persona-authoring.md`](docs/specs/persona-authoring.md) | 角色文件格式与校验 |

---

## 🚀 快速开始

### 安装

```bash
# 以可编辑模式安装
python -m pip install -e .

# 包含开发工具
python -m pip install -e '.[dev]'
```

### 供应商配置

```bash
# 交互式配置 — 安装并认证所有受支持的 CLI 供应商
# 同时把四个内置向导技能自动安装到 ~/.claude/skills/
colosseum setup

# 仅配置特定供应商
colosseum setup claude codex

# 验证已安装的工具
colosseum check
```

### 向导技能自动安装

首次运行任何 `colosseum` 命令时，四个 Claude Code 向导技能会被静默安装到 `~/.claude/skills/`，可在任何位置调用：

| 技能 | 触发 | 用途 |
|---|---|---|
| `/colosseum` | "colosseum debate" | 辩论向导 |
| `/colosseum_code_review` | "colosseum code review" | 多阶段代码评审向导 |
| `/colosseum_qa` | "colosseum qa" / "QA ensemble" | QA 集成向导 |
| `/update_docs` | "update docs" | 项目文档刷新向导 |

需要刷新或强制覆盖时：

```bash
colosseum install-skills            # 仅安装缺失的
colosseum install-skills --force    # 即使用户已自定义也覆盖
```

### 启动 Web UI

```bash
colosseum serve
```

打开 **http://127.0.0.1:8000/** 即可使用。

### 在 CLI 中运行辩论

```bash
# 快速 mock 辩论（无需真实供应商）
colosseum debate --topic "我们应该重构供应商层吗？" --mock --depth 1

# 真实多模型辩论
colosseum debate \
  --topic "迁移到供应商无关层的最佳策略" \
  -g claude:claude-sonnet-4-6 codex:o3 ollama:llama3.3

# AI 裁判 + 实时监控
colosseum debate \
  --topic "单体 vs 微服务" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -j claude:claude-opus-4-6 --monitor

# 人类裁判
colosseum debate \
  --topic "数据库迁移策略" \
  -g claude:claude-sonnet-4-6 codex:o4-mini \
  -j human
```

### 运行代码评审

```bash
# 使用默认阶段（A-E）的多阶段代码评审
colosseum review \
  -t "OAuth 实现评审" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  --dir ./src

# 包含红队阶段与指定文件
colosseum review \
  -t "支付模块安全评审" \
  -g claude:claude-sonnet-4-6 codex:o3 \
  --phases A B C D E F \
  -f src/payment.py src/auth.py
```

### 运行 QA 集成

目标项目必须包含 `.claude/skills/qa/SKILL.md` — 那个技能定义了它希望被怎样 QA。每位斗士在自己的 GPU 切片上并行运行该技能。

```bash
# 2 个 Claude 斗士 + disjoint GPU 切片，裁判合并并集
colosseum qa \
  -t "发布前回归扫描" \
  --target /path/to/your/target-project \
  -g claude:claude-opus-4-6 claude:claude-sonnet-4-6 \
  -j claude:claude-opus-4-6 \
  --gpus-per-gladiator 2

# 跨供应商集成：Claude（原生子智能体）+ Gemini/Codex（mediated）
colosseum qa \
  -t "跨供应商 QA 通过" \
  --target /path/to/your/target-project \
  -g claude:claude-opus-4-6 gemini:gemini-2.5-pro codex:gpt-5.4 \
  -j claude:claude-opus-4-6 \
  --gpus-per-gladiator 1

# Brief 模式（仅代码分析，不执行 GPU）
colosseum qa -t "快速 smoke" --target /path/to/target -g claude:claude-haiku-4-5-20251001 --brief
```

在 tmux 内部，watcher 面板会自动启动 — 每位斗士一个，显示实时进度。最终合并的 canonical 报告位于 `.colosseum/qa/<run_id>/synthesized_report.md`。

---

## 🖥️ CLI 命令

```
colosseum setup [providers...]       安装并认证 CLI 供应商（同时安装向导技能）
colosseum install-skills [--force]   把内置向导技能安装到 ~/.claude/skills/
colosseum serve                      启动 Web UI 服务器
colosseum debate                     在终端中运行辩论
colosseum review                     运行多阶段代码评审
colosseum qa                         对目标项目运行 QA 集成
colosseum monitor [run_id]           为活跃辩论打开 tmux 实时监控
colosseum models                     列出所有供应商的可用模型
colosseum personas                   列出可用角色
colosseum history                    列出过往对决
colosseum show <run_id>              查看过往对决结果
colosseum delete <run_id|all>        删除对决运行
colosseum check                      验证 CLI 工具可用性
colosseum local-runtime status       检查托管的本地模型运行时状态
```

### Debate 选项

| 参数 | 说明 |
|---|---|
| `-t`, `--topic` | 辩论主题（必填） |
| `-g` | `provider:model` 格式的斗士（至少 2 个） |
| `-j`, `--judge` | 裁判模型（`provider:model` 或 `human`） |
| `-d`, `--depth` | 辩论深度 1-5（默认：3） |
| `--dir` | 用作上下文的项目目录 |
| `-f` | 用作上下文的具体文件 |
| `--mock` | 使用 mock 供应商（免费，用于测试） |
| `--monitor` | 启动 tmux 监控面板 |
| `--timeout` | 单阶段超时（秒） |

### Review 选项

| 参数 | 说明 |
|---|---|
| `-t`, `--topic` | 评审目标描述（必填） |
| `-g` | `provider:model` 格式的评审智能体（至少 2 个） |
| `--phases` | 要运行的评审阶段（默认：`A B C D E`） |
| `-j`, `--judge` | 裁判模型 |
| `-d`, `--depth` | 单阶段辩论深度（默认：2） |
| `--dir` | 要评审的项目目录 |
| `-f` | 要评审的具体文件 |
| `--diff` | 将最近的 git diff 纳入上下文 |
| `--lang` | 响应语言（`ko`、`en`、`ja` 等） |
| `--rules` | 项目规则文件路径 |
| `--timeout` | 单阶段超时（秒） |

### QA 选项

| 参数 | 说明 |
|---|---|
| `-t`, `--topic` | QA 运行的一行描述（必填） |
| `--target` | 目标项目路径（必须包含 `.claude/skills/qa/SKILL.md`）（必填） |
| `--qa-args` | 传递给目标 `/qa` 技能的参数 |
| `-g` | `provider:model` 格式的斗士。Claude → 真实 `claude --print` 子进程；非 Claude → mediated executor |
| `-j`, `--judge` | 用于合并斗士发现的裁判模型 |
| `--gpus` | 强制使用的 GPU 索引 csv（默认：自动检测） |
| `--gpus-per-gladiator` | 每位斗士的 GPU 切片大小（默认：均匀分割） |
| `--sequential` | 顺序运行斗士，而不是并行 disjoint 切片 |
| `--max-budget-usd` | 每位斗士的硬性消费上限（默认：$25） |
| `--max-gladiator-minutes` | 每位斗士的 soft 超时（默认：90） |
| `--stall-timeout-minutes` | stall 检测阈值（默认：10） |
| `--brief` | 仅代码分析，不执行 GPU |
| `--monitor` / `--no-monitor` | 自动启动 tmux watcher 面板（在 tmux 内默认开启） |
| `--spec` | 给 `/qa` 技能转发 `--spec NAME` |
| `--lang` | 响应语言 |
| `--allow-dirty-target` | 跳过 dirty worktree 警告 |
| `--no-stash-safety` | 跳过 git stash 安全网 |

---

## 🏗️ 一次运行的流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  📋 任务    │───▶│  🧊 冻结    │───▶│  📝 方案    │───▶│  ⭐ 方案    │
│  接收       │    │  上下文     │    │  生成       │    │  打分      │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                               │
        ┌──────────────────────────────────────────────────────┘
        ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  🎯 裁判    │───▶│  💬 辩论    │───▶│  ⚖️ 论点    │───▶│  🏆 判决    │
│  议程       │    │  轮次       │    │  采纳       │    │  与报告    │
└──────┬──────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                                      │
       └──────── 🔄 下一议题 ◀────────────────┘
```

编排器使用**有界辩论**而不是开放式聊天。如果方案已经充分分化、新颖度坍塌或预算压力过大，裁判可以提前停止。

---

## ⚖️ 辩论协议

每一轮都是**议程驱动**的，而不是开放式的：

| 步骤 | 说明 |
|:---:|---|
| **1** | 裁判选定一个具体议题 |
| **2** | 每个智能体基于自己的方案作答 |
| **3** | 智能体必须反驳或接受具体的同侪论点 |
| **4** | 裁判采纳证据最充分的最强论点 |
| **5** | 裁判进入下一议题或终结辩论 |

### 默认轮次类型

`critique` → `rebuttal` → `synthesis` → `final_comparison` → `targeted_revision`

每一轮记录裁判议程、所有智能体消息、采纳的论点以及未解决项。

### Depth 配置

| Depth | 名称 | 新颖度阈值 | 收敛 | 备注 |
|:---:|---|:---:|:---:|---|
| 1 | Quick | 5% | 40% | 急切早停 |
| 2 | Brief | 10% | 55% | |
| 3 | Standard | 18% | 75% | 默认 |
| 4 | Thorough | 25% | 85% | 至少 2 轮 |
| 5 | Deep Dive | 30% | 92% | 至少 2 轮，硬停止 |

### 裁判模式

| 模式 | 说明 |
|---|---|
| 🤖 **Automated** | 含预算、新颖度、收敛、证据检查的启发式裁判 |
| 🧠 **AI** | 基于供应商的裁判 — 任意可用模型都可作为裁判 |
| 👤 **Human** | 在规划后或轮次后暂停；等待显式的人类操作 |

### 判决形式

最终判决可以是：**单一胜出方案**、**合并方案**或**定向修订**请求。

---

## 📝 代码评审阶段

| 阶段 | 名称 | 关注点 |
|:---:|---|---|
| **A** | 项目规则 | 编码规范、命名、linter/formatter 规则 |
| **B** | 实现 | 功能正确性、边界情况、错误处理 |
| **C** | 架构 | 设计模式、模块划分、依赖关系、可扩展性 |
| **D** | 安全/性能 | 漏洞、内存泄漏、性能瓶颈、并发 |
| **E** | 测试覆盖 | 单元测试、集成测试、测试结构 |
| **F** | 红队 | 对抗输入、认证绕过、信息泄露、权限提升（可选） |

每个阶段在评审智能体之间运行一场迷你辩论。结果汇总为综合评审报告（可导出 Markdown）。

---

## 🧊 上下文包支持

| 来源类型 | 说明 |
|---|---|
| `inline_text` | 直接传入的原始文本 |
| `local_file` | 磁盘上的单个文件 |
| `local_directory` | 整个目录的快照 |
| `external_reference` | 作为元数据冻结的 URL |
| `inline_image` | Base64 编码的图像数据 |
| `local_image` | 磁盘上的图像文件 |

> 大型文本包会被裁剪到提示预算（最大 28,000 字符）。图像字节会保留在冻结包中，但不会注入文本提示。

---

## 🔌 供应商支持

| 供应商 | 类型 | 备注 |
|---|---|---|
| **Claude** | CLI 包装 | 需要 `claude` CLI。模型：opus-4-6, sonnet-4-6, haiku-4-5 |
| **Codex** | CLI 包装 | 需要 `codex` CLI。模型：gpt-5.4, o3, o4-mini |
| **Gemini** | CLI 包装 | 需要 `gemini` CLI。模型：2.5-pro, 3.1-pro, 3-flash |
| **Ollama** | 本地 | 需要 `ollama` 守护进程。自动发现已安装模型 |
| **Mock** | 内置 | 用于测试的确定性输出 |
| **Custom** | CLI 命令 | 自带模型/命令 |

自定义模型可以标记为免费或付费，可接入角色流程，并和内置智能体一样参与辩论流程。

### 本地运行时管理

Colosseum 管理一个本地 **Ollama** 运行时，提供：
- GPU 设备检测（NVIDIA、AMD、CPU）
- 通过 `llmfit` 进行 GPU 级模型适配检查
- 守护进程的自动启停管理
- 模型下载编排

```bash
colosseum local-runtime status
```

---

<details>
<summary><h2>🗂️ API 参考</h2></summary>

### 配置与发现

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查 |
| `GET` | `/setup/status` | 供应商安装/认证状态 |
| `GET` | `/models` | 列出可用模型 |
| `POST` | `/models/refresh` | 强制重新探测模型 |
| `GET` | `/cli-versions` | CLI 版本信息 |
| `POST` | `/setup/auth/{tool_name}` | 启动供应商登录 |
| `POST` | `/setup/install/{tool_name}` | 安装供应商工具 |

### 本地运行时

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/local-runtime/status` | Ollama/llmfit 状态（`?ensure_ready=false`） |
| `POST` | `/local-runtime/config` | 更新本地运行时设置 |
| `POST` | `/local-models/download` | 下载本地模型 |
| `GET` | `/local-models/fit-check` | llmfit 硬件适配检查（`?model=...`） |

### 运行管理

| 方法 | 端点 | 说明 |
|---|---|---|
| `POST` | `/runs` | 创建运行（阻塞式） |
| `POST` | `/runs/stream` | 创建运行（SSE 流式） |
| `GET` | `/runs` | 列出所有运行 |
| `GET` | `/runs/{run_id}` | 获取运行详情 |
| `POST` | `/runs/{run_id}/skip-round` | 跳过当前辩论轮次 |
| `POST` | `/runs/{run_id}/cancel` | 取消活跃辩论 |
| `GET` | `/runs/{run_id}/pdf` | 下载 PDF 报告 |
| `GET` | `/runs/{run_id}/markdown` | 下载 Markdown 报告 |
| `POST` | `/runs/{run_id}/judge-actions` | 提交人类裁判操作 |

### 角色管理

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/personas` | 列出所有角色 |
| `POST` | `/personas/generate` | 由问卷生成 |
| `GET` | `/personas/{id}` | 获取角色详情 |
| `POST` | `/personas` | 创建自定义角色 |
| `DELETE` | `/personas/{id}` | 删除角色 |

### 配额管理

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/provider-quotas` | 获取配额状态 |
| `PUT` | `/provider-quotas` | 更新配额 |

### UI 路由

| 路由 | 说明 |
|---|---|
| `GET /` | 竞技场 / 运行设置界面 |
| `GET /reports/{run_id}` | 对决报告界面 |

</details>

---

<details>
<summary><h2>📂 仓库结构</h2></summary>

```
src/colosseum/
├── main.py                 # FastAPI 应用工厂与服务入口
├── cli.py                  # 终端界面与实时辩论 UX
├── monitor.py              # 基于 tmux 的实时监控
├── bootstrap.py            # 依赖注入与应用初始化
│
├── api/                    # FastAPI 路由
│   ├── routes.py           # 路由组合
│   ├── routes_runs.py      # 运行 CRUD、流式、裁判操作
│   ├── routes_setup.py     # 配置、发现、本地运行时
│   ├── routes_personas.py  # 角色 CRUD 与生成
│   ├── routes_quotas.py    # 供应商配额管理
│   ├── sse.py              # SSE 负载序列化
│   ├── validation.py       # 共享请求校验
│   └── signals.py          # 生命周期信号注册
│
├── core/                   # 领域类型与配置
│   ├── models.py           # 类型化运行时 schema 与请求
│   └── config.py           # 枚举、默认值、depth 配置、评审阶段
│
├── providers/              # 供应商抽象层
│   ├── base.py             # 抽象供应商接口
│   ├── factory.py          # 供应商实例化与定价
│   ├── command.py          # 通用 CLI 命令供应商
│   ├── cli_wrapper.py      # CLI 信封解析器与适配器
│   ├── cli_adapters.py     # Claude、Codex、Gemini CLI 适配器
│   ├── mock.py             # 确定性 mock 供应商
│   └── presets.py          # 模型预设
│
├── services/               # 核心业务逻辑
│   ├── orchestrator.py     # 运行生命周期组合
│   ├── debate.py           # 轮次执行与提示组装
│   ├── judge.py            # 方案打分、议程、裁定、判决
│   ├── report_synthesizer.py # 最终报告生成
│   ├── review_orchestrator.py # 多阶段代码评审工作流
│   ├── review_prompts.py   # 评审阶段提示模板
│   ├── context_bundle.py   # 冻结上下文构造
│   ├── context_media.py    # 图像提取与摘要
│   ├── provider_runtime.py # 供应商执行与配额
│   ├── local_runtime.py    # 托管的 Ollama/llmfit 运行时
│   ├── repository.py       # 基于文件的运行持久化
│   ├── budget.py           # 预算账本追踪
│   ├── event_bus.py        # 事件发布
│   ├── normalizers.py      # 数据规范化工具
│   ├── prompt_contracts.py # 提示资产契约
│   ├── pdf_report.py       # PDF 导出
│   └── markdown_report.py  # Markdown 报告导出
│
├── personas/               # 角色系统
│   ├── registry.py         # 类型化角色元数据与解析
│   ├── loader.py           # 角色加载、缓存、解析
│   ├── generator.py        # 由问卷生成角色
│   ├── prompting.py        # 角色提示渲染
│   ├── builtin/            # 20 个内置角色
│   └── custom/             # 用户创建的角色
│
└── web/                    # 静态 Web UI 资源
    ├── index.html          # 竞技场设置 UI
    ├── report.html         # 对决报告显示
    ├── app.js              # 主 UI 逻辑
    ├── report.js           # 报告渲染
    └── styles.css          # 样式

docs/
├── colosseum_spec.md       # 规范索引
├── architecture/
│   ├── overview.md         # 分层架构模型
│   └── design-philosophy.md # 核心设计原则
└── specs/
    ├── runtime-protocol.md # 运行生命周期与流式协议
    ├── agent-governance.md # 智能体、角色、供应商边界
    └── persona-authoring.md # 角色文件格式与校验

examples/
└── demo_run.json           # mock 供应商烟测载荷

tests/                      # 测试套件
```

</details>

---

## 🧪 测试

```bash
# 运行完整测试套件
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q

# 快速语法校验
python -m compileall src tests
```

---

## ⚠️ 已知限制

- 除非在创建运行之前由上游抓取，否则 URL 来源仅以元数据形式存在
- 付费配额追踪是本地/手动的，与供应商不同步
- 内置的供应商 CLI 包装器比完整的 SDK 集成更轻
- 图像感知的辩论最好通过自定义命令供应商来支持
- 产物持久化是基于文件的，不依赖数据库
- 当无法获取真实 token 数时，会回退到 `len//4` 估算

---

<div align="center">

**⚔️ 让模型对决，让证据胜出。 ⚔️**

*为想要结构化答案、而不是聊天噪音的人而生。*

</div>
