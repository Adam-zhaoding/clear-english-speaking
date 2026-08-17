---
name: clear-english-speaking
description: 用 BBC Learning English 6 Minute English 的官方素材，生成一个可以双击打开的英语精听 + 影子跟读练习页面。当用户说「备今天的英语课」「做一节 BBC 英语课」「生成跟读材料」「练英语口语」「6 Minute English」，或要排查备课失败时使用。
---

# Clear English Speaking 备课

把 BBC 6 Minute English 的一期节目，变成用户电脑上一个可以双击打开的 HTML 练习页：
整集精听（变速、快进快退）+ 3–5 句影子跟读（单句循环、隐藏字幕、翻译、录音）。

## 分工

脚本做确定性的事，你做语言判断。**不要越界。**

| 谁 | 做什么 |
|---|---|
| 脚本 | 找期次、下载官方 MP3 与 Transcript PDF、抽正文、Whisper 词级对齐、逐字校验、渲染 HTML、起预览服务 |
| 你 | 只做一件事：挑 3–5 句重点句，写翻译、词义、A/B/C 卡点、听力提示 |

英文原句永远逐字照抄官方 Transcript。你不负责判断音频地址、文件哈希或时间戳。

## 流程

### 第零步：技能装在哪（每次开工前先确认，不要问用户）

技能固定放在**用户主目录下的 `clear-english-speaking`**。位置是固定的，
这样明天的定时任务、下个月的手动备课，找的都是同一份。

- 已经存在：直接用，**不要重新下载**。可以先 `git pull`，失败就用现有版本继续，不要因此中止。
- 不存在：`git clone https://github.com/Adam-zhaoding/clear-english-speaking` 到用户主目录；
  机器上没有 git 就下载仓库 ZIP，解压到同一位置。

首次装好后跑这两条，通过再往下走：

```bash
python -m pip install requests beautifulsoup4 pypdf faster-whisper
python scripts/make_lesson.py doctor
```

`doctor` 会查依赖，并把 Whisper 的 `base.en` 模型（约 145MB）预先拉下来。
**这一步只做一次**，别省：省掉它，这 145MB 就会挂在用户第一节课的等待里，
让人以为备课本来就要好几分钟。装完之后每节课只剩「下载素材 + 一次 40 秒对齐」。

想更彻底一点再跑一次 `python scripts/selftest.py`（离线、几秒钟）。

**课程输出目录不要问用户。** 脚本默认写到用户的「文档 / ClearEnglish」，
自动建好。只有用户主动要求换地方时，才给 `--output`。

### 第一步：准备

```bash
cd scripts
python make_lesson.py prepare --workspace lesson-work
```

指定某一期就加 `--url <BBC 期次页地址>`；不加就自动挑一期还没备过的。

这一步下载素材、跑一次本地 Whisper 对齐（一集 6 分钟约 40 秒），
产出 `lesson-work/draft-request.json`，同时把词级时间戳存进 `lesson-work/<期次>.alignment.json`。

**别删那个 alignment 文件，也别换 workspace。** build 直接读它，所以 build 只要零点几秒。
换了目录就等于让 Whisper 白跑第二遍，一节课平白多等 40 秒。

### 第二步：你来选句（这是你唯一的创作工作）

读 `lesson-work/draft-request.json`，里面有 `transcript_text`（官方 Transcript 正文）。
挑 **3–5 句**，写成 `lesson-work/draft.json`：

```json
{
  "summary_zh": "这一期聊家务分工：全球女性平均每天比男性多干几个小时的无偿家务，节目从罗地岛的例子讲到「女人的活」这个说法是怎么来的。",
  "sentences": [
    {
      "text": "逐字照抄官方 Transcript 的英文原句",
      "translation_zh": "自然的中文口语翻译，不要逐词硬翻",
      "glossary": [
        {"surface": "take out the bins", "meaning": "倒垃圾（英式说法）"}
      ],
      "diagnosis_tags": ["B"],
      "listening_focus": "taking out the 三个词连成一串，t 几乎不爆破"
    }
  ]
}
```

**summary_zh** 是页面「关于本课 · 主要内容」那一栏，2–3 句中文，说清这期到底讲了什么，
落到具体内容上（谁、在哪、什么事、给了什么数字），不要写「本期讨论了一个有趣的话题」这种空话。
不写也不会报错，但页面上会退回 BBC 自己的英文简介——那对用户没什么用。

**选句标准**，按优先级：

1. 含本期核心词汇或词块，能带出值得记的 glossary。
2. 有明显语流现象：连读、弱读、失爆、重音转移、词边界模糊。
3. 句长 8–30 词，读出来 4–12 秒。太短练不出节奏，太长跟不上。
4. 语义完整，脱离上下文也能理解。

**避开**：主持人的纯过渡语（"Hello and welcome…"）、听力测验题干、专有名词密度过高的句子。

**A/B/C 卡点**（可多选，至少给一个）。这是你的选句依据，**页面上不再显示这三个标签**，
写进 `draft.json` 只是留档：

- `A` 词不认识 —— 词汇或词块超出用户水平。
- `B` 认识但没听出来 —— 连读、弱读、失爆、重音转移、词边界模糊。
- `C` 听出来但没懂 —— 句法结构、指代、省略、逻辑关系。

**listening_focus** 写一句具体的提示，指出这句到底难在哪。
不要写「注意连读」这种废话，要写「`take a` 连读成 /teɪkə/，重音全在 breather 上」。

**glossary** 每句 0–4 个。`surface` 必须是原句里真实出现的片段（大小写不敏感），
否则页面上点不出来。`meaning` 给本句语境下的意思，不是词典义项罗列。

