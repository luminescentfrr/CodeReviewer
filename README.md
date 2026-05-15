# CodeReview AI — 简洁版

多智能体代码审查工具。启动一条命令，打开浏览器即用，报告自动保存为本地 `.md` 文件。

## 结构

```
codereview-simple/
├── backend/
│   ├── main.py              # FastAPI 服务（含静态文件托管）
│   ├── agents/
│   │   ├── graph.py         # LangGraph 工作流（并行5智能体）
│   │   ├── reviewer.py      # 代码质量审查
│   │   ├── security.py      # 安全漏洞检测
│   │   ├── optimizer.py     # 性能瓶颈分析
│   │   ├── documenter.py    # 文档完整性
│   │   └── summarizer.py    # 元裁判（交叉验证 + 评分）
│   ├── tools/
│   │   ├── ast_parser.py    # Tree-sitter 代码解析
│   │   └── llm.py           # LLM 工厂（默认 DeepSeek，可选 OpenAI）
│   └── output/
│       └── report.py        # 生成并保存 Markdown 报告
├── frontend/
│   └── index.html           # 单页应用（纯 HTML/CSS/JS）
├── reports/                 # 审查报告自动保存在这里
├── requirements.txt
└── .env                     # 本地创建，勿提交仓库
```

## 启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key（推荐仅 DeepSeek）
# 在项目根目录创建 .env，至少包含：
#   DEEPSEEK_API_KEY=sk-...
#   DEEPSEEK_MODEL=deepseek-coder
# 若未配置 DeepSeek 且仅配置了有效的 OPENAI_API_KEY，则会回退到 OpenAI。
# 占位符如 OPENAI_API_KEY=none 会被忽略，不会当作有效密钥。

# 3. 启动
uvicorn backend.main:app --reload --port 8000

# 4. 打开浏览器
# http://localhost:8000
```

## 使用

1. 粘贴代码 或 点击「打开文件」载入本地文件
2. 选择语言
3. 点击「▶ 开始审查」
4. 实时看到 6 个智能体逐步完成分析
5. 查看「问题列表」和「详细报告」
6. 报告自动保存到 `reports/` 目录（Markdown 格式）

## 成本参考

单次审查（~100 行代码）：

| 配置 | 费用 | 耗时 |
|------|------|------|
| 全部 DeepSeek（`DEEPSEEK_API_KEY`） | 约低于 GPT-4o 全量 | ~35s |
| 全部 OpenAI GPT-4o（无 DeepSeek 时） | ~¥0.8 | ~35s |

配置 `DEEPSEEK_API_KEY` 后，**所有智能体**统一走 DeepSeek（与 OpenAI 兼容的 API）。

## 依赖说明

| 包 | 用途 |
|----|------|
| fastapi + uvicorn | Web 服务器 |
| langgraph | 多智能体工作流编排 |
| langchain-openai | GPT-4o / DeepSeek 调用 |
| tree-sitter | 代码 AST 解析（可选，无则 regex 降级）|
| pydantic | 数据验证 |
| python-dotenv | 读取 .env |
