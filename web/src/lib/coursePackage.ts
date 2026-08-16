import JSZip from "jszip";
import type { Course, Lesson, Manifest } from "./types";

export class CoursePackageError extends Error {}

/** A real 6 Minute English package is ~15 MB; anything far larger is not a course. */
const MAX_ARCHIVE_BYTES = 200 * 1024 * 1024;
const MAX_UNCOMPRESSED_BYTES = 400 * 1024 * 1024;
const MAX_ENTRIES = 32;
const REQUIRED = ["lesson.json", "manifest.json"];

const digest = async (value: ArrayBuffer) => {
  const result = await crypto.subtle.digest("SHA-256", value);
  return [...new Uint8Array(result)].map((item) => item.toString(16).padStart(2, "0")).join("");
};

/** Reject anything that would escape the package root when written out. */
const isSafeEntryName = (name: string) =>
  name.length > 0 && name.length <= 128 && !name.startsWith("/") && !name.includes("\\") &&
  !name.split("/").includes("..") && !/^[a-zA-Z]:/.test(name);

export function validateLesson(lesson: Lesson): void {
  if (lesson.schema_version !== 1 || !lesson.episode_id || !lesson.audio?.file || !lesson.transcript?.file) {
    throw new CoursePackageError("课程包缺少版本或必填字段，可能不是 Clear English Speaking 课程。");
  }
  if (!isSafeEntryName(lesson.audio.file) || !isSafeEntryName(lesson.transcript.file)) {
    throw new CoursePackageError("课程包内的文件名不合法，已拒绝导入。");
  }
  if (typeof lesson.audio.duration_seconds !== "number" || !(lesson.audio.duration_seconds > 0)) {
    throw new CoursePackageError("课程包没有记录有效的音频时长。");
  }
  if (!Array.isArray(lesson.sentences)) {
    throw new CoursePackageError("课程包缺少句子列表。");
  }
  // A listen-only lesson deliberately carries no timed sentences: the episode
  // is still fully playable, it just has no per-sentence drill.
  const listenOnly = lesson.mode === "listen_only";
  if (listenOnly ? lesson.sentences.length !== 0 : lesson.sentences.length < 5 || lesson.sentences.length > 6) {
    throw new CoursePackageError(listenOnly ? "只可收听的课程不应包含练习句。" : "练习句必须是 5–6 句官方原句。");
  }
  let lastEnd = -1;
  for (const sentence of lesson.sentences) {
    if (!sentence.text || typeof sentence.start !== "number" || typeof sentence.end !== "number") {
      throw new CoursePackageError("课程包里有句子缺少原文或时间。");
    }
    if (!sentence.id) throw new CoursePackageError("课程包里有句子缺少编号。");
    if (sentence.start < 0 || sentence.end <= sentence.start || sentence.end > lesson.audio.duration_seconds || sentence.start < lastEnd) {
      throw new CoursePackageError("句子时间轴无效、重叠或超出音频时长。");
    }
    lastEnd = sentence.end;
  }
  if (new Set(lesson.sentences.map((item) => item.id)).size !== lesson.sentences.length) {
    throw new CoursePackageError("课程包里有重复的句子编号。");
  }
}

export async function readCoursePackage(file: File): Promise<Course> {
  if (file.size > MAX_ARCHIVE_BYTES) {
    throw new CoursePackageError("这个 ZIP 超过 200 MB，不像是 Clear English Speaking 课程包。");
  }
  let zip: JSZip;
  try {
    // Read the bytes here rather than letting JSZip pick a reader: the result
    // is identical in the desktop WebView, the browser and the test runner.
    zip = await JSZip.loadAsync(await file.arrayBuffer());
  } catch {
    throw new CoursePackageError("这个文件不是有效的 ZIP，无法导入。");
  }
  const entries = Object.values(zip.files).filter((entry) => !entry.dir);
  if (entries.length > MAX_ENTRIES) throw new CoursePackageError("课程包内文件过多，已拒绝导入。");
  const unsafe = entries.find((entry) => !isSafeEntryName(entry.name));
  if (unsafe) throw new CoursePackageError("课程包内含不安全的文件路径，已拒绝导入。");
  if (new Set(entries.map((entry) => entry.name)).size !== entries.length) {
    throw new CoursePackageError("课程包内有重复条目，已拒绝导入。");
  }

  const lessonFile = zip.file("lesson.json");
  const manifestFile = zip.file("manifest.json");
  if (!lessonFile || !manifestFile) throw new CoursePackageError(`课程包必须含 ${REQUIRED.join(" 与 ")}。`);

  let lesson: Lesson;
  let manifest: Manifest;
  try {
    lesson = JSON.parse(await lessonFile.async("text")) as Lesson;
    manifest = JSON.parse(await manifestFile.async("text")) as Manifest;
  } catch {
    throw new CoursePackageError("课程包的 lesson.json 或 manifest.json 不是合法 JSON。");
  }
  if (manifest.schema_version !== 1) throw new CoursePackageError("不支持的课程包版本。");
  if (!manifest.files || typeof manifest.files !== "object") throw new CoursePackageError("课程包缺少文件校验信息。");
  // Packages built before the engine assigned sentence ids are already on
  // users' disks. Deriving the id from position keeps them importable; the
  // order inside a package never changes, so records stay stable.
  if (Array.isArray(lesson.sentences)) {
    lesson.sentences.forEach((sentence, position) => {
      if (sentence && !sentence.id) sentence.id = `s${position + 1}`;
    });
  }
  validateLesson(lesson);

  const declared = Object.values(manifest.files).reduce((total, item) => total + (Number(item.bytes) || 0), 0);
  if (declared > MAX_UNCOMPRESSED_BYTES) throw new CoursePackageError("课程包解压后过大，已拒绝导入。");

  let unpacked = 0;
  for (const [path, expected] of Object.entries(manifest.files)) {
    if (!isSafeEntryName(path)) throw new CoursePackageError("课程包的校验清单含不安全路径。");
    const entry = zip.file(path);
    if (!entry) throw new CoursePackageError(`课程包缺少 ${path}。`);
    const raw = await entry.async("arraybuffer");
    unpacked += raw.byteLength;
    if (unpacked > MAX_UNCOMPRESSED_BYTES) throw new CoursePackageError("课程包解压后过大，已拒绝导入。");
    if (typeof expected.bytes === "number" && raw.byteLength !== expected.bytes) {
      throw new CoursePackageError(`${path} 大小与校验清单不符。`);
    }
    if ((await digest(raw)) !== expected.sha256) throw new CoursePackageError(`${path} 校验失败，文件可能已损坏。`);
  }
  if (!("lesson.json" in manifest.files)) throw new CoursePackageError("校验清单没有覆盖 lesson.json。");

  const audioEntry = zip.file(lesson.audio.file);
  const transcriptEntry = zip.file(lesson.transcript.file);
  if (!audioEntry || !transcriptEntry) throw new CoursePackageError("课程包音频或原文文件不完整。");
  if (!(lesson.audio.file in manifest.files)) throw new CoursePackageError("音频没有通过校验清单验证。");

  return {
    ...lesson,
    importedAt: new Date().toISOString(),
    archiveBytes: file.size,
    audioUrl: URL.createObjectURL(await audioEntry.async("blob")),
    transcriptUrl: URL.createObjectURL(await transcriptEntry.async("blob"))
  };
}
