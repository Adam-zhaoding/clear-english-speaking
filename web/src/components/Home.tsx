import { ArrowRight, BookOpen, CheckCircle, Headphones, Sparkle } from "@phosphor-icons/react";
import type { Course, PracticeRecord } from "../lib/types";

const greeting = () => {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
};

type Props = {
  course: Course;
  courses: Course[];
  records: PracticeRecord[];
  loading: boolean;
  onSelectCourse: (episodeId: string) => void;
  goPractice: () => void;
  goStudio: () => void;
  goLibrary: () => void;
};

export function Home({ course, courses, records, loading, onSelectCourse, goPractice, goStudio, goLibrary }: Props) {
  // Sentence ids repeat across lessons, so progress has to be counted per
  // episode; keying on the sentence id alone silently merged different courses.
  const mine = records.filter((item) => item.episodeId === course.episode_id);
  const passed = new Set(mine.filter((item) => item.retest === "pass").map((item) => item.sentenceId)).size;
  const marked = new Set(mine.filter((item) => item.difficulty).map((item) => item.sentenceId)).size;
  const passedEverywhere = new Set(
    records.filter((item) => item.retest === "pass").map((item) => `${item.episodeId}/${item.sentenceId}`)
  ).size;
  const remaining = Math.max(0, course.sentences.length - passed);
  const listenOnly = course.sentences.length === 0;

  return <main className="page home">
    <div className="eyebrow">✦ 你的私人听力练习册</div>
    <h1>{greeting()}。</h1>
    <p className="muted">今天不用追求听懂全部，只要把一个原来模糊的声音听清。</p>

    <section className="hero-card">
      <div>
        <span className="tag">{listenOnly ? "只可收听" : course.isDemo ? "演示课 · 先试用" : `本课共 ${course.sentences.length} 句`}</span>
        <h2>{course.title}</h2>
        <p>{listenOnly
          ? "这一集没有生成逐句训练，但整集音频可以完整播放、暂停和快进快退。"
          : remaining > 0
            ? `裸听 → 标记卡点 → 对照 → 原速回测（还剩 ${remaining} 句未通过）`
            : "这节课已全部通过回测，可以挑战下一课。"}</p>
        <button className="primary" onClick={goPractice}>
          {listenOnly ? "整集收听" : passed > 0 ? "继续今天的训练" : "开始今天的训练"} <ArrowRight size={18} />
        </button>
      </div>
      <div className="hero-orb"><Headphones size={52} weight="thin" /></div>
    </section>

    <section className="split-grid">
      <article className="card">
        <div className="section-title"><h3>这节课的进度</h3><span className="soft-label">真实记录</span></div>
        <div className="overview">
          <div className="ring"><b>{passed}</b><span>已回测</span></div>
          <div className="metric-list">
            <p><span>本课练习句</span><b>{course.sentences.length} 句</b></p>
            <p><span>已标记卡点</span><b>{marked} 句</b></p>
            <p><span>累计回测通过</span><b>{passedEverywhere} 句</b></p>
          </div>
        </div>
        <small>{records.length === 0
          ? "暂无口语评分。完成任意一句的回测后，这里才会出现你的真实进度。"
          : "这里只统计你实际完成的标记与回测，不含任何估算分数。"}</small>
      </article>

      <article className="card build-card">
        <div className="section-title"><h3>本次备课</h3><Sparkle size={22} /></div>
        <p>Clear English 会在你的电脑上，从 BBC 官方来源构建课程并永久保存在本机。</p>
        <button className="quiet-button" onClick={goStudio}>打开备课中心 <ArrowRight size={16} /></button>
      </article>
    </section>

    <section className="card course-list">
      <div className="section-title">
        <h3>我的课程（{courses.length}）</h3>
        <button className="text-button" onClick={goLibrary}>管理课程库</button>
      </div>
      {loading && <p className="muted">正在读取本机课程……</p>}
      {courses.slice(0, 5).map((item) => (
        <button
          key={item.episode_id}
          className={item.episode_id === course.episode_id ? "course-row active" : "course-row"}
          onClick={() => onSelectCourse(item.episode_id)}
        >
          <div className="course-icon">{item.episode_id === course.episode_id ? <CheckCircle size={22} /> : <BookOpen size={22} />}</div>
          <div>
            <b>{item.title}</b>
            <p>{item.sentences.length ? `${item.sentences.length} 个精选句 · 离线可练` : "只可收听 · 离线可听"}</p>
          </div>
          <ArrowRight size={20} />
        </button>
      ))}
    </section>
  </main>;
}
