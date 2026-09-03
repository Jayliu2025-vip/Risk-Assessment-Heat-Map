# 审计风险评估热力图谱（Risk Assessment Heat Map）

通用内审风险评估工具三件套：**Excel 真源工作簿 + Python 出图/出报脚本 + 零依赖网页端**。
同一套评分模型、同一份数据，三端数值完全一致。

> 当前版本：1.2

## Windows 桌面端：审计报告风险评估

桌面端仅支持 Windows（Windows 10/11 x64），安装后不需要另装 Python，也不要求用户使用命令行。它把过往审计报告转换成可复核的风险建议，再接入本项目现有的确定性评分、Excel、热力图和报告链路。

- 支持文字型 PDF、扫描 PDF 和 DOCX；不支持 `.doc`。处理顺序固定为：本地文本提取 → 自动 OCR → 可选视觉模型兜底 → 大模型判断。
- 模型通过 OpenAI 兼容接口配置，可连接符合接口约定的云端或本地服务；API Key 存入 Windows 凭据管理器，不写入 SQLite 或日志。使用云端模型时，提取文本以及启用视觉兜底的页面图片会发送给所配置的服务方。
- 模型结果先进入“待复核”，用户人工确认风险映射、每个维度的独立证据、涉及单位、金额、可能性、当前控制和整改状态后，现有 `tools/common.py` 才重新计算最终分数。
- 写入前必须查看变更预览；输出为 `audit_risk_register_yyyyMMdd_HHmm.xlsx` 及对应导出目录，不覆盖原工作簿。新文件经业务复核和组织审批后才能被指定为新的正式真源。
- 不提供知识库、RAG、向量检索或报告问答。历史审计发现只能证明报告形成时的事实，不能单独证明当前剩余风险。
- 仓库内验收样例均标注“虚构测试数据”和“非生产”，不得把样例结果用于真实审计结论。

