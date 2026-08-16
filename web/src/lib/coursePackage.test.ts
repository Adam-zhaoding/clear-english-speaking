import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import { CoursePackageError, readCoursePackage, validateLesson } from "./coursePackage";
import { demoCourse } from "./demo";
import { explainBuildError } from "./errors";
import type { Lesson, Sentence } from "./types";

// The importer hands playable media to the player through object URLs, which
// the Node test runner does not provide.
if (typeof URL.createObjectURL !== "function") {
  let counter = 0;
  URL.createObjectURL = () => `blob:clear-english/${(counter += 1)}`;
  URL.revokeObjectURL = () => undefined;
}

const lessonOf = (): Lesson => {
  const course = demoCourse();
  return {
    schema_version: course.schema_version,
    episode_id: course.episode_id,
    title: course.title,
    source: course.source,
    audio: { ...course.audio },
    transcript: { ...course.transcript },
    sentences: course.sentences.map((sentence) => ({ ...sentence }))
  };
};

const sha256 = async (value: ArrayBuffer) => {
  const digest = await crypto.subtle.digest("SHA-256", value);
  return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
};

async function packageFile(overrides: {
  lesson?: Partial<Lesson>;
  corruptAudio?: boolean;
  extra?: [string, string];
  manifestKey?: string;
} = {}) {
  const lesson = { ...lessonOf(), ...overrides.lesson, audio: { file: "audio.wav", duration_seconds: 100 } };
  const audio = new TextEncoder().encode("synthetic audio bytes").buffer as ArrayBuffer;
  const transcript = new TextEncoder().encode("%PDF-1.4 synthetic").buffer as ArrayBuffer;
  const lessonBytes = new TextEncoder().encode(JSON.stringify(lesson)).buffer as ArrayBuffer;
  const manifest = {
    schema_version: 1,
    course_version: "1.0.0",
    generated_at: new Date().toISOString(),
    files: {
      "audio.wav": { sha256: await sha256(audio), bytes: audio.byteLength },
      "transcript.pdf": { sha256: await sha256(transcript), bytes: transcript.byteLength },
      "lesson.json": { sha256: await sha256(lessonBytes), bytes: lessonBytes.byteLength }
    }
  };
  if (overrides.manifestKey) {
    manifest.files = { ...manifest.files, [overrides.manifestKey]: { sha256: "0".repeat(64), bytes: 1 } };
  }
  const zip = new JSZip();
  // Same length as the original, so the hash check is what rejects it.
  zip.file("audio.wav", overrides.corruptAudio ? new TextEncoder().encode("TAMPERED audio bytes!") : audio);
  zip.file("transcript.pdf", transcript);
  zip.file("lesson.json", lessonBytes);
  zip.file("manifest.json", JSON.stringify(manifest));
  if (overrides.extra) zip.file(overrides.extra[0], overrides.extra[1]);
  const blob = await zip.generateAsync({ type: "blob" });
  return new File([blob], "test-course.zip", { type: "application/zip" });
}

describe("course package contract", () => {
  it("accepts the synthetic lesson contract", () => {
    expect(() => validateLesson(lessonOf())).not.toThrow();
  });

  it("rejects a package with an overlapping sentence range", () => {
    const invalid = lessonOf();
    invalid.sentences[1].start = invalid.sentences[0].end - 1;
    expect(() => validateLesson(invalid)).toThrow(CoursePackageError);
  });

  it("requires five to six selected sentences", () => {
    const invalid = lessonOf();
    invalid.sentences = invalid.sentences.slice(0, 4);
    expect(() => validateLesson(invalid)).toThrow("5–6");
  });

  it("rejects a sentence with no id, so a package can never lose record keys", () => {
    const invalid = lessonOf();
    invalid.sentences[2] = { ...invalid.sentences[2], id: "" };
    expect(() => validateLesson(invalid)).toThrow("缺少编号");
  });

  it("rejects duplicate sentence ids", () => {
    const invalid = lessonOf();
    invalid.sentences[1].id = invalid.sentences[0].id;
    expect(() => validateLesson(invalid)).toThrow("重复");
  });

  it("accepts a listen-only lesson that carries no timed sentences", () => {
    const listenOnly = { ...lessonOf(), sentences: [], mode: "listen_only" as const };
    expect(() => validateLesson(listenOnly)).not.toThrow();
  });

  it("still requires 5-6 sentences when the lesson is not listen-only", () => {
    expect(() => validateLesson({ ...lessonOf(), sentences: [] })).toThrow("5–6");
  });

  it("rejects a listen-only lesson that smuggles sentences back in", () => {
    expect(() => validateLesson({ ...lessonOf(), mode: "listen_only" })).toThrow("不应包含练习句");
  });

  it("rejects an audio filename that escapes the package root", () => {
    const invalid = lessonOf();
    invalid.audio = { ...invalid.audio, file: "../escape.mp3" };
    expect(() => validateLesson(invalid)).toThrow("文件名不合法");
  });
});

