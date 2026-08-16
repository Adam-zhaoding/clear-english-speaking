import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export const isDesktop = () => "__TAURI_INTERNALS__" in window;

export interface DesktopStatus {
  desktop: boolean;
  codexAvailable: boolean;
  workbuddyAvailable: boolean;
  workbuddyHome: string;
  dataDirectory: string;
}

export interface WorkBuddySetup {
  workspace: string;
  jobId: string;
  prompt: string;
  promptCopied: boolean;
  launchAttempted: boolean;
}

export type JobStatus = "awaiting_agent" | "draft_ready" | "building" | "imported" | "failed";

export interface DesktopJob {
  id: string;
  provider: string;
  status: JobStatus;
  createdAt: string;
  updatedAt: string;
  message: string;
  error: string;
  ready: boolean;
}

export interface BuildProgress {
  jobId: string;
  stage: string;
  message: string;
}

export const getDesktopStatus = () => invoke<DesktopStatus>("desktop_status");
export const connectWorkBuddy = () => invoke<WorkBuddySetup>("prepare_workbuddy");
export const openWorkBuddy = () => invoke<void>("open_workbuddy");
export const startCodexJob = () => invoke<string>("start_codex_job");
export const startApiCourse = () => invoke<string>("start_api_course");
export const listDesktopJobs = () => invoke<DesktopJob[]>("list_desktop_jobs");
export const buildDesktopJob = (jobId: string) => invoke<string>("build_desktop_job", { jobId });
export const deleteDesktopJob = (jobId: string) => invoke<void>("delete_desktop_job", { jobId });
export const retryDesktopJob = (jobId: string) => invoke<void>("retry_desktop_job", { jobId });
export const markJobImported = (jobId: string) => invoke<void>("mark_job_imported", { jobId });
export const listLocalCourses = () => invoke<string[]>("list_local_courses");
export const deleteLocalCourse = (path: string) => invoke<void>("delete_local_course", { path });
export const openCourseFolder = () => invoke<void>("open_course_folder");
export const ensureDemoCourse = () => invoke<string>("ensure_demo_course");
/** Raw bytes, not base64: a real course is far too large for a JSON string. */
export const readCourseBytes = (path: string) => invoke<ArrayBuffer>("read_course_bytes", { path });
export const saveApiConfiguration = (baseUrl: string, model: string, apiKey: string) =>
  invoke<void>("configure_api", { configuration: { baseUrl, model, apiKey } });
export const saveDesktopSchedule = (days: number[], time: string, timezone: string, provider: string, enabled: boolean) =>
  invoke<string>("configure_schedule", { configuration: { days, time, timezone, provider, enabled } });

/** Stream build phases from the engine; returns an unsubscribe function. */
export function onBuildProgress(handler: (progress: BuildProgress) => void): () => void {
  if (!isDesktop()) return () => undefined;
  const pending = listen<BuildProgress>("course-build-progress", (event) => handler(event.payload));
  return () => void pending.then((stop) => stop());
}

export function courseFileFromBytes(data: ArrayBuffer | Uint8Array, fileName = "clear-english-speaking-course.zip") {
  // Both forms are valid BlobParts at runtime; the cast is only needed because
  // the DOM lib types Uint8Array's buffer as possibly shared.
  return new File([data as BlobPart], fileName, { type: "application/zip" });
}

/**
 * Show the lesson transcript.
 *
 * The desktop web view cannot open a `blob:` URL in a new window, so there the
 * bytes are written to disk and handed to the user's PDF reader; in a browser
 * the blob opens in a new tab as usual.
 */
export async function openTranscript(transcriptUrl: string, episodeId: string): Promise<void> {
  if (!isDesktop()) {
    const opened = window.open(transcriptUrl, "_blank", "noopener");
    if (!opened) throw new Error("浏览器拦截了新窗口，请允许弹出窗口后重试。");
    return;
  }
  const response = await fetch(transcriptUrl);
  const bytes = new Uint8Array(await response.arrayBuffer());
  await invoke<string>("open_transcript", { fileName: `${episodeId}-transcript.pdf`, data: Array.from(bytes) });
}

/** Open an official source page in the user's real browser. */
export async function openExternal(url: string): Promise<void> {
  if (!isDesktop()) {
    window.open(url, "_blank", "noopener");
    return;
  }
  await invoke<void>("open_external", { url });
}

/** Read a course from the local library and wrap it as a File for the importer. */
export async function readCourseFile(path: string): Promise<File> {
  const name = path.split(/[\\/]/).pop() || "clear-english-speaking-course.zip";
  return courseFileFromBytes(await readCourseBytes(path), name);
}
