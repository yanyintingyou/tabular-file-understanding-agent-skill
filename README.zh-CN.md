# Tabular File Understanding Agent Skill

简体中文 | [English](README.md)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-purple)
![Large CSV](https://img.shields.io/badge/Large%20CSV-ready-green)
![LLM Context](https://img.shields.io/badge/No%20raw%20table%20in%20LLM%20context-orange)
![IMF BOP/PIP](https://img.shields.io/badge/IMF%20BOP%2FPIP-tested-brightgreen)
![Stdlib](https://img.shields.io/badge/Core-Python%20stdlib-lightgrey)

**在让 LLM 分析表格之前，先理解大型、混乱、复杂表格文件的结构。**

一个可移植、仅依赖 Python 的 agent skill，用于帮助 LLM agent 理解大型、混乱或结构复杂的 CSV、TSV、Excel 和 PDF 表格文件，**避免把完整表格直接塞进上下文窗口**。

作者：[yanyintingyou](https://github.com/yanyintingyou)  
许可证：MIT

---

## 这是什么？

`tabular-file-understanding` 是一个兼容 Agent Skills 结构的工具型 skill，专门解决数据工作里最容易出错的第一步：先弄清楚一个表格文件到底是什么结构。

它不是让 LLM 直接阅读整个大表，而是让 agent 运行一个有边界的 Python profiler，生成紧凑、可审计的结构化产物：

- 文件级元数据；
- 检测到的表格、sheet 和候选数据区域；
- 字段名与标准化字段名；
- 推断字段类型；
- 代表性示例；
- 基于样本的缺失率和轻量统计；
- 结构性警告与歧义说明；
- 面向宏观 / SDMX 类数据的 domain-aware data locator。

最终输出的是一组 JSON 和 Markdown 文件，方便 LLM 后续安全地理解和使用。

---

## 为什么需要它？

大型表格并不适合作为 LLM 上下文。

一个几十 MB、几百 MB 甚至数 GB 的 CSV 或 Excel 文件，很容易超出上下文限制，也会让对话里充满原始行数据，导致模型忽略真正重要的结构信息。这个 skill 解决的是第一步问题：

> 在用户要求分析、清洗、可视化、建模、查询或写报告之前，先让 agent 理解表格结构。

这个 skill 有意**不做最终数据分析**。它负责生成结构理解层、记录不确定性，并告诉下游 agent 数据在哪里。

---

## 快速演示：合成 examples

仓库内置了 `examples/` 小型合成示例，用户不用下载真实大数据，也能快速测试 skill：

```text
examples/simple_fred.csv
examples/wide_time_imf_mock.csv
examples/wide_measure_epu_mock.xlsx
examples/report_style_worldbank_mock.xlsx
```

运行回归演示：

```bash
python tests/test_profile_examples.py
```

这些示例专门模拟容易让普通 LLM 表格读取流程出错的结构：FRED 简单时间序列、IMF BOP/PIP 宽时间列、EPU 宽指标列、World Bank 报告式 worksheet。

### 示例输出片段

对 `examples/wide_time_imf_mock.csv` 使用 `--domain-preset imf-bop` 后，会生成类似 locator：

```text
value_layout: wide_time_columns
column_roles.scale_column: SCALE.ID
column_roles.value_column: null
wide_time_value_columns: 1997, 1998, 1999, 2024-Q1, 2024-Q2, ...
required_preprocessing: reshape_wide_time_columns_to_long
recommended_key: COUNTRY.ID × INDICATOR.ID × COUNTERPART_COUNTRY.ID × FREQUENCY.ID × <time_period_column>
```

完整输出产物没有逐次提交到仓库，因为其中包含时间戳和本地路径。可以运行 `python tests/test_profile_examples.py` 或下方 quick-start 命令在本地重新生成。

---

## 默认能够理解哪些表格？

内置 profiler 是保守实现，但已经覆盖很多现实工作中常见、而且容易让 LLM 出错的表格形态。

| 表格形态 | 默认理解能力 | 典型例子 |
|---|---|---|
| 简单长表时间序列 | 识别时间列、数值列、行数、日期范围和观测键 | FRED 单序列 CSV：`observation_date, IRLTLT01JPM156N` |
| 通用长表 / 面板表 | 识别实体/id 列、日期/时间列、分类列、数值列和可能的行粒度 | `country × date × flow`、调查导出、交易流水 |
| 宏观 / SDMX 风格长表 | 推断 entity、indicator、counterpart、frequency、time、value、unit/scale/status 等角色 | SDMX CSV、IMF 风格国家-指标-时间导出 |
| IMF BOP/PIP 宽时间列 CSV | 识别描述列 + 大量期间列，如 `1948`、`1997-S1`、`2025-Q4`，并建议 reshape | 超大型 IMF BOP/PIP web CSV，包括多 GB 文件 |
| 宽指标列表 | 保留 `Year`/`Month` 或 `Date` 作为键，把国家、指数、序列列识别为并列 value columns | EPU `All_Country_Data.xlsx`：`Year, Month, GEPU_current, GEPU_ppp, Australia, Brazil, ...` |
| 报告式 Excel 工作簿 | 搜索真实 header 和 data-start，不机械假设第 1 行；标注 notes、merged cells、标题区 | World Bank 历史分类表，如 `OGHIST_*.xlsx` |
| lookup / classification 表 | 识别代码-标签、分类、成员关系表，不强行当成数值时间序列表 | World Bank `CLASS_*.xlsx`、国家代码表、分组成员表 |
| 矩阵 / 交叉表 | 标记行和列都承载维度的结构，分析前要求确认 | 透视表、cross-tab、密集数值矩阵 |
| PDF 表格文件 | 默认以元数据为主，不在无法抽取时虚假声称理解表格内容 | 需要额外 OCR/抽表流程的 PDF 报告 |

对于未知或混合布局，skill 会要求 agent 把 profiler 标签当成“假设”而不是“神谕”：检查有限样本、解释不确定性，并在模式可复用时补充 heuristic。

---

## 已验证的压力测试场景

这个仓库不仅能处理小 CSV，它真正面向的是那些会让普通 LLM 工作流失效的现实数据文件。

### IMF BOP / PIP：超大、宽表、强领域属性

大型 IMF Data Portal CSV 导出文件可能达到 **数 GB**，经常包含描述列和大量宽期间列：

```text
COUNTRY.ID | INDICATOR.ID | COUNTERPART_COUNTRY.ID | FREQUENCY.ID | SCALE.ID | 1948 | 1948-Q1 | ... | 2025-Q4
```

profiler 能识别：

```text
value_layout: wide_time_columns
recommended_key: COUNTRY.ID × INDICATOR.ID × COUNTERPART_COUNTRY.ID × FREQUENCY.ID × <time_period_column>
required_preprocessing: reshape_wide_time_columns_to_long
```

并避免常见误判，例如把 `PUBLICATION_DATE` 当成观测期，或把 `SCALE.ID` 当成数值列。

### World Bank 历史分类工作簿

World Bank workbook 常见标题行、说明行、阈值行、legend、merged cells，以及从 sheet 中间才开始的真实数据表。这个 skill 会搜索真实 header 和数据起点，因此类似：

```text
Code | Economy | FY89 | FY90 | FY91 | ...
```

可以被理解为宽历史分类表，而不是一个“第 1 行坏掉”的普通 Excel。

### EPU 全国家工作簿

EPU 工作簿常见结构：

```text
Year | Month | GEPU_current | GEPU_ppp | Australia | Brazil | Canada | China | US | ...
```

会被识别为：

```text
value_layout: wide_measure_columns
recommended_key: Year × Month
value_columns: GEPU_current, GEPU_ppp, Australia, Brazil, Canada, ...
```

如果后续需要 tidy panel，推荐 reshape 为：

```text
Year × Month × series_or_country → value
```

---

## 支持的文件类型

| 格式 | 支持程度 | 说明 |
|---|---:|---|
| CSV / TSV / 分隔符文本 | 强 | 使用 Python 标准库进行流式、样本边界内 profiling；支持可选 full scan |
| Excel `.xlsx` / `.xlsm` | 尽力但实用 | 读取 workbook XML；检测 sheet、used range、merged cells、候选 header、报告式布局；不执行公式或宏 |
| PDF | 元数据优先 | 默认只做保守文件级 profiling，除非后续用可选 Python 库增强 |
| 其他文件 | 有限 | 明确报告未知或不支持的格式 |

内置参考 profiler **只使用 Python 标准库**。agent 可以在需要时使用可选库做更深检查，但核心工作流不依赖它们。

### Excel 和 PDF 限制

标准库 Excel 读取器是保守实现：

- 仅支持 `.xlsx` / `.xlsm`；核心脚本不支持旧二进制 `.xls`。
- 永不执行公式、宏或外部链接。
- Excel 样式驱动的日期可能显示为原始序列号，因为核心脚本不实现完整 Excel 样式引擎。
- merged cells、hidden sheets、数据验证、图表、条件格式最多作为结构线索，不会按 Excel UI 完整重建。
- 复杂多级表头 workbook 仍可能需要人工确认，或在下游流程里使用 `openpyxl` 等可选解析器。

PDF 默认只做元数据优先检查。核心脚本只能统计粗粒度文件/page 信号，不能当作权威 PDF 表格抽取或 OCR。

---

## 会生成什么？

运行 profiler 后，会生成以下核心产物：

```text
<output_dir>/
├── table_manifest.json
├── table_profile.json
├── table_digest.md
├── ambiguities.md
├── data_locator_spec.json
└── data_locator_guide.md
```

可选产物包括：

```text
downstream_schema_hint.json
domain_indicator_catalog.json
domain_indicator_catalog.csv
domain_indicator_catalog.md
```

### 各文件作用

- `table_manifest.json`：文件清单、候选表格、能力级别、输出策略、警告信息。
- `table_profile.json`：有边界的字段画像、推断类型、样本值、缺失率、轻量统计。
- `table_digest.md`：紧凑的、适合 LLM 阅读的表格结构摘要。
- `ambiguities.md`：严肃分析前需要用户确认的问题。
- `data_locator_spec.json`：机器可读的数据定位说明，包括实体、指标、时间覆盖、观测键、数值列、单位、状态列和预处理需求。
- `data_locator_guide.md`：适合人和 LLM 阅读的数据定位指南，便于后续自动化提取。

---

## 快速开始

检查可选依赖情况：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --check-deps
```

分析一个文件：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile
```

然后读取：

```text
./tabular-profile/table_digest.md
./tabular-profile/ambiguities.md
./tabular-profile/data_locator_guide.md
```

如果想对 CSV 做更完整但更慢的扫描：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile \
  --full-scan
```

---

## 面向宏观 / SDMX 文件的数据定位器

对于 IMF BOP、SDMX CSV、国家-指标-时间这类宏观面板数据，profiler 会额外推断一层 data locator，用来回答“后续自动化处理时应该如何定位数据”。它会识别：

- 对象 / 实体列，例如国家、经济体；
- 指标 / 序列代码列；
- counterpart / partner 列，如果存在；
- 频率列与时间列；
- 观测值列或宽表中的 value-bearing columns；
- 单位、缩放、状态等属性列；
- 推荐的观测定位键。

IMF BOP 类文件示例：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./tabular-profile \
  --domain-preset imf-bop
```

可用 domain preset：

- `auto`，默认；
- `generic`；
- `macro-timeseries`；
- `sdmx`；
- `imf-bop`。

如果本地有 codelist，可以额外传入映射文件：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./tabular-profile \
  --domain-preset sdmx \
  --indicator-mapping indicators.csv \
  --entity-mapping areas.csv
```

映射文件建议使用 `code,label,description` 这类列名。没有映射文件时，profiler 只报告代码，并明确标注需要外部 codelist。

### IMF BOP/PIP 全量指标目录

如果目标是判断超大 IMF BOP/PIP 文件中有哪些变量/指标可用，可以增加 `--domain-full-scan`：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./bop-profile \
  --domain-preset imf-bop \
  --domain-full-scan
```

它会生成 `domain_indicator_catalog.json`、`.csv` 和 `.md`，包含指标覆盖度、时间范围、单位/缩放、会计方向样本，以及基于透明规则的跨境资本流动指标分类。

---

## 自适应输出控制

默认情况下，profiler 使用：

```bash
--output-policy auto
```

这个策略只控制生成的结果文件大小，**不会修改原始输入文件**。

| 输入规模 | 自动策略 | 行为 |
|---|---:|---|
| 小文件 / 普通宽度表格 | `full` | JSON 中完整保留 profiling 细节 |
| 中等文件或中等宽表 | `balanced` | 保留样本，但减少 examples / top values 数量 |
| 大文件或宽表 | `compact` | 省略行级样本，并减少部分字段级细节 |
| 超大文件或极宽表 | `very-compact` | 明显限制 examples 和详细字段画像数量 |

默认阈值：

- 小文件阈值：10 MB；
- 大文件阈值：100 MB；
- 超大文件阈值：1 GB；
- 中等宽表阈值：200 列；
- 宽表阈值：1,000 列；
- 极宽表阈值：5,000 列。

手动覆盖示例：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile \
  --output-policy compact
```

---

## 隐私选项

如果文件可能包含敏感信息，可以使用轻量样本脱敏：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --redact-samples
```

如果希望不写入行级样本和列级取值样本：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --no-samples
```

`--no-samples` 会从 `table_profile.json` 中移除 `samples.head_rows`、`samples.representative_rows`、`columns[].examples` 和 `columns[].top_values_sample`。它还会在 `data_locator_spec.json` / `data_locator_guide.md` 中抑制由样本行派生的 locator 索引、频率样本、key 检查和各时期取值摘要。字段名、推断类型、结构警告和 locator 字段角色元数据仍会保留，因为这些是理解 schema 所必需的。

也可以限制单元格保留长度：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --redact-samples \
  --max-cell-chars 80
```

---

## 可选下游提示

这个 skill 的边界是“结构理解”，但它可以为后续工作流生成一个小型提示文件：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile \
  --schema-preset generic
```

可用 preset：

- `generic`
- `rag`
- `sql`
- `none`，默认值

---

## 仓库结构

```text
.
├── agent instruction file
├── Claude-compatible instruction file
├── LICENSE
├── README.md
├── README.zh-CN.md
├── .gitignore
├── .cursor/
│   └── rules/
│       └── tabular-file-understanding.mdc
├── examples/
│   ├── README.md
│   ├── report_style_worldbank_mock.xlsx
│   ├── simple_fred.csv
│   ├── wide_measure_epu_mock.xlsx
│   └── wide_time_imf_mock.csv
├── tests/
│   ├── README.md
│   └── test_profile_examples.py
└── skills/
    └── tabular-file-understanding/
        ├── SKILL.md
        ├── scripts/
        │   └── profile_tabular_file.py
        └── references/
            ├── adaptive-output-policy.md
            ├── compatibility-notes.md
            ├── dependency-policy.md
            ├── domain-aware-data-locator.md
            ├── downstream-schema-hints.md
            ├── output-schema.md
            ├── privacy-and-security.md
            ├── table-structure-patterns.md
            └── validation-checklist.md
```

---

## Agent 兼容性

这个仓库设计为兼容多个 agent 生态：

- Agent Skills / Hermes / OpenClaw：使用 `skills/tabular-file-understanding/SKILL.md`。
- OpenAI Codex 兼容 agent：使用 `agent instruction file`。
- Claude Code 兼容 agent：使用 `Claude-compatible instruction file`。
- Cursor：使用 `IDE rule adapter directory/tabular-file-understanding.mdc`。

---

## 安装示例

克隆仓库：

```bash
git clone https://github.com/yanyintingyou/tabular-file-understanding-agent-skill.git
cd tabular-file-understanding-agent-skill
```

直接使用：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile
```

### 作为 Hermes skill 安装

这个仓库是一个 skill collection，真正的 skill 目录是：

```text
skills/tabular-file-understanding/
```

对于本地 Hermes，可以把该目录复制或软链接到 Hermes skills 目录，例如：

```bash
mkdir -p ~/.hermes/skills/data-science
ln -sfn "$PWD/skills/tabular-file-understanding" \
  ~/.hermes/skills/data-science/tabular-file-understanding
```

如果你的 Hermes 版本支持 skill tap / install 命令，可以把本仓库作为 tap 安装后选择 `tabular-file-understanding`；否则，上面的软链接/复制方式最透明。

对于其他兼容 Agent Skills 的系统，复制或引用：

```text
skills/tabular-file-understanding/
```

---

## 设计原则

1. **不要把大型原始表格直接放进 LLM 上下文。**
2. **只使用 Python。**
3. **默认只依赖 Python 标准库。**
4. **根据文件大小和表格宽度自适应控制 JSON 输出体积。**
5. **对于宏观 / SDMX 类数据，生成定位器，而不是把原始观测直接塞入上下文。**
6. **没有用户明确许可，不自动安装依赖。**
7. **不覆盖或修改原始文件。**
8. **区分结构事实和语义猜测。**
9. **把 profiler 标签当成假设，而不是神谕。**
10. **优先生成紧凑产物，而不是在聊天中输出大量内容。**

---

## 已知限制

- 内置脚本是保守的标准库实现。
- CSV 默认是样本边界内 profiling，不过 `--full-scan` 可改善行数和行宽检查。
- 对大文件或极宽表，JSON 结果可能会被自适应输出策略主动压缩。
- Excel 支持基于 `.xlsx` XML，不执行公式、宏、外部链接或 Excel 计算引擎。
- PDF 默认以元数据为主，除非通过可选 Python 库增强。
- 脱敏是轻量、基于模式的，不是完整 DLP 系统。
- data locator 是启发式推断；对于 SDMX / IMF 数据，官方 DSD 和 codelist 仍然是权威来源。
- 多行表头、同一 sheet 堆叠多张表、公式、嵌套数据包、扫描 PDF、领域专用口径等复杂结构，可能仍需要定制 extractor。
- 这个 skill 生成结构理解，不生成最终分析结论。

---

## 验证

运行基础 smoke test：

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --check-deps
```

创建一个小型 CSV 并 profiling：

```bash
printf 'country,date,flow\nUS,2024-01-01,1.2\nCN,2024-01-02,3.4\n' > /tmp/tfu-smoke.csv

python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input /tmp/tfu-smoke.csv \
  --out /tmp/tfu-smoke-profile
```

预期文件：

```text
/tmp/tfu-smoke-profile/table_manifest.json
/tmp/tfu-smoke-profile/table_profile.json
/tmp/tfu-smoke-profile/table_digest.md
/tmp/tfu-smoke-profile/ambiguities.md
/tmp/tfu-smoke-profile/data_locator_spec.json
/tmp/tfu-smoke-profile/data_locator_guide.md
```

完整检查清单见：

```text
skills/tabular-file-understanding/references/validation-checklist.md
```

---

## 许可证

MIT License。见 [LICENSE](LICENSE)。

---

## 作者

由 [yanyintingyou](https://github.com/yanyintingyou) 创建。
