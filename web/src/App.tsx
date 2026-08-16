import { FileArrowUp } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CourseLibrary } from "./components/CourseLibrary";
import { Home } from "./components/Home";
import { Practice } from "./components/Practice";
import { Review } from "./components/Review";
import { Sidebar, type View } from "./components/Sidebar";
import { Studio } from "./components/Studio";
import { fetchAgentCourses, isAgentPaired } from "./lib/agent";
import { readCoursePackage } from "./lib/coursePackage";
import { demoCourse } from "./lib/demo";
import { deleteLocalCourse, ensureDemoCourse, isDesktop, listLocalCourses, readCourseFile } from "./lib/desktop";
import {
  deleteCourseArchive, loadActiveCourseId, loadCourseArchives, loadRecords,
  removeRecordsFor, saveActiveCourseId, saveCourseArchive, saveCourses
} from "./lib/storage";
import type { Course, PracticeRecord } from "./lib/types";

/** Path of the ZIP in the local library, so the course can be deleted later. */
type SourcePaths = Record<string, string>;

export default function App() {
  const [view, setView] = useState<View>("home");
  const [courses, setCourses] = useState<Course[]>([]);
  const [records, setRecords] = useState<PracticeRecord[]>(() => loadRecords());
  const [activeId, setActiveId] = useState(() => loadActiveCourseId());
  const [sources, setSources] = useState<SourcePaths>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const demo = useMemo(() => demoCourse(), []);

  const playable = courses.length ? courses : [demo];
  const course = playable.find((item) => item.episode_id === activeId) ?? playable[0];

  const importCourse = useCallback(async (file?: File, options: { persist?: boolean; sourcePath?: string } = {}) => {
    if (!file) return undefined;
    const { persist = true, sourcePath } = options;
    const next = await readCoursePackage(file);
    setCourses((current) => {
      const values = [next, ...current.filter((item) => item.episode_id !== next.episode_id)];
      saveCourses(values);
      return values;
    });
    if (sourcePath) setSources((current) => ({ ...current, [next.episode_id]: sourcePath }));
    if (persist) await saveCourseArchive(next.episode_id, file);
    return next;
  }, []);

  /** Used by the import button and the studio, where failures must be visible. */
  const importWithFeedback = useCallback(async (file?: File) => {
    if (!file) return undefined;
    try {
      const next = await importCourse(file);
      if (next) {
        setActiveId(next.episode_id);
        saveActiveCourseId(next.episode_id);
        setError("");
      }
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "课程包导入失败。");
      return undefined;
    }
  }, [importCourse]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const failures: string[] = [];
      const attempt = async (run: () => Promise<unknown>) => {
        try {
          await run();
        } catch (reason) {
          failures.push(reason instanceof Error ? reason.message : String(reason));
        }
      };
      for (const archive of await loadCourseArchives()) {
        await attempt(() => importCourse(archive, { persist: false }));
      }
      if (isDesktop()) {
        // A brand-new machine has no lesson at all; write the synthetic one so
        // the very first click on 播放 actually produces sound.
        await attempt(async () => {
          const paths = await listLocalCourses();
          if (!paths.length) await ensureDemoCourse();
        });
        let paths: string[] = [];
        await attempt(async () => { paths = await listLocalCourses(); });
        for (const path of paths) {
          await attempt(async () => {
            await importCourse(await readCourseFile(path), { sourcePath: path });
          });
        }
      } else if (isAgentPaired()) {
        await attempt(async () => {
          for (const item of await fetchAgentCourses()) await importCourse(item);
        });
      }
      if (cancelled) return;
      if (failures.length) setError(`有 ${failures.length} 个本机课程包未能导入：${failures[0]}`);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [importCourse]);

  const selectCourse = (episodeId: string) => {
    setActiveId(episodeId);
    saveActiveCourseId(episodeId);
    setView("practice");
  };

  const removeCourse = async (target: Course) => {
    if (target.isDemo) return;
    setCourses((current) => {
      const values = current.filter((item) => item.episode_id !== target.episode_id);
      saveCourses(values);
      return values;
    });
    setRecords(removeRecordsFor(target.episode_id));
    if (target.audioUrl) URL.revokeObjectURL(target.audioUrl);
    if (target.transcriptUrl) URL.revokeObjectURL(target.transcriptUrl);
    await deleteCourseArchive(target.episode_id).catch(() => undefined);
    const path = sources[target.episode_id];
    if (path && isDesktop()) await deleteLocalCourse(path).catch(() => undefined);
    if (activeId === target.episode_id) {
      setActiveId("");
      saveActiveCourseId("");
    }
  };

  return <div className="app-shell">
    <Sidebar view={view} setView={setView} courseCount={courses.length} />
    <div className="app-content">
      <header className="topbar">
        <span>本地优先 · 默认不上传</span>
        <div>
          <input
            ref={input}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(event) => {
              void importWithFeedback(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <button className="import-button" onClick={() => input.current?.click()}>
            <FileArrowUp size={18} />导入 ZIP 课程包
          </button>
        </div>
      </header>
      {error && <div className="error-banner" role="alert">
        <span>{error}</span>
        <button className="text-button" onClick={() => setError("")}>知道了</button>
      </div>}
      {view === "home" && <Home
        course={course}
        courses={playable}
        records={records}
        loading={loading}
        onSelectCourse={selectCourse}
        goPractice={() => setView("practice")}
        goStudio={() => setView("studio")}
        goLibrary={() => setView("library")}
      />}
      {view === "practice" && <Practice course={course} records={records} onUpdate={setRecords} />}
      {view === "library" && <CourseLibrary
        courses={playable}
        activeId={course.episode_id}
        records={records}
        onSelect={selectCourse}
        onDelete={removeCourse}
        onImportClick={() => input.current?.click()}
      />}
      {view === "studio" && <Studio onImportCourse={importWithFeedback} />}
      {view === "review" && <Review courses={playable} activeCourse={course} records={records} />}
    </div>
  </div>;
}