### 第三步：渲染

```bash
python make_lesson.py build --workspace lesson-work
```

课程写到「文档 / ClearEnglish」，目录不存在会自动建。不要向用户要路径，
也不要临时换地方——定时备课的重复防护靠的就是这个固定目录。

产出两个文件：

- `<期次>_<标题>.html` —— 双击就能练，官方音频和 Transcript PDF 都已内嵌，断网可用
- `<期次>_<标题>.lesson.json` —— 完整数据，方便以后重渲染

第一次点「开始录音」时浏览器会弹一次麦克风授权，**允许一次即可**，
这一次授权对整个页面所有句子有效，后面每一句都不会再打断。

「整集精听」右上角的「📄 官方 Transcript」按钮，打开的就是备课时下载的那份官方 PDF，
整份内嵌在 HTML 里，断网照样打得开。你不要另外复述或改写原文。

### 第四步：起预览服务，把课件喂进 WorkBuddy

```bash
python make_lesson.py serve
```

**每次备完课都要做这一步**，不是可选项。WorkBuddy 的内置浏览器打不开 `file://`，
只给一个本地路径，用户在 WorkBuddy 里点开就是一片空白。起了服务再把
`http://127.0.0.1:8931/<期次>_<标题>.html` 给他，播放、变速、循环、跟读、录音才都能用。

用户说「**服务打开，我要进行课件预览**」时，跑的也是这一条。

这个服务：

- 固定 `127.0.0.1:8931`，**只监听回环地址**。课件里内嵌着 BBC 音频，是用户的个人副本，
  不该出这台电脑——所以绝不要改成 `0.0.0.0`，也不要用 `python -m http.server` 顶替
  （它默认对整个局域网开放）。
- 端口被占多半是上一次的服务还开着，直接用就行，不必换端口。
- 它会一直占着这个终端。跑在后台，别用前台阻塞的方式跑完就干等。

在 WorkBuddy 之外，用户**双击 HTML 一样能练**，麦克风也是通的——Chrome 和 Edge 把
双击打开的本地文件视为安全上下文（已实测验证）。不要说 `file://` 不能录音。

## 定时自动备课

用户可以在 WorkBuddy 里建一个定时任务，让你每天自动备一节课。**定时任务触发时没有人在
旁边**，所以整条流程你要一个人走完，不要中途提问、不要等确认，更不要向用户要路径。

技能位置和课程目录都用默认的那一份（第零步已经规定死了），别另建、别换地方——
换目录就等于失忆，重复防护认不出哪些期次已经备过。

### 第一步：挑一期还没备过的

```bash
python make_lesson.py prepare --workspace lesson-work
```

BBC 每周才更新一期，用户却是每天练。所以脚本不是只盯最新一期：它按列表页从新往旧走，
拿默认课程目录里的成品比对期次号，挑出**第一期还没备过的**。这一步在下载音频、
跑 Whisper **之前**完成，不会白下 7MB。

只有整张列表都备过了才会打印 `NOTHING_NEW`。真出现了就**就此停下**：
不要重复备课，不要硬凑一节。按用户设定的方式回一句「列表上的期次都练完了」即可。

### 第二步：选句和渲染，跟手动流程完全一样

拿到期次后，照第二步、第三步做：读 `draft-request.json` 挑 3–5 句，写 `draft.json`，
然后 build。输出目录不用给，脚本自己落到同一个默认课程目录。

无人值守不降低选句标准。宁可只挑 3 句好的，也不要为了凑满 5 句放进一句平淡的过渡语。

### 第三步：起服务并报告

跑 `python make_lesson.py serve`（后台），把
`http://127.0.0.1:8931/<期次>_<标题>.html` 发给用户，附一句这期讲什么、你挑了哪几句。
本地路径也一并给上，他不在 WorkBuddy 里的时候双击就能用。

失败了就直接说失败在哪一步、失败码是什么。**不要自己反复重试**——
BBC 偶尔会拒连，下一次定时触发会自然重来。

## 失败处理

脚本会以失败码中止，按码给用户明确的修复动作，不要含糊带过：

| 码 | 含义 | 怎么办 |
|---|---|---|
| `no_eligible_episode` | 列表页找不到期次 | 让用户给一个具体的期次页地址，用 `--url` |
| `official_mp3_missing` | 页面上没有官方 MP3 | 换一期 |
| `official_transcript_missing` | 无 Transcript，或候选歧义 | 换一期，不要猜 |
| `sentence_not_in_official_transcript` | 你抄的句子不是原文 | 重新逐字照抄，再跑一次 build |
| `alignment_low_confidence` | 这句在音频里匹配不上 | 换一句；或用 `--model small.en` 重跑 prepare |
| `invalid_sentence_timing` | 句子时长越界 | 换一句 |
| 预览服务起不来 | 8931 被占 | 多半是上次的服务还开着，直接用；真要换就 `serve --port` |

**句子层失败不让整集报废。** 如果最后凑不齐 3 句，脚本会自动退回
`listen_only` 模式：整集音频照样能播、能变速、能快进快退。这是预期行为，如实告诉用户即可。

## 边界

- 只用 BBC Learning English 6 Minute English 官方期次页、官方音频、官方 Transcript PDF。
- MP3 地址必须从页面上发现，**不要**从 transcript 文件名推断。
- 不把 Whisper 的转写结果当成原文，它只负责给时间戳。
- 不绕过地区限制、访问控制或版权标识。
- 生成的 HTML 内嵌了 BBC 音频，属于用户的个人本地副本：不要上传、不要提交到仓库、不要分享。
- 不要修改用户的其他任务、定时任务或系统配置。
- 不要索要 API Key，整条链路不需要。