桌面端采用四步流程：选择报告与模型 → 自动提取和分析 → 复核审计发现 → 预览并生成版本化工作簿。完整安装、配置、隐私和故障处理见[使用手册第 11 章](docs/使用手册.md#11-windows-桌面端审计报告风险评估)。

风险领域体系对齐权威框架：**《企业内部控制应用指引》18 项**（业务循环颗粒度）×
**《中央企业全面风险管理指引》**（战略/财务/运营/合规大类）= **4 大类 × 12 领域**
（详见 `docs/使用手册.md` 3.4 节）。

> 📖 **完整操作文档见 [`docs/使用手册.md`](docs/使用手册.md)**（评分锚点、逐表逐字段说明、常见任务、FAQ）。

## 评分模型

```
综合影响 I = max( Σ(wᵢ×维度ᵢ)/Σ(已评分维度的wᵢ), floor × 最高维度分 )
            八个影响维度：经济损失/合规法律/运营中断/声誉舆情/舞弊风险/战略影响/数据安全/健康安全（各1-5）
            wᵢ 按"所属领域"取分领域权重矩阵，未列领域用全领域默认行
            floor=一票否决系数（默认0.75）：任一维度打高分时致命后果不被稀释
固有风险   = 发生可能性 L × I                     ∈ [1, 25]
控制分     = MIN(关键控制点得分)（短板效应；未标记关键 → 退回全部控制点取 MIN；无控制点 → 不折减）
剩余风险   = 固有 × (1 − 折减系数[控制分])          折减映射默认 1→0% 2→15% 3→40% 4→55% 5→70%
控制挽回率 = (固有 − 剩余) / 固有                  控制环境化解风险的比例
等级五档   = 极高≥20 / 高≥12 / 中≥6 / 低≥3 / 极低<3（可调）
```

权重矩阵、阈值、折减映射、一票否决系数全部可在「参数配置」页或网页设置面板调整，即时重算。

## 目录结构

```
├── audit_risk_register.xlsx      ★ 数据真源：六张表（说明/参数配置/风险登记册/控制措施表/热力图/汇总与优先级）
├── risk_heatmap.html  (web/)     ★ 网页端：双击即用，离线零依赖
├── tools/
│   ├── common.py                 共享评分逻辑（Python 侧唯一实现）
│   ├── sample_data.py            内置示例数据（每期 24 条，覆盖 4 大类 12 领域，共 2 期）
│   ├── build_excel.py            生成/重建真源工作簿
│   ├── export_from_excel.py      xlsx → CSV 对 + config.json
│   └── generate_report.py        CSV → PNG 图集 + PDF 高管简报
├── data/export/{期间}/           risks.csv + controls.csv（按期间分目录）
├── data/export/config.json       权重矩阵/阈值/折减映射/一票否决系数
├── tests/test_scoring.py         24 项评分模型单元测试（unittest/pytest 兼容）
└── output/                       热力图 PNG ×2、领域分布、趋势、迁徙矩阵、敏感性、executive_report_*.pdf
```

## 快速开始

**A. 只想看结果**：双击 `web/risk_heatmap.html` → 点「载入内置示例」。
**B. 日常维护（推荐动线）**：
1. 在 `audit_risk_register.xlsx` 的黄色单元格维护风险、控制点打分（公式列勿动）；
2. `python tools/export_from_excel.py` 导出 CSV；
3. `python tools/generate_report.py` 出图出报；网页端导入同一份 CSV 交互查看。

**C. 环境要求**：Python 3.10+，`pip install matplotlib openpyxl`；
Excel 需 2019/365+（用到 MINIFS/MAXIFS）；网页端无任何依赖。
Node.js 仅用于发布一致性测试，不是运行依赖。

## 常用命令

```bash
python tools/build_excel.py           # 重建含示例数据的工作簿（覆盖现有文件）
python tools/export_from_excel.py     # xlsx → data/export/{期间}/*.csv + config.json
python tools/generate_report.py       # 默认最新期间；--period 2025H2 --compare 2026H1 可指定
python tools/generate_report.py --sensitivity   # 附加权重敏感性分析图
python tools/sample_data.py           # 重置示例数据（CSV + 网页内置数据）
python -m unittest discover -s tests  # 24 项评分模型测试 + 发布一致性测试
```

## 汇报输出物

| 输出 | 内容 |
|---|---|
| `*_inherent_heatmap.png` | 固有风险气泡热力图（背景按分值分档） |
| `*_residual_heatmap.png` | 剩余风险气泡热力图（控制折减后真实等级） |
| `*_domain_distribution.png` | 领域 × 剩余等级堆叠分布 |
| `trend_*.png` | 两期剩余风险哑铃图（红=恶化 绿=改善） |
| `executive_report_*.pdf` | 高管简报：指标卡 + TOP10 优先级表 + 全部图集 |
| 网页端「打印 / 存 PDF」 | 浏览器原生排版输出，隐藏编辑区 |

## 数据一致性约定

- **Excel 是唯一真源**；CSV 是交换格式；网页端 localStorage 仅作草稿。
- 三端共用同一公式体系；`generate_report.py` 运行末尾会打印 TOP8 交叉验证表。
- 新增评估期间：Excel 登记册「评估期间」列直接填新期间编号（下拉可编辑范围），
  导出后自动生成 `data/export/{新期间}/`；网页端趋势自动识别多期。

## 二次开发提示

- 调整领域清单：改 `tools/common.py` 的 `DOMAINS` + Excel C 列数据验证 + 网页 `DOMAINS` 常量。
- 增减影响维度：`common.py` 的 `DIMS`/`DIM_LABELS`、Excel 参数配置权重区与登记册公式、网页 `DIMS`。
- 换行业适配：替换 `tools/sample_data.py` 的风险清单即可，模型无需改动。

## 许可证

本项目采用 [MIT License](LICENSE)。
