# EZTrans 架构设计

最后核对时间：2026-06-30

## 1. 产品目标

EZTrans 的目标不是替代所有翻译网站，而是成为一个“无感”的本地翻译小工具：

- 呼出快：像 Pin 一样，随时弹出一个小窗口
- 输入快：焦点自动落在输入框，粘贴即可翻译
- 结果快：优先给出字词/短语解释，再给句子级译文
- 依赖少：默认离线可用，不要求用户登录任何账号
- 联网克制：只有在本地结果不足、用户显式开启、或者要拉取例句时才联网

## 2. 非目标

首个版本不建议做这些：

- 语音输入
- 浏览器插件
- 大而全的词典百科
- OCR 截图翻译
- 文档整页翻译

这些功能都很有价值，但会显著抬高体积、复杂度和维护成本，违背“轻量、无感”的核心原则。

## 3. 推荐总体方案

### 3.1 推荐技术栈

推荐采用两层结构：

1. GUI Shell：`Tauri 2 + 极简前端`
2. 翻译引擎：`Python sidecar + CTranslate2 + SQLite`

这是当前最平衡的做法。

原因：

- `Tauri` 很适合做小窗、置顶、托盘、更新器这类桌面工具能力。
- 本地翻译生态里，`Python + CTranslate2 + SentencePiece + Hugging Face` 的可选资源最成熟。
- 把翻译引擎放在 sidecar 里，可以把“桌面交互”和“模型推理”解耦，后续替换模型不会伤到 GUI。
- 用户最终拿到的是桌面程序，不需要单独安装 Python。

### 3.2 为什么不建议一开始就用纯 Electron

- 壳层更重，不符合“像 Pin 一样”的产品气质
- 真正的体积大头本来就在模型，不值得再给 GUI 多背一层重量

### 3.3 为什么不建议只依赖 Argos Translate

Argos Translate 很适合作为离线参考方案，但不建议把它当唯一核心：

- 它的包管理思路很好
- 但公开索引里的语种覆盖并不总是双向对称
- 对你要的北欧语支持来说，单靠它不够稳

一个具体例子是：我在 2026-06-30 核对公开 `argospm-index` 时，可以定位到 `en -> sv` 包记录，但没有找到对应的 `sv -> en` 包记录。对桌面程序来说，这种不对称会直接反映成“有的方向能离线翻，有的方向不能”。

因此更合理的路线是：

- 词典层：负责字词/短语
- 句子模型层：负责完整句子翻译
- 联网补充层：只在必要时启用

## 4. 核心模块设计

### 4.1 模块一：桌面 GUI

GUI 只做四件事：

- 接收输入
- 展示分层结果
- 控制置顶/固定/历史
- 调度本地或联网翻译

建议窗口特性：

- 小窗，默认约 `420 x 320`
- 支持 `always on top`
- 支持托盘驻留
- 支持全局快捷键呼出
- 支持窗口半透明或极简边框

建议交互流程：

1. 用户按快捷键呼出窗口
2. 输入框自动聚焦
3. 输入后 120 到 180ms 防抖
4. 先展示本地词典命中
5. 再展示句子翻译
6. 最后展示 1 到 2 条例句

### 4.2 模块二：本地翻译引擎

本地翻译引擎分成三层：

1. `Dictionary Layer`
2. `Sentence MT Layer`
3. `Example Layer`

#### Dictionary Layer

负责字词和短语优先展示。

推荐数据源：

- 中英：`CC-CEDICT`
- 英语与北欧语：`FreeDict`

存储方式：

- 统一转换成本地 `SQLite`
- 开启 `FTS5` 全文索引
- 结果按“完全匹配 > 前缀匹配 > 模糊匹配”排序

建议统一数据表：

```sql
CREATE TABLE dictionary_entries (
  id INTEGER PRIMARY KEY,
  src_lang TEXT NOT NULL,
  tgt_lang TEXT NOT NULL,
  headword TEXT NOT NULL,
  normalized_headword TEXT NOT NULL,
  reading TEXT,
  pos TEXT,
  gloss TEXT NOT NULL,
  source TEXT NOT NULL,
  weight REAL DEFAULT 1.0
);
```

#### Sentence MT Layer

负责短句和整句翻译。

推荐运行时：

- `CTranslate2`

推荐模型路线：

- `zh -> en`：`Helsinki-NLP/opus-mt-zh-en`
- `en -> zh`：`Helsinki-NLP/opus-mt-en-zh`
- `en <-> fi`
- `en <-> sv`
- `en <-> da`
- `en <-> nb`