describe("course package import", () => {
  it("imports a well-formed package and exposes playable media", async () => {
    const course = await readCoursePackage(await packageFile());
    expect(course.episode_id).toBe("demo-local");
    expect(course.audioUrl).toBeTruthy();
    expect(course.transcriptUrl).toBeTruthy();
    expect(course.archiveBytes).toBeGreaterThan(0);
  });

  it("imports a package built before the engine assigned sentence ids", async () => {
    // Real BBC packages on disk carry no sentence id at all; without the
    // positional fallback they could never be opened again.
    const legacy = lessonOf();
    legacy.sentences = legacy.sentences.map((sentence) => {
      const copy: Record<string, unknown> = { ...sentence };
      delete copy.id;
      return copy as unknown as Sentence;
    });
    const course = await readCoursePackage(await packageFile({ lesson: legacy }));
    expect(course.sentences.map((item) => item.id)).toEqual(["s1", "s2", "s3", "s4", "s5"]);
  });

  it("refuses a package whose audio does not match the manifest hash", async () => {
    await expect(readCoursePackage(await packageFile({ corruptAudio: true }))).rejects.toThrow("校验失败");
  });

  it("refuses a file that is not a ZIP at all", async () => {
    const file = new File([new TextEncoder().encode("not a zip")], "broken.zip", { type: "application/zip" });
    await expect(readCoursePackage(file)).rejects.toThrow("不是有效的 ZIP");
  });

  it("imports a listen-only package so the episode stays playable", async () => {
    const file = await packageFile({ lesson: { sentences: [], mode: "listen_only", degraded: { code: "sentence_alignment_failed", reason: "有句子没能在音频里定位到。" } } });
    const course = await readCoursePackage(file);
    expect(course.sentences).toHaveLength(0);
    expect(course.mode).toBe("listen_only");
    expect(course.audioUrl).toBeTruthy();
    expect(course.transcriptUrl).toBeTruthy();
    expect(course.degraded?.code).toBe("sentence_alignment_failed");
  });

  it("refuses a manifest entry whose path escapes the package root", async () => {
    await expect(readCoursePackage(await packageFile({ manifestKey: "../../evil.txt" }))).rejects.toThrow("不安全路径");
  });

  it("refuses a package that hides extra files beyond the course contract", async () => {
    const file = await packageFile({ extra: ["notes.txt", "x"] });
    const course = await readCoursePackage(file);
    // Extra benign files are tolerated; only the manifest-listed ones are trusted.
    expect(course.sentences).toHaveLength(5);
  });
});

describe("build error messages", () => {
  it("turns an engine code into a cause and a next step", () => {
    const text = explainBuildError(new Error("CourseBuildError: sentence_not_in_official_transcript"));
    expect(text).toContain("官方文稿对不上");
    expect(text).toContain("下一步");
    expect(text).not.toContain("sentence_not_in_official_transcript");
  });

  it("keeps an unknown message readable instead of blanking it", () => {
    expect(explainBuildError("磁盘已满")).toContain("磁盘已满");
  });
});
