# Clear English

一个 Windows 优先、完全本地优先的英语听力与口语练习播放器。它把 BBC Learning English · 6 Minute English 的单期节目，在你自己的电脑上做成可离线练习的课程包，然后带你走完 **裸听 → 标记卡点（A/B/C）→ 对照 → 原速回测** 的闭环。

课程、录音和学习记录都留在你的电脑上：没有账号，没有云同步，不上传任何内容。

---

## 给普通用户：三步开始

1. 从 [Releases](../../releases) 下载 `clear-english.exe`，放到任意文件夹，双击打开。
   不需要安装 Node、Python、ffmpeg，也不需要打开命令行。
2. 首次打开时，播放器会自带一节**演示课**。点「开始今天的训练」，能听到声音就说明一切正常。
3. 想练真实的 BBC 课程，进「备课」页，选一种你已经装好的助手：

| 备课方式 | 需要什么 | 你要做什么 |
|---|---|---|
| **WorkBuddy**（推荐给小白） | 已安装 WorkBuddy | 点「准备 WorkBuddy 任务」→「打开 WorkBuddy」→ 新建会话 → 粘贴并发送一次 |
| **Codex** | 本机已登录 Codex CLI | 点一次「使用 Codex 立即备课」 |
| **我的 API** | 自己的 OpenAI 兼容服务 | 填服务地址、模型名、Key，点「立即备课」 |

发送任务后回到 Clear English 等待即可。剩下的下载、逐句校验、时间轴对齐、打包和导入都由播放器在本机自动完成，界面会显示当前进行到哪一步。

> **首次备课需要联网下载约 500 MB 的语音识别模型，只需一次。** 之后备课全程离线可用，已导入的课程断网也能练。

### Windows 系统要求

- Windows 10 / 11 64 位
- WebView2 Runtime（Windows 11 自带；Windows 10 若缺失，首次启动会提示安装）
- 对 `%LOCALAPPDATA%` 有写权限

---

## 每个页面在做什么

| 页面 | 作用 |
|---|---|
| **首页** | 当前课程进度、继续训练入口、我的课程列表。数字全部来自你真实的标记和回测，没有估算分数。 |
| **训练** | 打开就是**整集播放**：进度条拖到任意位置、±10 秒快进快退、暂停、0.6–1.25× 变速、整集循环。点「影子跟读」切到逐句训练：上一句/下一句、单句循环、回退 5 秒、A/B/C 卡点、译文与词汇、原速回测、可选跟读录音。任一模式都能一键打开这一集的官方原文 PDF。 |
| **课程库** | 本机全部课程：句数、已回测数、大小、导入时间、BBC 来源链接。可切换、可删除（删除需二次确认，同时清除该课记录）。 |
| **备课** | 三种备课来源、自动备课计划、备课任务列表（状态、失败原因、重试、删除）。 |
| **复盘** | 本课通过/待回测、A/B/C 卡点分布、按课程汇总、导出 JSON 与 CSV。 |

右上角的「导入 ZIP 课程包」在任何页面都可用，用来导入你在别处构建或备份过的课程包。

## 数据存在哪里

| 数据 | 位置 | 是否上传 |
|---|---|---|
| 课程 ZIP | `%LOCALAPPDATA%\ClearEnglish\engine\courses` | 否 |
| 引擎设置 | `%LOCALAPPDATA%\ClearEnglish\engine\settings.json`（不含 Key 明文） | 否 |
| API Key | Windows 凭据管理器，服务名 `clear-english` | 否 |
| 已导入课程与练习记录 | 应用内置 WebView 的本地存储 | 否 |
| 跟读录音 | 你手动保存到下载目录 | 否，且不做发音评分 |

**备份**：复制上面的 `courses` 目录，并在「复盘」页导出学习记录。不要复制或分享系统凭据库。

**卸载**：删除 `clear-english.exe`，再删除 `%LOCALAPPDATA%\ClearEnglish` 目录即可。若开过自动备课，请一并删除 Windows 任务计划程序中的 `Clear English Background`。

---

## 常见问题

**点了播放没有声音？**
先用自带的演示课测试。演示课有声音、真实课程没有，通常是课程包损坏 —— 到课程库删除后重新备课。

**备课失败了怎么办？**
「备课」页的任务列表会直接写出中文原因和下一步，并提供「重试」。失败不会覆盖你已有的课程。

**为什么 WorkBuddy 要我手动发送一次？**
WorkBuddy 桌面版目前没有可供外部程序调用的公开接口，Clear English 无法替你新建会话或点发送。所以它只负责把任务准备好并复制到剪贴板，发送这一步必须由你完成。这是产品的真实边界，不是待修复的缺陷。

**能识别我的发音、给我打分吗？**
不能，也不打算做。单次语音识别的误判不足以证明你发音有问题。跟读录音只用于你自己回听。

---

## 给开发者

```powershell
npm install
npm run lint
npm test
npm run build
```

网页版开发预览（可导入 ZIP 完整练习，但没有自动备课）：

```powershell
npm run dev
```

构建 Windows 便携版（会先用 PyInstaller 打包内嵌课程引擎，再构建 Tauri Release）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1 -NoBundle
```

> 使用 GNU 工具链时，Windows 的资源编译器不接受带空格的路径。脚本会优先使用 `D:\ClearEnglish` 这样的无空格 junction；如果你的仓库路径带空格，请先建一个：
> ```powershell
> cmd /c 'mklink /J "D:\ClearEnglish" "<你的仓库路径>"'
> ```

### 仓库结构

| 路径 | 职责 |
|---|---|
| `web/` | React + Vite 前端、播放器、课程包校验与本地存储 |
| `src-tauri/` | Tauri 桌面壳：备课来源、任务状态机、Windows 凭据库、计划任务、内嵌引擎 |
| `agent/bbc_course_agent/` | BBC 发现、下载、PDF 解析、音频时长、Whisper 对齐、原子写 ZIP |
| `skills/bbc-course-pack-builder/` | 复制给 WorkBuddy 的公开备课 Skill 与错误码说明 |
| `docs/` | 产品需求文档与便携版说明 |

### 课程包契约

```text
<episode_id>.zip
├── audio.mp3          # 或 audio.wav（演示课）
├── transcript.pdf
├── lesson.json        # schema_version 1，5–6 句，含时间轴与教学字段
└── manifest.json      # 每个文件的 SHA-256 与字节数
```

导入时前端会重新计算全部哈希，并拒绝缺文件、未知 Schema、句数不在 5–6、时间轴重叠越界、路径不安全或体积异常的包。详见 `skills/bbc-course-pack-builder/references/course-package-schema.md`。

---

## 隐私与 BBC 内容

- 本仓库只发布代码、Schema、Skill、文档和构建脚本，**不含任何 BBC 音频、Transcript 或完整课程包**。
- BBC 素材只因你本人主动备课而下载到你自己的电脑，请自行确认对 BBC 官方素材的访问与本地使用合规性。
- 本项目不规避地区限制、访问控制或版权标识，也绝不把 worksheet 当作 Transcript。
- 没有账号体系、没有分析 SDK、没有云端模型服务。

## License

MIT，仅适用于本仓库的代码和文档，不授予 BBC 内容的复制或再分发权利。
