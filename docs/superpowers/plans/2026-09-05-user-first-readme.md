# User-First README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the repository README with an audit-user-first guide that accurately describes the shipped single-entity Windows report-to-risk workflow and keeps private publishing material out of repository content.

**Architecture:** Keep `README.md` as a concise product entry point and route detailed operations to `docs/使用手册.md` and verification evidence to `docs/desktop-acceptance.md`. Extend the existing documentation contract test so stale sample-first wording, obsolete test counts, and private-content keywords cannot return unnoticed.

**Tech Stack:** Markdown, Python 3.13 `unittest`, Git, GitHub CLI

---

### Task 1: Lock the README contract

**Files:**
- Modify: `tests/test_desktop_documentation.py`
- Test: `tests/test_desktop_documentation.py`

- [x] **Step 1: Add a failing user-first README contract test**

Add `test_readme_is_user_first_current_and_free_of_private_publishing_content`. Read `README.md` as UTF-8 and assert that it contains all of these phrases:

```python
required = (
    "审计报告到风险图谱",
    "默认不加载示例",
    "单主体",
    "一份或多份报告",
    "上传日期",
    "报告日期",
    "为同一风险的两条证据",
    "不会复制原始报告",
    "249 项 Python 测试",
    "7 项 Playwright",
)
```

Also assert that these stale or private phrases are absent:

```python
forbidden = (
    "点「载入内置示例」",
    "24 项评分模型测试",
    "公众号",
    "微信公众号",
    "WeChat",
    ".private/",
)
```

- [x] **Step 2: Run the focused test and verify it fails on the old README**

Run:

```powershell
& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' -m unittest tests.test_desktop_documentation.DesktopDocumentationTests.test_readme_is_user_first_current_and_free_of_private_publishing_content -v
```

Expected: failure because the old README still recommends loading the built-in sample and reports 24 tests.

### Task 2: Rewrite the README

**Files:**
- Modify: `README.md`
- Test: `tests/test_desktop_documentation.py`

- [x] **Step 1: Replace the README with the approved user-first structure**

Write the sections in this exact order:

1. Product title, version and the value statement “从审计报告到风险图谱”.
2. “适合谁使用” and current one-entity scope.
3. “Windows 桌面端快速开始” with four numbered steps: configure the information directory and entity; add and review PDF/DOCX reports; select one or more reports and handle similar findings; preview and create a versioned workbook.
4. “报告目录如何工作” covering upload date as primary date, optional recognized report date, audit-project filtering, delete, clear and recoverable trash.
5. “同一风险的多份证据” with the recommended `为同一风险的两条证据` behavior and no averaging of model suggestions.
6. “数据与隐私边界” describing local extraction, credential storage, retained structured information, and excluded originals/paths/full text/page images/API keys.
7. “评分与人工责任” describing model suggestions, human confirmation, deterministic scoring and versioned output.
8. “当前支持与暂不支持” including Windows/PDF/DOCX support and excluding `.doc`, group multi-entity management, knowledge bases, RAG, vector retrieval and report chat.
9. “网页端与 Excel/Python 工作流” as a secondary path, with browser sample loading described only as explicit and non-production.
10. “评分模型”, “输出文件”, “开发与验证”, “项目结构”, and “许可证”.

Use only repository-relative links:

```markdown
[完整使用手册](docs/使用手册.md)
[桌面端验收记录](docs/desktop-acceptance.md)
[MIT License](LICENSE)
[第三方许可清单](THIRD_PARTY_NOTICES.md)
```

State the verified test status exactly as `249 项 Python 测试` and `7 项 Playwright 流程`. Keep clean-machine/no-Python and physical-disconnect checks marked as outstanding.

- [x] **Step 2: Run the complete documentation contract**

Run:

```powershell
& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' -m unittest tests.test_desktop_documentation -v
```

Expected: 3 tests pass.

### Task 3: Verify repository presentation and publish the update

**Files:**
- Modify: `docs/superpowers/plans/2026-09-05-user-first-readme.md`
- Modify: `README.md`
- Modify: `tests/test_desktop_documentation.py`

- [x] **Step 1: Validate Markdown, links and private-content exclusions**

Run:

```powershell
git diff --check
git grep -n -i -E "公众号|微信公众号|WeChat|\.private/" -- README.md
```

Expected: both commands produce no errors and the keyword scan has no matches.

Check each relative README link with `Test-Path`; all four targets must exist.

- [x] **Step 2: Commit the README and its contract test**

Run:

```powershell
git add -- README.md tests/test_desktop_documentation.py docs/superpowers/plans/2026-09-05-user-first-readme.md
git commit -m "docs: rewrite README for audit users"
```

- [x] **Step 3: Push the current branch and update PR #4**

Run:

```powershell
git push origin codex/remove-private-wechat-content
gh pr edit 4 --title "docs: publish user-first README and remove private drafts"
gh pr view 4 --json number,state,title,url,headRefOid,mergeable
```

Expected: PR #4 remains open and mergeable with the new commit at its head.
