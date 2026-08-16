# Clear English Speaking · 给 WorkBuddy 用的英语精听技能

把 BBC 6 Minute English 的一期节目，变成你电脑上一个**双击就能打开**的英语练习页：
整集精听（变速、快进快退）+ 3–5 句影子跟读（单句循环、隐藏字幕、看翻译、录音回听）。

不需要 API Key，不需要装 Node，不需要开终端敲一堆命令。
你只要会复制粘贴一段话给 WorkBuddy。

---

## 最快的用法：把下面这段话发给 WorkBuddy

> 帮我装一个英语学习技能，然后给我备今天的课。
>
> 1. 把 `https://github.com/Adam-zhaoding/clear-english-speaking` 这个仓库下载到本地
> 2. 打开里面的 `SKILL.md`，完全按它写的流程做
> 3. 如果提示缺 Python 依赖，先执行 `pip install requests beautifulsoup4 pypdf faster-whisper`
> 4. 全部做完之后，把生成的 HTML 文件的完整路径告诉我
>
> 我不写代码，需要我配合的地方请一步一步告诉我该点哪里。

WorkBuddy 会自己完成：找最新一期 → 下载官方音频和 Transcript → 本地转写对齐 →
挑句子写翻译 → 生成练习页。全程大约 2–3 分钟，其中 1 分钟是本地语音对齐在跑。

做完你会拿到一个像 `260813_who-does-the-housework.html` 的文件，双击打开就能练。

---

## 想让它每天自动备课

用 WorkBuddy 自己的定时任务功能，建一个每天触发的任务，内容写这段：

> 用 clear-english-speaking 技能备一节新的 BBC 6 Minute English。
>
> 课程统一放在 `D:\课程\ClearEnglish`（这个目录固定不变）。
> 先跑 `prepare` 并带上 `--courses` 指向这个目录；如果输出里有 `NOTHING_NEW`，
> 说明最新一期已经备过了，回我一句「今天没有新一期」就结束，不要重复备课。
>
> 有新一期就走完整流程，做好之后把 HTML 的完整路径发给我，
> 附一句这期讲什么、你挑了哪几句。

把里面的目录换成你自己的路径。**这个目录一定要固定**——技能靠它记住哪些期次已经备过，
换目录就等于失忆，会把同一期反复备一遍。

BBC 每周更新一期，所以每天触发的任务里大部分天会直接回「今天没有新一期」。
这一步很快，只抓一下期次页就结束，不会下载音频、不会跑语音识别。

---

## 关于录音

页面里有「录音 → 回听」，可以把自己的跟读和原句对照。**双击打开就能用**，
不需要起本地服务，不需要开终端。

第一次点「录音」时，浏览器会问一次麦克风权限，**允许一次就够了**：
这次授权对整个页面所有句子有效，后面每一句都不会再打断你。

（Chrome 和 Edge 把双击打开的本地文件视为安全上下文，麦克风是通的。
这一点在 `probe/` 的探针里实测验证过，三个环境的结果都可以自己复现。）

---

## 目录里都有什么

| 文件 | 作用 |
|---|---|
| `SKILL.md` | WorkBuddy 读的说明书。它按这个流程干活 |
| `scripts/make_lesson.py` | 备课流水线：下载、抽正文、对齐、校验、渲染 |
| `assets/player-template.html` | 练习页模板 |

## 手动跑（给愿意开终端的人）

```bash
pip install requests beautifulsoup4 pypdf faster-whisper

cd scripts
python make_lesson.py prepare --workspace lesson-work
# 这一步之后，让 AI 读 lesson-work/draft-request.json，
# 挑 3-5 句写成 lesson-work/draft.json（格式见 SKILL.md）
python make_lesson.py build --workspace lesson-work --output ../courses
```

想指定某一期，给 prepare 加 `--url <BBC 期次页地址>`。
对齐不够准，把 `--model base.en` 换成 `--model small.en` 重跑。

---

## 设计上的几个决定

**英文原句逐字来自官方 Transcript PDF。**
本地 Whisper 只用来给时间戳，它的转写结果永远不会当成原文。草案里凡是对不上官方
Transcript 的句子会被直接丢掉——宁可少练两句，也不练一句错的。

**句子层失败不让整集报废。**
如果最后凑不齐 3 句，会自动退回「只可收听」模式：整集音频照样能播、能变速、能快进快退。

**不做自动发音评分。**
一次语音识别的误判不足以证明你发音错了。页面只提供录音和回听，让你自己对比。

**句尾判定用了双保险。**
单句循环要在句尾停住。只用 `timeupdate` 最坏会多播近 300 毫秒；只用
`requestAnimationFrame` 精度高但页面切到后台就完全停摆，音频会跑飞。
所以两个同时挂，谁先到谁生效，外加一道硬超时。这几个数字是实测出来的，
探针在 `probe/` 目录里，你可以在自己机器上复现。

---

## 版权

- 只使用 BBC Learning English 的官方页面、官方音频、官方 Transcript PDF。
- 不绕过地区限制、访问控制或版权标识。
- 生成的 HTML 里内嵌了 BBC 音频，**这是你的个人本地副本**：不要上传、不要提交到仓库、不要分享。
- 这个仓库本身不包含任何 BBC 素材。
