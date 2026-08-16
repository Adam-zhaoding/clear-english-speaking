import type { Course, PracticeRecord } from "./types";

const coursesKey = "clear-english-courses";
const recordsKey = "clear-english-records";
const activeKey = "clear-english-active-course";
const databaseName = "clear-english-player";
const archiveStore = "course-archives";

const parse = <T>(raw: string | null, fallback: T): T => {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
};

export const loadCourses = (): Course[] => parse<Course[]>(localStorage.getItem(coursesKey), []);

/**
 * Blob URLs die with the page, so persisting them would leave a stored course
 * pointing at audio that can no longer play. Only the lesson data is kept; the
 * playable URLs are rebuilt from the archived ZIP on the next start.
 */
export const saveCourses = (courses: Course[]) => {
  const stored = courses.filter((course) => !course.isDemo).map((course) => {
    const copy: Course = { ...course };
    delete copy.audioUrl;
    delete copy.transcriptUrl;
    return copy;
  });
  localStorage.setItem(coursesKey, JSON.stringify(stored));
};

export const loadRecords = (): PracticeRecord[] => parse<PracticeRecord[]>(localStorage.getItem(recordsKey), []);
export const saveRecords = (records: PracticeRecord[]) => localStorage.setItem(recordsKey, JSON.stringify(records));

export const loadActiveCourseId = () => localStorage.getItem(activeKey) || "";
export const saveActiveCourseId = (episodeId: string) => localStorage.setItem(activeKey, episodeId);

export function upsertRecord(next: PracticeRecord): PracticeRecord[] {
  const current = loadRecords();
  const rest = current.filter((item) => !(item.episodeId === next.episodeId && item.sentenceId === next.sentenceId));
  const result = [...rest, next];
  saveRecords(result);
  return result;
}

export function removeRecordsFor(episodeId: string): PracticeRecord[] {
  const result = loadRecords().filter((item) => item.episodeId !== episodeId);
  saveRecords(result);
  return result;
}

const download = (name: string, content: BlobPart, type: string) => {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
};

export function exportLearningData() {
  const records = loadRecords();
  const escape = (value: string) => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);
  const csv = [
    "episode_id,sentence_id,difficulty,retest,updated_at",
    ...records.map((item) => [item.episodeId, item.sentenceId, item.difficulty || "", item.retest || "", item.updatedAt].map((value) => escape(String(value))).join(","))
  ].join("\r\n");
  download("clear-english-records.json", JSON.stringify(records, null, 2), "application/json");
  // Excel on a Chinese Windows reads UTF-8 CSV correctly only with a BOM.
  download("clear-english-records.csv", `${String.fromCharCode(0xFEFF)}${csv}`, "text/csv;charset=utf-8");
}

export const downloadBlob = (name: string, blob: Blob) => download(name, blob, blob.type || "application/octet-stream");

function archiveDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(archiveStore);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest | null): Promise<T | undefined> {
  const database = await archiveDatabase();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const transaction = database.transaction(archiveStore, mode);
      const request = run(transaction.objectStore(archiveStore));
      transaction.oncomplete = () => resolve(request ? (request.result as T) : undefined);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
}

/** Keyed by episode id so re-importing the same lesson replaces its archive. */
export const saveCourseArchive = (episodeId: string, file: File) =>
  withStore<void>("readwrite", (store) => store.put(file, episodeId));

export const deleteCourseArchive = (episodeId: string) =>
  withStore<void>("readwrite", (store) => store.delete(episodeId));

export async function loadCourseArchives(): Promise<File[]> {
  const files = await withStore<File[]>("readonly", (store) => store.getAll());
  return files ?? [];
}
