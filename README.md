# 汽车每日事件站

最近 48 小时的中国汽车行业事件，一天一页，每条带摘要、一句点评、原文链接和标签。
纯静态、无 JS、无后端。**当前阶段：已上线，每天 07:10 自动更新。**

线上地址：<https://zxcvb-cmy.github.io/wangzhan/>（Actions 每天构建 → 提交 `docs/` → Pages 发布）

## 现在是什么状态

- 模板、样式、渲染、RSS、单日固定链接、**分类页**、**历史页**、GitHub Actions 定时任务：**已完成，线上在跑**
- 抓取：`d1ev`（第一电动网）、`sina`（新浪汽车）、`cada`（中国汽车流通协会）三个真源已接通；
  `mock` 保留用于离线开发和自检，默认关闭
- 摘要：LLM（DeepSeek `deepseek-chat`）已接通，没有 key 时自动降级为规则摘要（页面照常生成，不会崩）；
  摘要只改写源站导语，不许新增数字/机构/时间，素材只有标题时摘要会退化成标题复述 —— 这种卡片干脆不显示摘要行
- **已用 Actions 实跑验证**：三个源在机房 IP 上全部可达（第一电动 30 条 ~60s、新浪 15 条 ~13s、协会 30 条 ~18s），
  一轮全量摘要 2201 prompt + 2021 completion tokens

## 页面结构

| 路径 | 内容 |
| --- | --- |
| `/` | 今日：今日看点 + 分类入口 + 当日卡片 |
| `/<YYYY-MM-DD>/` | 单日固定链接，带前/后一天导航 |
| `/category/` | 全部分类，按事件数排序 |
| `/category/<slug>/` | 单个分类下的全部历史事件（跨天，按时间倒序，最多 80 条） |
| `/archive/` | 历史：按月分组，每天附 3 条头条 |
| `/feed.xml` | RSS，每天一条 |

分类来自标签：`rank.CATEGORY_RULES` 自动推断的 13 类（召回/政策/销量/财报/新车/价格/技术/电池/智驾/新能源/出海/基建/商用车）。
标签到 URL 的映射写在 `config.yaml` 的 `categories` 里（如 政策 → `policy`），
没声明的标签自动生成 `t-<hash6>` 链接，加新分类不用改代码。

## 跑起来

```bash
pip install -r requirements.txt
python run.py                     # 全流程 → docs/
python run.py --sources mock      # 只跑指定源
python run.py --check             # 只抓取统计，不渲染
python run.py --no-llm            # 强制用规则摘要
python run.py --date 2026-11-04   # 按指定日期的时间窗构建（补跑/测试）
```

产物在 `docs/`，双击 `docs/index.html` 就能看（链接全是相对路径，`file://` 直接可用）。

接 LLM：`export LLM_API_KEY=sk-...`（Windows：`$env:LLM_API_KEY="sk-..."`）。
全量一次的用量约 **2000 prompt + 1800 completion tokens**（15 条事件 + 今日看点），一天一次，
一个月不到 15 万 tokens。没有 key 时自动走规则摘要，页面照常生成。

摘要缓存在 `data/.llm-cache.json`，键是「事件 id + 素材指纹」：同一事件补到了正文导语会重新生成，
素材没变就直接复用。`--no-llm` 只是**禁止新调接口**，缓存里的 AI 摘要照用（所以会显示"缓存模式"）。

## 目录

```
config.yaml              全部可调项：时间窗、条数、权重、阈值、LLM
run.py                   入口：抓取 → 清洗 → 去重 → 排序聚类 → 摘要 → 渲染
sources/                 每个源一个适配器，统一返回 RawItem
  base.py                RawItem / SourceNotReady / 时区工具
  _net.py                共用请求层：UA、重试、导语抽取
  d1ev.py                第一电动网（主力源，8 个栏目并集）
  sina.py                新浪汽车·行业新闻
  cada.py                中国汽车流通协会（协会快讯 / 行业资讯 / 数据）
  mock.py                假数据（离线开发、自检用）
  cnautonews.py          中国汽车报（被雷池 WAF 挡，见下）
  autoinfo.py            中国汽车工业信息网（Vue SPA，要扒接口）
  dongchedi.py           懂车帝（匿名访问跳登录）
pipeline/
  fetch.py               调度所有源，单源失败不影响整体
  clean.py               去 HTML、规范化 URL、解析时间、基础字段校验
  dedupe.py              二元组 Dice 去重（URL 硬去重 + 文本软去重）
  rank.py                打分、48 小时时间窗、同事件聚类
  summarize.py           摘要 + 点评 + 今日看点，LLM 失败自动降级
  taxonomy.py            标签 → slug，汇总每个分类跨天的事件
  render.py              Jinja2 → docs/（含历史重渲、分类页、历史页、RSS）
templates/               base / index / day / archive / categories / category / card / feed.xml
static/style.css         单文件，14.4KB（预算 15KB，含深色主题与分类配色）
tools/                   自检与探测脚本（verify_site.py 查链接与 RSS，test_llm_stub.py 用假接口测 LLM，probe_source.py 判断站点能不能抓，diff_day.py 对比两天的数据看哪条新闻变了）
data/                    events-YYYY-MM-DD.json 永久留档（重跑可重建全站）
docs/                    Pages 根目录
.github/workflows/daily.yml   每天 07:10（北京时间）构建并提交
```

构建完想自检：

```bash
python tools/verify_site.py     # 卡片数、全站相对链接、分类页、RSS、历史统计
python tools/test_llm_stub.py   # 起本地假接口，验证 prompt/解析/缓存/渲染，不花钱
python tools/diff_day.py        # 最近两天的数据对比：新增/消失/标题改写
```

