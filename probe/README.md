# M0 探针 · 一次跑完三个未知

这个目录只做一件事：**在动手改造之前，把「这套方案到底能不能跑」测出来。**
不改任何现有代码，不碰 Hermes 的任务，跑完就能定案。

## 要测的三个未知

| # | 未知 | 由谁回答 |
|---|---|---|
| 1 | 浏览器能不能精确地做单句 AB 循环、变速、录音 | `runtime-probe.html` |
| 2 | WorkBuddy 沙箱能不能起 localhost 服务（决定录音是否可用） | `probe_workbuddy.py` |
| 3 | 本地 Whisper 能不能跑、跑多久（决定备课耗时） | `probe_workbuddy.py --audio` |

## 文件

| 文件 | 说明 |
|---|---|
| `runtime-probe.html` | **成品**。单文件、自包含、可离线，双击即用。内嵌了一段 8 秒测试音（每秒一个滴声，音高递增，便于人耳判断 seek 落点） |
| `runtime-probe.template.html` | 模板，改功能改这个 |
| `build_probe.py` | 生成测试音并注入模板，产出上面的成品 |
| `probe_workbuddy.py` | 沙箱侧探针，测端口、出网、依赖、Whisper |

改完模板后重新生成：

```bash
python build_probe.py
```

## 怎么跑

### 第一步：浏览器探针，同一个文件跑三遍

同一个 `runtime-probe.html`，在三个环境各跑一次，每次在页面底部「导出结果」里选对环境标签，然后下载 JSON。三份 JSON 一比，结论自明。

**环境 A · file:// 双击**

直接双击 `runtime-probe.html`。预期：播放、变速、循环全部正常，**录音会失败**——浏览器把 `file://` 视为不安全上下文，`navigator.mediaDevices` 直接不存在。

**环境 B · localhost**

```bash
python -m http.server 8765 --directory .
```

然后浏览器打开 `http://localhost:8765/runtime-probe.html`。localhost 属于安全上下文，这里录音应该可用。**这一步能不能成，决定录音功能的去留。**

**环境 C · WorkBuddy 产物预览**

把 `runtime-probe.html` 交给 WorkBuddy，让它作为 HTML 产物预览打开。测它的预览容器能不能播内嵌音频、能不能拿麦克风。

### 第二步：沙箱探针

在 WorkBuddy 里让它执行：

```bash
python probe_workbuddy.py
```

如果手头有一集真实的 BBC MP3，加上它一起测 Whisper 耗时：

```bash
python probe_workbuddy.py --audio 某一集.mp3
```

结果写到同目录 `probe-workbuddy.json`，终端也会打印人类可读的报告。

## 怎么读结果

页面顶部三个大数字是核心读数：

| 读数 | 含义 | 合格线 |
|---|---|---|
| **seek 误差** | 跳到句首准不准 | < 50ms |
| **timeupdate 间隔** | 浏览器多久汇报一次播放位置 | 越小越好，通常 250ms 左右 |
| **循环超出** | 实际停点比句尾晚多少 | < 60ms |

第 02 组里有三行 AB 循环，跑的是同一件事、三种实现：

- **timeupdate 方案**：参考实现 v9 用的就是这个。精度受限于浏览器汇报间隔。
- **rAF 方案**：逐帧判定，精度高得多，**但页面切到后台会被浏览器暂停**，音频会一路播过头。
- **双保险方案**：rAF 主判定 + timeupdate 兜底 + 硬超时。结果里的「判定者」字段会告诉你每一轮实际是谁先命中的。

选超出最小、且不会失灵的那个方案写进最终实现。

## 状态色

- 深绿 = 通过
- 琥珀 = 降级，能用但要知道代价
- 砖红 = 失败，是阻塞项

页面把「阻塞项」和「精度项」分开判定：播不了、变速失效、seek 不准属于阻塞；句尾停不准只是选哪种实现方案的问题。

## 不做什么

- 不改 `src-tauri`、`web`、`agent` 里的任何代码
- 不碰 Hermes 的 BBC learning 定时任务
- 不下载 BBC 素材（远程连通性测试只读 HTTP header）
- 不安装任何依赖，只报告缺什么
