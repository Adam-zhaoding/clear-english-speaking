---
name: clear-english
description: 用 BBC Learning English 6 Minute English 的官方素材，生成一个可以双击打开的英语精听 + 影子跟读练习页面。当用户说「备今天的英语课」「做一节 BBC 英语课」「生成跟读材料」「练英语口语」「6 Minute English」，或要排查备课失败时使用。
---

# Clear English 备课

把 BBC 6 Minute English 的一期节目，变成用户电脑上一个可以双击打开的 HTML 练习页：
整集精听（变速、快进快退）+ 3–5 句影子跟读（单句循环、隐藏字幕、翻译、录音）。

## 分工

脚本做确定性的事，你做语言判断。**不要越界。**

| 谁 | 做什么 |
|---|---|
| 脚本 | 找期次、下载官方 MP3 与 Transcript PDF、抽正文、Whisper 词级对齐、逐字校验、渲染 HTML |
| 你 | 只做一件事：挑 3–5 句重点句，写翻译、词义、A/B/C 卡点、听力提示 |

英文原句永远逐字照抄官方 Transcript。你不负责判断音频地址、文件哈希或时间戳。

## 流程

### 第一步：准备

```bash
cd scripts
python make_lesson.py prepare --workspace lesson-work
```

指定某一期就加 `--url <BBC 期次页地址>`；不加就自动取最新一期。

这一步会下载素材并跑本地 Whisper（一集 6 分钟的节目约需 1 分钟），
产出 `lesson-work/draft-request.json`。

首次运行如果报缺依赖：

```bash
pip install requests beautifulsoup4 pypdf faster-whisper
```

### 第二步：你来选句（这是你唯一的创作工作）

读 `lesson-work/draft-request.json`，里面有 `transcript_text`（官方 Transcript 正文）。
挑 **3–5 句**，写成 `lesson-work/draft.json`：

```json
{
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

**选句标准**，按优先级：

1. 含本期核心词汇或词块，能带出值得记的 glossary。
2. 有明显语流现象：连读、弱读、失爆、重音转移、词边界模糊。
3. 句长 8–30 词，读出来 4–12 秒。太短练不出节奏，太长跟不上。
4. 语义完整，脱离上下文也能理解。

**避开**：主持人的纯过渡语（"Hello and welcome…"）、听力测验题干、专有名词密度过高的句子。

**A/B/C 卡点**（可多选，至少给一个）：

- `A` 词不认识 —— 词汇或词块超出用户水平。
- `B` 认识但没听出来 —— 连读、弱读、失爆、重音转移、词边界模糊。
- `C` 听出来但没懂 —— 句法结构、指代、省略、逻辑关系。

**listening_focus** 写一句具体的提示，指出这句到底难在哪。
不要写「注意连读」这种废话，要写「`take a` 连读成 /teɪkə/，重音全在 breather 上」。

**glossary** 每句 0–4 个。`surface` 必须是原句里真实出现的片段（大小写不敏感），
否则页面上点不出来。`meaning` 给本句语境下的意思，不是词典义项罗列。

### 第三步：渲染

```bash
python make_lesson.py build --workspace lesson-work --output "课程输出目录"
```

产出两个文件：

- `<期次>_<标题>.html` —— 双击就能练，音频已内嵌，断网可用
- `<期次>_<标题>.lesson.json` —— 完整数据，方便以后重渲染

告诉用户 HTML 的完整路径，让他**直接双击打开**就行：播放、变速、循环、跟读、录音全都可用，
不需要起本地服务，不需要命令行。

第一次点「开始录音」时浏览器会弹一次麦克风授权，**允许一次即可**，
这一次授权对整个页面所有句子有效，后面每一句都不会再打断。

不要让用户去起 `http://localhost`，也不要说 `file://` 不能录音——Chrome 和 Edge 把双击打开的
本地文件视为安全上下文，麦克风是通的（已实测验证）。

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
