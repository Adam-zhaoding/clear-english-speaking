import {
  ArrowCounterClockwise, ArrowClockwise, Check, Eye, EyeSlash, FilePdf, Headphones, Microphone,
  Pause, Play, Repeat, SkipBack, SkipForward, SpeakerHigh, Stop, Translate, WarningCircle
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { openExternal, openTranscript } from "../lib/desktop";
import { downloadBlob, upsertRecord } from "../lib/storage";
import type { Course, Difficulty, PracticeRecord } from "../lib/types";

const reasons: { value: Difficulty; title: string; text: string }[] = [
  { value: "A", title: "A｜词不认识", text: "词汇或语块不足" },
  { value: "B", title: "B｜认识但没听出", text: "声音识别失败" },
  { value: "C", title: "C｜听出来了但没懂", text: "句法或逻辑理解失败" }
];

const speeds = [0.6, 0.75, 1, 1.25];

const clock = (value: number) => {
  if (!Number.isFinite(value) || value < 0) return "0:00";
  const total = Math.floor(value);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

export function Practice({ course, records, onUpdate }: { course: Course; records: PracticeRecord[]; onUpdate: (value: PracticeRecord[]) => void }) {
  const total = course.sentences.length;
  // Sentence drilling needs timed sentences; whole-episode listening never
  // does, so a lesson without them still opens as a working player.
  const drillAvailable = total > 0;

  const [index, setIndex] = useState(0);
  // Listening to the whole episode is the natural first step, and it is the
  // only mode that always works; shadow reading is opt-in from here.
  const [wholeEpisode, setWholeEpisode] = useState(true);
  const [showText, setShowText] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(course.audio.duration_seconds || 0);
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(false);
  const [recording, setRecording] = useState(false);
  const [notice, setNotice] = useState("");
  const audio = useRef<HTMLAudioElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  // The microphone is acquired once per visit, not once per sentence: asking
  // again for every take makes the browser re-prompt and interrupts the drill.
  const micStream = useRef<MediaStream | null>(null);
  const micPending = useRef<Promise<MediaStream> | null>(null);
  const loopRef = useRef(loop);
  loopRef.current = loop;

  const safeIndex = Math.min(index, Math.max(0, total - 1));
  const sentence = drillAvailable ? course.sentences[safeIndex] : undefined;
  // Whole-episode mode must never be constrained by a sentence span.
  const bounds = wholeEpisode || !sentence ? { start: 0, end: duration || course.audio.duration_seconds } : { start: sentence.start, end: sentence.end };

  useEffect(() => {
    setIndex(0);
    setShowText(false);
    setPlaying(false);
    setPosition(0);
    setWholeEpisode(true);
    audio.current?.pause();
  }, [course.episode_id, course.sentences.length]);

  useEffect(() => { if (audio.current) audio.current.playbackRate = speed; }, [speed]);

  useEffect(() => {
    const element = audio.current;
    if (!element) return undefined;
    const onTime = () => {
      setPosition(element.currentTime);
      // Only sentence drilling stops early; the whole episode plays to its end.
      if (wholeEpisode || !sentence) return;
      if (element.currentTime < sentence.end) return;
      if (loopRef.current) {
        element.currentTime = sentence.start;
        return;
      }
      element.pause();
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => {
      setPlaying(false);
      if (wholeEpisode && loopRef.current) {
        element.currentTime = 0;
        void element.play();
      }
    };
    const onMeta = () => setDuration(element.duration || course.audio.duration_seconds);
    element.addEventListener("timeupdate", onTime);
    element.addEventListener("play", onPlay);
    element.addEventListener("pause", onPause);
    element.addEventListener("ended", onEnded);
    element.addEventListener("loadedmetadata", onMeta);
    if (element.readyState >= 1) onMeta();
    return () => {
      element.removeEventListener("timeupdate", onTime);
      element.removeEventListener("play", onPlay);
      element.removeEventListener("pause", onPause);
      element.removeEventListener("ended", onEnded);
      element.removeEventListener("loadedmetadata", onMeta);
    };
  }, [sentence, wholeEpisode, course.audio.duration_seconds]);

  useEffect(() => () => {
    recorder.current?.stream?.getTracks().forEach((track) => track.stop());
  }, []);

  const record = sentence && records.find((item) => item.episodeId === course.episode_id && item.sentenceId === sentence.id);

  const openOfficialTranscript = async () => {
    if (!course.transcriptUrl) return;
    setNotice("正在打开官方原文……");
    try {
      await openTranscript(course.transcriptUrl, course.episode_id);
      setNotice("已用你电脑的 PDF 阅读器打开这一集的官方原文。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法打开官方原文。");
    }
  };

  const openSource = async () => {
    if (!course.source?.bbc_page_url) return;
    try {
      await openExternal(course.source.bbc_page_url);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法打开 BBC 官方页面。");
    }
  };

  const togglePlay = async () => {
    const element = audio.current;
    if (!element) return;
    if (!element.paused) {
      element.pause();
      return;
    }
    if (element.currentTime < bounds.start || element.currentTime >= bounds.end) element.currentTime = bounds.start;
    element.playbackRate = speed;
    try {
      await element.play();
      setNotice("");
    } catch {
      setNotice("这节课的音频无法播放，请到课程库删除后重新导入或重新备课。");
    }
  };

  const seekTo = (value: number) => {
    const element = audio.current;
    if (!element) return;
    const target = Math.min(Math.max(value, bounds.start), Math.max(bounds.start, bounds.end - 0.05));
    element.currentTime = target;
    setPosition(target);
  };

  const nudge = (seconds: number) => seekTo((audio.current?.currentTime ?? 0) + seconds);

  const goto = (next: number) => {
    const bounded = Math.min(Math.max(next, 0), total - 1);
    if (bounded === safeIndex) return;
    audio.current?.pause();
    setIndex(bounded);
    setShowText(false);
  };

  const mark = (difficulty?: Difficulty, retest?: "pass" | "not_yet") => {
    if (!sentence) return;
    onUpdate(upsertRecord({
      episodeId: course.episode_id,
      sentenceId: sentence.id,
      difficulty: difficulty ?? record?.difficulty,
      retest: retest ?? record?.retest,
      updatedAt: new Date().toISOString()
    }));
  };

  // Release the microphone when the user leaves practice, not between takes.
  useEffect(() => () => {
    micStream.current?.getTracks().forEach((track) => track.stop());
    micStream.current = null;
  }, []);

  const ensureMicStream = () => {
    const live = micStream.current?.getAudioTracks().some((track) => track.readyState === "live");
    if (micStream.current && live) return Promise.resolve(micStream.current);
    // A stream whose track died (device unplugged, reclaimed by the OS) is useless.
    micStream.current?.getTracks().forEach((track) => track.stop());
    micStream.current = null;
    // Double-clicking must not turn into two permission prompts.
    if (!micPending.current) {
      micPending.current = navigator.mediaDevices.getUserMedia({ audio: true })
        .then((stream) => { micStream.current = stream; micPending.current = null; return stream; })
        .catch((error) => { micPending.current = null; throw error; });
    }
    return micPending.current;
  };

  const toggleRecording = async () => {
    if (recording) {
      recorder.current?.stop();
      setRecording(false);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setNotice("这台设备不支持录音。你仍然可以完成全部听力训练和回测。");
      return;
    }
    try {
      const stream = await ensureMicStream();
      chunks.current = [];
      const instance = new MediaRecorder(stream);
      recorder.current = instance;
      instance.ondataavailable = (event) => chunks.current.push(event.data);
      instance.onstop = () => {
        const label = sentence ? sentence.id : "episode";
        downloadBlob(`${course.episode_id}-${label}-shadow.webm`, new Blob(chunks.current, { type: "audio/webm" }));
        // The stream stays open on purpose: stopping it would re-prompt next take.
        setNotice("跟读录音已保存到你的下载目录。");
      };
      instance.start();
      setRecording(true);
      setNotice("");
    } catch {
      setNotice("麦克风未授权。你仍可继续听力训练和回测。");
    }
  };

  const elapsed = wholeEpisode ? position : Math.max(0, position - bounds.start);
  const span = wholeEpisode ? (duration || course.audio.duration_seconds) : bounds.end - bounds.start;

  return <main className="page practice">
    <header className="practice-header">
      <div>
        <span className="eyebrow">
          {wholeEpisode ? "整集播放" : `练习室 · 第 ${safeIndex + 1} / ${total} 句`}
        </span>
        <h1>{course.title}</h1>
      </div>
      <div className="practice-header-actions">
        {drillAvailable && <button className={wholeEpisode ? "primary" : "outline"} onClick={() => setWholeEpisode(!wholeEpisode)}>
          <Headphones size={18} />{wholeEpisode ? `影子跟读（${total} 句）` : "回到整集播放"}
        </button>}
        {!wholeEpisode && sentence && <button className="outline" onClick={() => setShowText(!showText)}>
          {showText ? <EyeSlash size={18} /> : <Eye size={18} />}{showText ? "隐藏文本" : "显示文本"}
        </button>}
      </div>
    </header>

    {!drillAvailable && <div className="listen-only-banner">
      <WarningCircle size={20} />
      <div>
        <b>这一集没有生成逐句训练。</b>
        <p>
          {course.degraded?.reason || "官方音频与原文都已校验通过，但句子未能定位到音频。"}
          你仍然可以完整收听整集，并查看官方原文；想要逐句训练，可以到「备课」页重新备课或换一集。
        </p>
      </div>
    </div>}

    <audio ref={audio} src={course.audioUrl} preload="auto" />

    <div className={wholeEpisode ? "practice-grid whole" : "practice-grid"}>
      <section className="player-panel card">
        <span className="tag">{wholeEpisode ? "完整音频 · 可暂停、可快进快退" : "裸听 → 对照 → 原速回测"}</span>

        {wholeEpisode
          ? <p className="sentence hidden episode-hint">整集连续播放。用下面的进度条跳到任意位置，或用 ±10 秒微调。</p>
          : <p className={showText ? "sentence visible" : "sentence hidden"}>
              {showText ? sentence?.text : "先不看文字，听清这一句在说什么。"}
            </p>}

        <div className="scrubber">
          <span className="time">{clock(elapsed)}</span>
          <input
            type="range"
            aria-label="播放进度"
            min={bounds.start}
            max={Math.max(bounds.start + 0.1, bounds.end)}
            step={0.1}
            value={Math.min(Math.max(position, bounds.start), bounds.end)}
            onChange={(event) => seekTo(Number(event.target.value))}
          />
          <span className="time">{clock(span)}</span>
        </div>

        <div className="audio-controls">
          {wholeEpisode
            ? <button onClick={() => nudge(-10)} aria-label="后退 10 秒"><ArrowCounterClockwise size={24} /></button>
            : <button onClick={() => goto(safeIndex - 1)} disabled={safeIndex === 0} aria-label="上一句"><SkipBack size={24} /></button>}
          <button className="play-button" onClick={() => void togglePlay()} aria-label={playing ? "暂停" : "播放"}>
            {playing ? <Pause weight="fill" size={30} /> : <Play weight="fill" size={30} />}
          </button>
          {wholeEpisode
            ? <button onClick={() => nudge(10)} aria-label="快进 10 秒"><ArrowClockwise size={24} /></button>
            : <button onClick={() => goto(safeIndex + 1)} disabled={safeIndex >= total - 1} aria-label="下一句"><SkipForward size={24} /></button>}
        </div>

        <div className="control-row">
          <button onClick={() => nudge(-5)} aria-label="回退 5 秒"><ArrowCounterClockwise size={18} /> 回退 5 秒</button>
          {speeds.map((item) => (
            <button key={item} className={speed === item ? "selected" : ""} onClick={() => setSpeed(item)}>{item}×</button>
          ))}
          <button className={loop ? "selected" : ""} onClick={() => setLoop(!loop)} aria-pressed={loop}>
            <Repeat size={18} />{loop ? "循环中" : wholeEpisode ? "整集循环" : "单句循环"}
          </button>
          <button onClick={() => void toggleRecording()} className={recording ? "recording" : ""}>
            {recording ? <Stop size={18} /> : <Microphone size={18} />}{recording ? "结束并保存" : "可选跟读"}
          </button>
        </div>
        <p className="record-note">录音只在本机生成并下载，不上传、不评分。</p>
        {notice && <p className="build-result">{notice}</p>}
      </section>

      <aside className="coach-panel">
        {wholeEpisode || !sentence
          ? <section className="card explanation">
              <div className="section-title"><h3>整集收听</h3><Headphones size={21} /></div>
              <p>没有隐藏文本，也不记录卡点。想练某一句时，{drillAvailable ? "点右上角「回到逐句训练」。" : "请重新备课生成逐句训练。"}</p>
              {course.source?.bbc_page_url && (
                <button className="text-button" onClick={() => void openSource()}>打开 BBC 官方页面</button>
              )}
              {course.transcriptUrl && (
                <button className="text-button" onClick={() => void openOfficialTranscript()}>
                  <FilePdf size={17} />打开这一集的官方原文
                </button>
              )}
            </section>
          : <>
              <section className="card">
                <div className="section-title"><h3>这句卡在哪里？</h3><Headphones size={21} /></div>
                <p className="muted">可跳过；只标记你真正卡住的地方。</p>
                <div className="reason-list">
                  {reasons.map((reason) => (
                    <button
                      key={reason.value}
                      className={record?.difficulty === reason.value ? "reason active" : "reason"}
                      onClick={() => mark(reason.value)}
                    >
                      <b>{reason.title}</b><span>{reason.text}</span>
                    </button>
                  ))}
                </div>
              </section>
              <section className="card explanation">
                <div className="section-title"><h3>针对性提示</h3><SpeakerHigh size={21} /></div>
                {sentence.listening_focus && <p><b>听力关注：</b>{sentence.listening_focus}</p>}
                {sentence.comprehension_check && <p><b>理解检查：</b>{sentence.comprehension_check}</p>}
                {sentence.diagnosis_tags?.length > 0 && (
                  <div className="tag-row">{sentence.diagnosis_tags.map((tag) => <span key={tag} className="soft-label">{tag}</span>)}</div>
                )}
                {showText && <>
                  <p className="translation"><Translate size={17} />{sentence.translation_zh}</p>
                  {sentence.glossary?.length > 0 && (
                    <div className="glossary">{sentence.glossary.map((item) => <span key={item.surface}>{item.surface} · {item.gloss_zh}</span>)}</div>
                  )}
                </>}
                {course.transcriptUrl && (
                  <button className="text-button" onClick={() => void openOfficialTranscript()}>
                    <FilePdf size={17} />打开这一集的官方原文
                  </button>
                )}
              </section>
              <section className="card retest">
                <h3>原速回测</h3>
                <p>隐藏文本，把语速调回 1× 再听一遍，然后记录结果。</p>
                <div>
                  <button className={record?.retest === "pass" ? "pass selected" : "pass"} onClick={() => mark(undefined, "pass")}>
                    <Check size={17} />通过
                  </button>
                  <button className={record?.retest === "not_yet" ? "outline selected" : "outline"} onClick={() => mark(undefined, "not_yet")}>
                    还没听清
                  </button>
                </div>
              </section>
            </>}
      </aside>
    </div>
  </main>;
}
