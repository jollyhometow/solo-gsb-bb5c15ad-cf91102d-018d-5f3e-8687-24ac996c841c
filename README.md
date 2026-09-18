# Markdown Link Checker API

一个无外部依赖的 Markdown 文档链接检查服务：客户端提交一组带路径的 Markdown 文件，服务解析标题锚点（GitHub 风格 slug）、相对路径与显式 fragment，按规范化路径解析跨文件引用，把诊断结果存入 SQLite，并可按检查 ID 查询。

## 一键启动（Docker Compose）

```bash
docker compose up --build
```

服务监听 <http://localhost:8000>，交互式文档见 <http://localhost:8000/docs>。
SQLite 数据库持久化在名为 `mdlink-data` 的卷中（容器内路径 `/data/checks.db`，可用环境变量 `DB_PATH` 覆盖）。

## 本地开发

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # 运行测试
uvicorn app.main:app --reload
```

## API 用法

### 1. 提交文件集合并执行检查

```bash
curl -s -X POST http://localhost:8000/checks \
  -H 'Content-Type: application/json' \
  -d '{
    "files": [
      {"path": "README.md",      "content": "# Home\n\nSee [guide](docs/guide.md#install) and [api](docs/api.md#nope).\n"},
      {"path": "docs/guide.md",  "content": "# Guide\n\n## Install\n\n## Install\n"},
      {"path": "docs/broken.md", "content": "[esc](../../out.md)\n[me](broken.md)\n[404](nope.md)\n"}
    ]
  }'
```

响应（`201 Created`）：

```json
{
  "check_id": "9f2c…",
  "created_at": "2026-09-18T…",
  "file_count": 3,
  "diagnostic_count": 5,
  "summary": {"duplicate_anchor": 1, "missing_file": 2, "path_out_of_root": 1, "self_reference": 1},
  "diagnostics": [
    {
      "type": "missing_file",
      "source_file": "README.md",
      "line": 3,
      "link": "docs/api.md#nope",
      "target_file": "docs/api.md",
      "message": "Target file 'docs/api.md' not found in submitted files"
    }
  ]
}
```

### 2. 按检查 ID 查询结果

```bash
curl -s http://localhost:8000/checks/<check_id>
```

### 其他端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/checks` | 最近检查列表（新的在前） |
| `POST` | `/checks` | 提交文件集合并返回完整结果 |
| `GET` | `/checks/{check_id}` | 按 ID 查询已存结果（不存在返回 404） |

## 诊断类型

每条诊断都包含**来源文件**（`source_file`）、**行号**（`line`）和**可复现的链接**（`link`，即源文件中原始写法），以及规范化后的 `target_file`（可解析时）。

| `type` | 含义 |
| --- | --- |
| `missing_file` | 链接目标文件不在提交的文件集合中 |
| `missing_anchor` | 目标文件存在，但找不到对应 `#fragment` 锚点（含同文件锚点） |
| `duplicate_anchor` | 同一文件内多个标题产生相同锚点（以首次定义为准） |
| `path_out_of_root` | 相对路径经规范化后越出提交根目录（如 `../../x.md`） |
| `self_reference` | 文件通过显式路径链接到自身（纯 `#anchor` 页内跳转不算） |

## 解析规则

- **标题锚点**：ATX 标题（`#`–`######`），slug 规则与 GitHub 一致——小写、去标点、空格转连字符，保留 CJK 字符、数字与下划线。
- **路径规范化**：统一为 POSIX 路径，解析 `./`、`../` 与 `%20` 等百分号编码；以 `/` 开头的路径按根相对处理；越出根目录的路径报 `path_out_of_root`。
- **忽略项**：代码块（``` / ~~~）与行内代码中的标题和链接不参与检查；`http(s):`、`mailto:` 等外部 URL 不检查（无任何网络访问）；图片 `![alt](src)` 不检查。

## 已知限制

- 仅支持行内链接 `[text](dest)`，不支持引用式链接 `[text][ref]` 与 Setext 标题。
- 链接目标按精确路径匹配（区分大小写），不做 `.md` 后缀补全或目录索引解析。
- 目标是否存在的判断基于**提交的文件集合**：集合外的相对链接（如图片）会报 `missing_file`。

## 项目结构

```
app/
  main.py       # FastAPI 路由
  analyzer.py   # Markdown 解析与链接分析（纯函数，可独立测试）
  storage.py    # SQLite 存储层（stdlib sqlite3）
  models.py     # Pydantic 模型
tests/          # pytest：分析器单测 + API 集成测试
Dockerfile / docker-compose.yml
```