没有新内容时重跑构建，产物应该一个字节都不变（`[6/6]` 那行会打印「产物无变化：0 个文件重写」）。做到这一点靠三件事：落盘统一用 LF（`.gitattributes` + `render.py` 的 `_write_text`）、写之前逐字节比对、页脚与 RSS 的时间戳只用日期/固定时刻。

## 上线

仓库：<https://github.com/ZXCVB-CMY/wangzhan>，站点：<https://zxcvb-cmy.github.io/wangzhan/>。
以下都已经做完，写在这里是为了以后照着重做：

1. Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`、目录 `/docs`。
2. Settings → Secrets and variables → Actions → `LLM_API_KEY`（DeepSeek key）。
3. Actions → `daily` → Run workflow。构建约 1.5 分钟，最后一步把 `docs/` 和 `data/` 提交回仓库，
   Pages 自动重新发布。之后每天 07:10（北京时间）自动跑。

**运维备忘**

- 手动补跑：Actions → `daily` → Run workflow，可填 `sources`（如 `d1ev`）或把 `no_llm` 设为 `true`。
- 换 key：更新 `LLM_API_KEY` secret，再手动跑一次；缓存里已有的摘要不会重算。
- 想强制重写全部摘要：把 `data/.llm-cache.json` 清成 `{}` 再跑一次（一轮约 4k tokens）。
- 看构建日志：Actions → 对应 run → build → 各步骤；抓取失败会以 `[FAIL]` 行显示原因，不会中断整体流程。
- 看"今天比昨天变了什么"：`python tools/diff_day.py`（不带参数比较最近两天，也可 `diff_day.py 2026-11-05 2026-11-06`）。输出新增 / 消失 / 标题改写 / 内容有更新四类，比翻 HTML diff 直观。
- 没有新内容时重跑构建，`[6/6]` 会打印「产物无变化：0 个文件重写」，CI 的「提交产物」步骤直接跳过——不会为了时间戳制造空提交。

**国内访问**：GitHub Pages 在部分网络下不稳。要备案外的方案就用 Cloudflare Pages 连同一个仓库，
构建输出目录填 `docs`、不做构建（纯静态），速度明显更好，免费额度够用。

## 源站摸底（2026-11-06 实测）

用 `python tools/probe_source.py <url>` 逐站跑过一遍，结论直接决定了主源选谁：

| 站点 | 结果 |
| --- | --- |
| 第一电动 d1ev.com | **可用**。列表页服务端渲染，8 个栏目并集每次约 40 条 |
| 新浪汽车 auto.sina.com.cn/news/ | **可用**。一页 15 条带导语和时间，更新偏慢 |
| 中国汽车流通协会 cada.cn | **可用**。协会快讯/行业资讯/数据三栏，但列表常停在一周前 |
| 中国汽车报 cnautonews.com | 证书主机名不匹配 + 整站雷池（SafeLine）WAF，`httpx` 只能拿到 14KB 挑战页 |
| 中国汽车工业信息网 autoinfo.org.cn | 447 字节 Vue SPA 空壳，资讯走 `/api/*` 接口 |
| 懂车帝 dongchedi.com | `/news` 匿名访问直接跳 `login-required` |
| 盖世汽车 / 汽车头条 / 电车资源 / 网通社 | 一律 403 |
| 乘联会 cpcaauto.com | 首页 200，但 `news.php` 返回"请使用浏览器访问本站"（带 Referer 也一样） |
| 汽车之家 autohome.com.cn | 200 但 GBK，行业列表停在 2026-10-30，且已不是当日新闻 |
| 中汽协 caam.org.cn | 连接超时（数据中心网络下更明显） |

结论：能长期在 **GitHub Actions 的机房 IP** 上稳定抓的，就是上表前三个。
中国汽车报不建议硬耗（证书本身就不对，Actions 里只会更脆）；懂车帝/autoinfo 要上无头浏览器，
性价比低，先放着。

## 去重与聚类（容易被写错的地方）

两层，阈值含义不同：

- **硬去重** `pipeline/dedupe.py`：URL 相同直接并，另外文本二元组 Dice ≥ 0.9 视为同稿转载。
- **同事件聚类** `pipeline/rank.py`：三条通道，任一命中就并卡片
  ① 文本相似度 ≥ 0.72（同稿转载/轻微改写，不看品牌）；
  ② 共享品牌词 **且** 共享事件词（召回/销量/财报/进博会…）且相似度 ≥ 0.26；
  ③ 共享品牌词且相似度 ≥ 0.45。

为什么要品牌词表：模板化标题（"奔驰携多款新车亮相第九届进博会" vs "宝马集团携新世代成果亮相第九届进博会"）
在二元组上能到 0.45–0.55，纯阈值必然把两家不同车企并成一条。加品牌护栏之后，
"通用/凯迪拉克"这种同一事件跨源报道能合上，奔驰和宝马不会再串。

## 已知限制

- 品牌词表是手工维护的，遇到新品牌（尤其新势力子品牌）要补 `rank.BRANDS`；
  漏了不会错合，只是同一事件的两条稿子各占一张卡片。
- 标题被大幅改写、又恰好没提品牌名的同一事件（相似度 0.3 上下）合不到一起，目前接受这个漏。
- 没有正文抓取，摘要基于标题 + 源站导语。源站不给导语时，摘要会明确写"站点未给出导语"。
- 单日页是不可变的固定链接，但历史页面每次构建都会重渲（模板改了，老页面跟着变）。