其中挪威语建议首版明确标注为 `Bokmal (nb)`，避免“挪威语”概念过宽导致模型和 UI 表达不一致。

模型策略：

- 首次只内置 `zh <-> en`
- 北欧语模型按需下载
- 下载后转为 `CTranslate2 int8` 或 `int8_float16`
- 所有模型单独放在 `models/` 目录，不和主程序强耦合

这样做有两个好处：

- 首包更小
- 模型可以独立更新

#### Example Layer

负责提供 1 到 2 条例句。

展示规则：

- 默认优先取在线例句
- 离线时回退到本地例句库
- 每条例句都标注来源

离线例句库建议：

- 不要一开始就打包整套大语料
- 只保留高频、短句、工作场景友好的小型例句包
- 每个核心语种方向控制在可维护的小规模

本地数据结构建议：

```sql
CREATE TABLE example_sentences (
  id INTEGER PRIMARY KEY,
  src_lang TEXT NOT NULL,
  tgt_lang TEXT NOT NULL,
  source_text TEXT NOT NULL,
  target_text TEXT NOT NULL,
  tags TEXT,
  source_name TEXT NOT NULL,
  quality_score REAL DEFAULT 0.5
);
```

## 5. 语种策略

### 5.1 核心语种

首发必须稳的只有一组：

- 中文 <-> 英文

这是整个产品体验的主战场，质量、速度、例句、发音都优先堆在这里。

### 5.2 扩展语种

建议第二阶段补：

- 英文 <-> 芬兰语
- 英文 <-> 瑞典语
- 英文 <-> 丹麦语
- 英文 <-> 挪威语（首版建议先做 `nb`）

如果未来要支持：

- 中文 <-> 芬兰语
- 中文 <-> 瑞典语
- 中文 <-> 丹麦语
- 中文 <-> 挪威语

建议先走英文中转：

- `zh -> en -> target`
- `target -> en -> zh`

不要在首版直接塞过多低频双语模型，否则体积和维护都会失控。

## 6. 联网功能的平衡设计

联网能力应该是“增强层”，而不是“默认主路径”。

建议只保留三类联网能力：

1. 在线例句
2. 可选在线翻译 Provider
3. 模型和程序更新

### 6.1 在线翻译 Provider 设计

定义统一接口：

```ts
type TranslationProvider = {
  id: string;
  kind: "offline" | "online";
  translate(input: {
    text: string;
    srcLang: string;
    tgtLang: string;
  }): Promise<TranslationResult>;
};
```

首版 Provider 建议：

- `offline-dictionary`
- `offline-ct2`
- `online-deepl`（可选）
- `online-libretranslate`（可选）
- `online-openai-compatible`（可选）

调用策略建议：

- 词典命中时，不自动联网
- 短文本本地已有高置信结果时，不自动联网
- 只有在用户开启“联网增强”或本地失败时才调在线 Provider

这样产品仍然是“本地优先”，不会滑向臃肿。

## 7. 发音功能

发音是加分项，不应反过来拖累产品。

建议分两阶段：

### 7.1 首版

只做英文发音按钮，优先复用系统 TTS 或极轻量方案。

### 7.2 后续版本

如果首版体验不错，再把 `Piper` 语音包做成可选下载项。

原则：

- 发音资源不能默认塞进主安装包
- 发音质量不稳定时，宁可先隐藏

## 8. 更新机制设计

更新机制拆成两类：

1. 程序更新
2. 模型更新

### 8.1 程序更新

推荐：

- 应用发布到 GitHub Releases
- GUI 使用 `Tauri Updater`
- 程序启动后静默检查
- 有更新时提示“后台下载并重启安装”

程序更新元数据建议：

```json
{
  "channel": "stable",
  "currentVersion": "0.1.0",
  "latestVersion": "0.1.2",
  "notes": "Improve zh-en latency and fix updater rollback.",
  "publishedAt": "2026-06-30T12:00:00Z"
}
```

### 8.2 模型更新

模型更新不要跟程序发版绑死。

建议维护一个本地锁文件：

```json
{
  "models": [
    {
      "id": "zh-en",
      "repo": "Helsinki-NLP/opus-mt-zh-en",
      "revision": "main",
      "resolvedSha": "abc123",
      "format": "ctranslate2-int8",
      "installedAt": "2026-06-30T12:00:00Z",
      "checksum": "sha256:..."
    }
  ]
}
```

检查逻辑：

