import {
  ArrowClockwise, CheckCircle, ClipboardText, Clock, Copy, Robot, Sparkle, Trash, WarningCircle
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildDesktopJob, connectWorkBuddy, deleteDesktopJob, getDesktopStatus,
  isDesktop, listDesktopJobs, markJobImported, onBuildProgress, openWorkBuddy, readCourseFile,
  retryDesktopJob, saveApiConfiguration, saveDesktopSchedule, startApiCourse, startCodexJob,
  type DesktopJob, type DesktopStatus, type WorkBuddySetup
} from "../lib/desktop";
import { explainBuildError } from "../lib/errors";
import type { Course } from "../lib/types";

type Provider = "workbuddy" | "codex" | "api";
type Props = { onImportCourse: (file: File) => Promise<Course | undefined> };

const statusLabels: Record<string, string> = {
  awaiting_agent: "等待助手",
  draft_ready: "草案已就绪",
  building: "正在构建",
  imported: "已导入",
  failed: "未完成"
};

export function ProviderSetup({ onImportCourse }: Props) {
  const [provider, setProvider] = useState<Provider>("workbuddy");
  const [status, setStatus] = useState<DesktopStatus>();
  const [setup, setSetup] = useState<WorkBuddySetup>();
  const [jobs, setJobs] = useState<DesktopJob[]>([]);
  const [message, setMessage] = useState("");
  const [progress, setProgress] = useState("");
  const [busy, setBusy] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [scheduleDays, setScheduleDays] = useState<number[]>([1, 3, 6]);
  const [scheduleTime, setScheduleTime] = useState("17:30");
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const building = useRef(false);

  const refresh = useCallback(async () => {
    if (!isDesktop()) return;
    try {
      setStatus(await getDesktopStatus());
      setJobs(await listDesktopJobs());
    } catch {
      // A transient IPC failure must not break the page; the next tick retries.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => onBuildProgress((event) => setProgress(event.message)), []);

  // Only one build may run at a time, and a job that already failed is not
  // retried automatically — the user decides, via the retry button.
  useEffect(() => {
    const next = jobs.find((job) => job.status === "draft_ready");
    if (!next || building.current) return;
    building.current = true;
    setBusy(true);
    void (async () => {
      try {
        setMessage("");
        setProgress("正在校验草案并准备构建……");
        const path = await buildDesktopJob(next.id);
        const course = await onImportCourse(await readCourseFile(path));
        if (course) {
          await markJobImported(next.id);
          setMessage(`《${course.title}》已通过校验并导入播放器。`);
        } else {
          setMessage("课程包生成了，但导入播放器时被拒绝。请在课程库重新导入该 ZIP。");
        }
      } catch (error) {
        setMessage(explainBuildError(error));
      } finally {
        setProgress("");
        setBusy(false);
        building.current = false;
        await refresh();
      }
    })();
  }, [jobs, onImportCourse, refresh]);

  const guard = async (run: () => Promise<void>) => {
    try {
      await run();
    } catch (error) {
      setMessage(explainBuildError(error));
    }
  };

  const connect = () => guard(async () => {
    setSetup(await connectWorkBuddy());
    setMessage("第 1 步已完成：工作区、备课 Skill 和任务内容都准备好了。接下来需要你在 WorkBuddy 新建会话并发送一次任务。");
    await refresh();
  });

  const openBuddy = () => guard(async () => {
    await openWorkBuddy();
    setMessage("已请求打开 WorkBuddy。如果它已经在运行，请手动切到 WorkBuddy 窗口再新建会话。");
  });

  const copyPrompt = async () => {
    if (!setup) return;
    try {
      await navigator.clipboard.writeText(setup.prompt);
      setMessage("任务内容已复制。现在切到 WorkBuddy，新建会话后按 Ctrl+V，再点发送。");
    } catch {
      setMessage("无法访问剪贴板，请展开下方任务内容后手动复制。");
    }
  };

  const runCodex = () => guard(async () => {
    if (!localStorage.getItem("clear-english-speaking-codex-consent")) {
      if (!window.confirm("将使用这台电脑当前已登录 Codex 账号的配额来准备一节课。首次确认后，后续备课将静默执行。继续吗？")) return;
      localStorage.setItem("clear-english-speaking-codex-consent", "yes");
    }
    const id = await startCodexJob();
    setMessage(`Codex 正在准备教学草案（任务 ${id.slice(0, 8)}）。完成后会自动构建并导入。`);
    await refresh();
  });

  const saveApi = () => guard(async () => {
    await saveApiConfiguration(baseUrl, model, apiKey);
    setApiKey("");
    setMessage("API 配置已保存到本机系统凭据库。Key 不会显示，也不会写入课程包。");
  });

  const runApi = () => guard(async () => {
    setBusy(true);
    try {
      setProgress("正在从 BBC 官方来源构建课程，可能需要几分钟……");
      const path = await startApiCourse();
      const course = await onImportCourse(await readCourseFile(path));
      setMessage(course ? `《${course.title}》已通过校验并导入播放器。` : "课程包生成了，但导入被拒绝。");
    } finally {
      setBusy(false);
      setProgress("");
    }
  });

  const saveSchedule = () => guard(async () => {
    setMessage(await saveDesktopSchedule(scheduleDays, scheduleTime, "Asia/Shanghai", provider, scheduleEnabled));
  });

  const retry = (job: DesktopJob) => guard(async () => {
    await retryDesktopJob(job.id);
    setMessage("已重新排队，正在重新构建。");
    await refresh();
  });

  const remove = (job: DesktopJob) => guard(async () => {
    await deleteDesktopJob(job.id);
    if (setup?.jobId === job.id) setSetup(undefined);
    await refresh();
  });

  const toggleScheduleDay = (day: number) => setScheduleDays((current) => current.includes(day)
    ? current.filter((item) => item !== day) : [...current, day].sort());

  if (!isDesktop()) {
    return <section className="card provider-setup">
      <div className="section-title"><h3>自动备课需要桌面版</h3><Robot size={21} /></div>
      <p className="muted">
        你现在打开的是网页版。网页版可以完整练习：用右上角“导入 ZIP 课程包”把课程导入即可。
        自动从 BBC 官方来源备课需要下载 Windows 桌面版 Clear English Speaking。
      </p>
    </section>;
  }

  return (
    <section className="card provider-setup">
      <div className="section-title"><h3>选择备课方式</h3><Robot size={21} /></div>
      <p className="muted">不需要命令行。优先使用你已经登录的助手；只有 API 模式才需要填写 Key。</p>
      <div className="provider-tabs">
        <button className={provider === "workbuddy" ? "provider active" : "provider"} onClick={() => setProvider("workbuddy")}>WorkBuddy</button>
        <button className={provider === "codex" ? "provider active" : "provider"} onClick={() => setProvider("codex")}>Codex</button>
        <button className={provider === "api" ? "provider active" : "provider"} onClick={() => setProvider("api")}>我的 API</button>
      </div>

      {provider === "workbuddy" && <div className="provider-panel">
        <b>{status?.workbuddyAvailable ? "已检测到 WorkBuddy" : "未检测到 WorkBuddy"}</b>
        <p>{status?.workbuddyAvailable
          ? "Clear English Speaking 会准备好课程任务；WorkBuddy 目前不能被外部程序自动新建会话或发送消息，所以需要你手动发送一次。"
          : "请先安装 WorkBuddy 并至少启动一次，然后回到这里。"}</p>
        {!setup && <button className="primary" disabled={!status?.workbuddyAvailable || busy} onClick={() => void connect()}>
          <Sparkle size={18} />准备 WorkBuddy 任务
        </button>}
        {setup && <div className="guide handoff-guide">
          <CheckCircle size={18} /><b>第 1 步已完成：任务已准备。</b>
          <ol>
            <li>点击“打开 WorkBuddy”；若它已打开，请切换到该窗口。</li>
            <li>在 WorkBuddy 点击“新建会话”。</li>
            <li>点击“复制任务”，在新会话按 Ctrl+V，然后发送。</li>
            <li>回到这里等待，Clear English Speaking 会自动完成校验、构建和导入。</li>
          </ol>
          <div className="handoff-actions">
            <button className="secondary" onClick={() => void openBuddy()}>打开 WorkBuddy</button>
            <button className="secondary" onClick={() => void copyPrompt()}><Copy size={17} />复制任务</button>
            <button className="text-button" onClick={() => setSetup(undefined)}>重新准备</button>
          </div>
          <details><summary>查看任务内容（仅在无法复制时使用）</summary><pre>{setup.prompt}</pre></details>
        </div>}
      </div>}

      {provider === "codex" && <div className="provider-panel">
        <b>{status?.codexAvailable ? "已检测到本机 Codex" : "未检测到 Codex"}</b>
        <p>使用当前 Codex 登录账号生成受限教学草案；本机构建器仍负责 BBC 下载、逐字校验与课程 ZIP。</p>
        <button className="primary" disabled={!status?.codexAvailable || busy} onClick={() => void runCodex()}>
          <Robot size={18} />使用 Codex 立即备课
        </button>
      </div>}

      {provider === "api" && <div className="provider-panel api-fields">
        <label>服务地址<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label>
        <label>模型名称<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="provider-model-name" /></label>
        <label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="只保存到系统凭据库" /></label>
        <button className="primary" onClick={() => void saveApi()}>保存 API 配置</button>
        <button className="secondary" disabled={busy} onClick={() => void runApi()}>使用我的 API 立即备课</button>
      </div>}

      <div className="provider-panel schedule-panel">
        <div className="section-title"><h3>自动备课</h3><Clock size={19} /></div>
        <p>WorkBuddy 到点仅创建待办；Codex 和 API 可在后台运行。电脑休眠时不执行，恢复后只补跑最近一次。</p>
        <div className="schedule-controls">
          <input aria-label="自动备课时间" type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} />
          <label className="schedule-switch">
            <input type="checkbox" checked={scheduleEnabled} onChange={(event) => setScheduleEnabled(event.target.checked)} />启用
          </label>
          <button className="secondary" onClick={() => void saveSchedule()}>保存计划</button>
        </div>
        <div className="day-picker">
          {["一", "二", "三", "四", "五", "六", "日"].map((label, index) => (
            <button key={label} className={scheduleDays.includes(index + 1) ? "day active" : "day"} onClick={() => toggleScheduleDay(index + 1)}>
              周{label}
            </button>
          ))}
        </div>
      </div>

      {progress && <p className="build-progress" role="status"><span className="spinner" aria-hidden />{progress}</p>}

      {jobs.length > 0 && <div className="job-list">
        <div className="section-title"><h3>备课任务</h3><ClipboardText size={18} /></div>
        {jobs.slice(0, 4).map((job) => (
          <div key={job.id} className="job-row">
            <span className={`job-badge ${job.status}`}>{statusLabels[job.status] ?? job.status}</span>
            <div className="job-main">
              <b>{job.provider} · {job.id.slice(0, 8)}</b>
              <p>{job.message}</p>
              {job.status === "failed" && job.error && <p className="job-error">{explainBuildError(job.error)}</p>}
            </div>
            <div className="job-buttons">
              {job.status === "failed" && <button className="secondary" disabled={busy} onClick={() => void retry(job)}>
                <ArrowClockwise size={16} />重试
              </button>}
              {job.status !== "building" && <button className="text-button" onClick={() => void remove(job)} aria-label="删除任务">
                <Trash size={16} />
              </button>}
            </div>
          </div>
        ))}
      </div>}

      {message && <p className="build-result"><WarningCircle size={16} /><span>{message}</span></p>}
    </section>
  );
}
