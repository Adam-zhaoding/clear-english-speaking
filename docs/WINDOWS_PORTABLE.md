# Windows 免安装版

`clear-english-speaking.exe` 是用户的唯一启动入口。双击即可运行，不需要安装 Python、Node、ffmpeg，也不需要打开命令行。

首次运行时它会在 `%LOCALAPPDATA%\EnglishSpeakingPlayer` 下建立：

```text
%LOCALAPPDATA%\EnglishSpeakingPlayer\
├── engine\
│   ├── runtime\bbc-course-agent.exe   # 从 EXE 内部释放的课程引擎
│   ├── courses\                       # 你的课程 ZIP
│   └── settings.json                  # 不含 API Key 明文
└── workbuddy-workspace\               # 交给 WorkBuddy 的专用工作区
    ├── .workbuddy\skills\             # 复制过来的备课 Skill
    └── .clear-english-speaking\jobs\<id>\      # 每次备课任务与状态
```

## 首次打开

播放器自带一节合成演示课。点「开始今天的训练」再点播放，能听到轻柔的提示音就说明音频链路正常。演示课可以在课程库删除；一旦你有了真实课程，它就不再自动生成。

训练页**打开就是整集播放**：进度条可以拖到任意位置，用 ±10 秒微调，随时暂停。想练某几句时，点右上角「影子跟读（N 句）」切换到逐句训练，再点「回到整集播放」切回。

点「打开这一集的官方原文」会把课程包里的 PDF 写到 `%LOCALAPPDATA%\EnglishSpeakingPlayer\engine\transcripts`，并用你电脑默认的 PDF 阅读器打开。

## WorkBuddy 用户流程

1. 双击 `clear-english-speaking.exe`，进入「备课」页。
2. 选择 **WorkBuddy**，点「准备 WorkBuddy 任务」。应用会创建工作区、复制 Skill、写入任务，并把任务内容放进剪贴板。
3. 点「打开 WorkBuddy」；若它已在运行，请手动切到该窗口。
4. 在这个工作区**新建会话**（必须是新会话，WorkBuddy 才会发现完整的 Skill 目录）。
5. 按 `Ctrl+V` 粘贴任务，点发送。发送一次即可。
6. 回到 Clear English Speaking 等待。「备课」页会实时显示当前阶段：核对官方页面 → 下载 → 读取原文 → 语音对齐 → 生成课程包 → 导入。

**首次备课需要联网下载约 500 MB 的语音识别模型，只需一次。** 界面会明确提示这一步，不要误以为卡死。整体耗时通常 2–4 分钟（不含模型下载）。

### 为什么需要你手动发送

WorkBuddy 桌面版目前没有可供外部程序调用的公开接口，Clear English Speaking 无法替你新建会话或点发送。因此自动备课计划到点时，WorkBuddy 模式只会**创建待办**并提醒你，不会声称已在后台静默完成。Codex 与 API 模式则可以真正后台运行。

## 备课失败了怎么办

「备课」页的任务列表会显示中文原因和下一步，并提供「重试」和「删除任务」。常见情况：

| 现象 | 含义 | 处理 |
|---|---|---|
| 挑的句子和官方文稿对不上 | 助手改写了原句 | 点「重试」，或重新准备任务让助手严格照抄 |
| 没有可确认的官方文稿 | 该集只有 worksheet 或多个无名 PDF | 换一集 |
| 有句子没能在音频里定位到 | 音频与文稿版本不一致 | 点「重试」或换一集 |
| 语音识别模型下载失败 | 首次下载中断 | 确认联网后重试 |

失败**不会**覆盖或损坏你已有的课程。

## 备份与卸载

- **备份**：复制 `%LOCALAPPDATA%\EnglishSpeakingPlayer\engine\courses` 目录，并在「复盘」页导出学习记录（JSON + CSV）。不要复制系统凭据库。
- **卸载**：删除 `clear-english-speaking.exe` 和 `%LOCALAPPDATA%\EnglishSpeakingPlayer` 目录。若启用过自动备课，再删除 Windows 任务计划程序里的 `Clear English Speaking Background`。

## 发布构建（开发者）

```powershell
./scripts/build-desktop.ps1 -NoBundle
```

脚本会先用 PyInstaller 把课程引擎打包成单文件 EXE、复制到 `src-tauri/resources/`，再构建 Tauri Release。不带 `-NoBundle` 则额外生成当前用户级 NSIS 安装包。

> **路径限制**：GNU 工具链下 Windows 资源编译器不接受带空格的路径。脚本会优先使用 `D:\ClearEnglishSpeaking` 无空格 junction。仓库路径带空格时先执行：
> ```powershell
> cmd /c 'mklink /J "D:\ClearEnglishSpeaking" "<你的仓库路径>"'
> ```

构建产物：`src-tauri/target/release/clear-english-speaking.exe`（GNU 工具链下为 `src-tauri/target/x86_64-pc-windows-gnu/release/clear-english-speaking.exe`）。构建输入中不得包含任何 BBC 素材。
