import { ChartLineUp, CheckCircle, DownloadSimple, ListChecks } from "@phosphor-icons/react";
import { exportLearningData } from "../lib/storage";
import type { Course, Difficulty, PracticeRecord } from "../lib/types";

const labels: Record<Difficulty, string> = {
  A: "A 类 · 词不认识",
  B: "B 类 · 认识但没听出",
  C: "C 类 · 听出来了但没懂"
};

type Props = { courses: Course[]; activeCourse: Course; records: PracticeRecord[] };

export function Review({ courses, activeCourse, records }: Props) {
  const mine = records.filter((item) => item.episodeId === activeCourse.episode_id);
  const passed = mine.filter((item) => item.retest === "pass").length;
  // Sentences that were never opened still need a retest, so count against the
  // lesson rather than against the rows that happen to exist.
  const pending = Math.max(0, activeCourse.sentences.length - passed);

  const counts = (["A", "B", "C"] as Difficulty[])
    .map((value) => ({ value, count: records.filter((item) => item.difficulty === value).length }))
    .sort((left, right) => right.count - left.count);
  const top = counts[0];

  const perCourse = courses
    .map((course) => {
      const rows = records.filter((item) => item.episodeId === course.episode_id);
      return {
        course,
        passed: rows.filter((item) => item.retest === "pass").length,
        pendingRows: rows.filter((item) => item.retest === "not_yet").length
      };
    })
    .filter((item) => item.passed > 0 || item.pendingRows > 0);

  return <main className="page review">
    <div className="eyebrow">只呈现已发生的练习</div>
    <h1>学习复盘</h1>
    <p className="muted">这里不显示虚构分数。你的下一步来自真实卡点和回测结果。</p>

    <section className="review-grid">
      <article className="card stat"><CheckCircle size={25} /><b>{passed}</b><span>本课回测通过</span></article>
      <article className="card stat"><ListChecks size={25} /><b>{pending}</b><span>本课待回测</span></article>
      <article className="card stat">
        <ChartLineUp size={25} />
        <b>{top.count ? top.value : "—"}</b>
        <span>{top.count ? `最高频卡点（${top.count} 次）` : "尚无卡点记录"}</span>
      </article>
    </section>

    <section className="card">
      <div className="section-title"><h3>下一步</h3><span className="soft-label">{activeCourse.title}</span></div>
      {records.length === 0
        ? <p className="empty">先完成任意一句的 A/B/C 标记与回测，这里才会给出基于事实的建议。</p>
        : <p>
            {pending > 0 ? `先回到本课还没通过原速回测的 ${pending} 句。` : "本课已全部通过回测，可以换一节新课。"}
            {top.count > 0 && ` 你最常卡在 ${labels[top.value]}，这一轮多留意这一类。`}
          </p>}
      {counts.some((item) => item.count > 0) && (
        <div className="reason-summary">
          {counts.map((item) => <p key={item.value}><span>{labels[item.value]}</span><b>{item.count} 次</b></p>)}
        </div>
      )}
    </section>

    {perCourse.length > 0 && (
      <section className="card">
        <div className="section-title"><h3>按课程</h3></div>
        {perCourse.map(({ course, passed: done, pendingRows }) => (
          <p key={course.episode_id} className="review-course-row">
            <span>{course.title}</span>
            <b>{done}/{course.sentences.length} 通过{pendingRows > 0 ? ` · ${pendingRows} 句标记为还没听清` : ""}</b>
          </p>
        ))}
      </section>
    )}

    <section className="card export">
      <div>
        <h3>备份自己的学习记录</h3>
        <p>导出 JSON 与 CSV；课程内容、录音和进度仍只留在你的电脑。</p>
      </div>
      <button className="outline" onClick={exportLearningData}><DownloadSimple size={18} />导出记录</button>
    </section>
  </main>;
}
