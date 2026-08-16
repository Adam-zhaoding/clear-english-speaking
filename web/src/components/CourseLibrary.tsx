import { BookOpen, FileArrowUp, FolderOpen, Trash } from "@phosphor-icons/react";
import { useState } from "react";
import { isDesktop, openCourseFolder, openExternal } from "../lib/desktop";
import type { Course, PracticeRecord } from "../lib/types";

const megabytes = (bytes?: number) => (bytes ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : "—");
const day = (value?: string) => (value ? new Date(value).toLocaleDateString("zh-CN") : "—");

type Props = {
  courses: Course[];
  activeId: string;
  records: PracticeRecord[];
  onSelect: (episodeId: string) => void;
  onDelete: (course: Course) => Promise<void>;
  onImportClick: () => void;
};

export function CourseLibrary({ courses, activeId, records, onSelect, onDelete, onImportClick }: Props) {
  const [confirming, setConfirming] = useState("");

  const passedIn = (course: Course) => records.filter(
    (item) => item.episodeId === course.episode_id && item.retest === "pass"
  ).length;

  return <main className="page library">
    <div className="eyebrow">全部课程都保存在你自己的电脑上</div>
    <h1>课程库</h1>
    <p className="muted">选择要练习的课程。删除只影响本机文件，不会上传任何东西。</p>

    <div className="library-actions">
      <button className="secondary" onClick={onImportClick}><FileArrowUp size={17} />导入 ZIP 课程包</button>
      {isDesktop() && <button className="secondary" onClick={() => void openCourseFolder()}>
        <FolderOpen size={17} />打开课程文件夹
      </button>}
    </div>

    <section className="card course-list">
      {courses.map((course) => (
        <div key={course.episode_id} className={course.episode_id === activeId ? "library-row active" : "library-row"}>
          <div className="course-icon"><BookOpen size={22} /></div>
          <div className="library-main">
            <b>{course.title}</b>
            <p>
              {course.sentences.length
                ? `${course.sentences.length} 句 · 已回测 ${passedIn(course)} 句`
                : "只可收听 · 无逐句训练"} · {megabytes(course.archiveBytes)} · 导入于 {day(course.importedAt)}
            </p>
            {course.sentences.length === 0 && course.degraded?.reason && (
              <p className="degraded-note">{course.degraded.reason}</p>
            )}
            {course.source?.bbc_page_url
              ? <button className="source-link" onClick={() => void openExternal(course.source.bbc_page_url)}>BBC 官方页面</button>
              : <span className="soft-label">本地演示课</span>}
          </div>
          <div className="library-buttons">
            <button className="secondary" onClick={() => onSelect(course.episode_id)}>{course.sentences.length ? "练习" : "收听"}</button>
            {!course.isDemo && (confirming === course.episode_id
              ? <>
                  <button className="danger" onClick={() => { setConfirming(""); void onDelete(course); }}>确认删除</button>
                  <button className="text-button" onClick={() => setConfirming("")}>取消</button>
                </>
              : <button className="outline" onClick={() => setConfirming(course.episode_id)} aria-label={`删除 ${course.title}`}>
                  <Trash size={17} />删除
                </button>)}
          </div>
        </div>
      ))}
      {confirming && <p className="muted">删除会同时清除这节课的 A/B/C 标记和回测记录，且无法撤销。</p>}
    </section>
  </main>;
}