1. 启动后异步读取 `models.lock.json`
2. 每 24 小时最多检查一次远端修订信息
3. 如果远端版本变化，先下载到临时目录
4. 校验哈希
5. 原子替换旧模型
6. 失败则回滚

注意：

- 下载和替换必须后台进行
- 主窗口绝不能因为检查更新而卡住

## 9. 结果展示设计

结果必须分层，不能像很多翻译网页那样把所有东西糊成一块。

建议 UI 结构：

```text
[输入框]

[主译文]
English translation here

[字词 / 短语]
- 词条 1
- 词条 2
- 常见搭配 1

[例句]
1. ...
2. ...

[底栏]
来源 | 离线/在线 | 发音 | 复制
```

更具体的排序规则：

1. 主译文
2. 字词/短语候选
3. 例句
4. 来源与状态

如果输入只有单词或短语：

- 词典结果放在最上面
- 句子译文退到次级位置

如果输入是完整句子：

- 主译文放第一位
- 词语拆解放第二位

## 10. 性能目标

以下建议作为 MVP 的验收目标，而不是对外宣传承诺：

- 冷启动可见窗口：`< 1.2s`
- 热启动呼出：`< 250ms`
- 单词/短语本地查询：`< 80ms`
- 短句本地翻译：普通 CPU 下尽量压到 `300ms ~ 1200ms`
- 更新检查：异步，不阻塞首屏

## 11. 建议的项目目录

```text
EZTrans/
  docs/
    architecture.md
  app/
    ui/
      src/
      public/
    src-tauri/
      src/
      capabilities/
      tauri.conf.json
  engine/
    eztrans_engine/
      providers/
      dictionary/
      mt/
      examples/
      updater/
    pyproject.toml
  resources/
    dictionaries/
    examples/
    manifests/
  tools/
    build_models/
    import_dictionaries/
    make_example_pack/
```

## 12. MVP 路线

### Phase 1：先做最小可用版

只做：

- 小窗 GUI
- `zh <-> en` 离线翻译
- 中英词典查询
- 1 到 2 条本地例句
- 复制结果
- 托盘驻留

不要做：

- 发音
- 北欧语
- 在线 Provider
- 自动更新

### Phase 2：补全你最在意的体验

加入：

- 程序自动更新
- 模型自动更新
- 在线例句
- 发音按钮

### Phase 3：补北欧语

加入：

- `en <-> fi`
- `en <-> sv`
- `en <-> da`
- `en <-> nb`

### Phase 4：高级能力

可选：

- 剪贴板监听
- 输入历史
- 收藏短语
- 自定义术语表

## 13. 最关键的产品判断

这个项目成败不在于“你能接多少翻译 API”，而在于下面三件事：

1. 小窗呼出是否足够快
2. 单词和短语结果是否比网页更顺手
3. 句子本地翻译是否稳定到能覆盖日常 80% 场景

只要这三件事做对了，它就会比“打开网页、等加载、找输入框、登录账号”爽很多。

## 14. 推荐资源

以下资源适合作为实现参考：

- Argos Translate: https://github.com/argosopentech/argos-translate
- Argos package index: https://github.com/argosopentech/argospm-index
- CTranslate2 docs: https://opennmt.net/CTranslate2/translation.html
- OPUS-MT zh-en: https://huggingface.co/Helsinki-NLP/opus-mt-zh-en
- OPUS-MT en-zh: https://huggingface.co/Helsinki-NLP/opus-mt-en-zh
- CC-CEDICT: https://cc-cedict.org/wiki/
- FreeDict: https://freedict.org/
- Tatoeba downloads: https://tatoeba.org/en/downloads
- Piper TTS: https://github.com/rhasspy/piper
- Tauri updater: https://v2.tauri.app/plugin/updater/
- Tauri sidecar: https://v2.tauri.app/develop/sidecar/
- GitHub Releases API: https://docs.github.com/rest/releases/releases
- Hugging Face Hub API: https://huggingface.co/docs/huggingface_hub/package_reference/hf_api

## 15. 结论

如果只讲“最适合你当前目标”的路线，我的建议很明确：

- GUI 用 `Tauri`
- 本地翻译核心用 `CTranslate2`
- 词典层用 `CC-CEDICT + FreeDict + SQLite`
- 例句层做“小而精”的本地包，并保留在线补充
- 联网能力只作为增强层
- 更新机制分离成“程序更新”和“模型更新”

这样做出来的 EZTrans 不会变成一个“什么都想做”的庞然大物，而会更像一个真正可以长期放在桌面角落、随时救场的小工具。
