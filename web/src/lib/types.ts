export type Difficulty = "A" | "B" | "C";

export interface Sentence {
  id: string;
  start: number;
  end: number;
  text: string;
  translation_zh: string;
  glossary: { surface: string; lemma: string; gloss_zh: string }[];
  diagnosis_tags: string[];
  listening_focus: string;
  comprehension_check: string;
}

export interface Lesson {
  schema_version: 1;
  episode_id: string;
  title: string;
  source: { bbc_page_url: string; transcript_url: string };
  audio: { file: string; duration_seconds: number };
  transcript: { file: string };
  sentences: Sentence[];
  /**
   * "listen_only" means per-sentence training could not be produced for this
   * episode. The official audio and transcript are still verified and usable,
   * so the lesson stays playable end to end instead of being thrown away.
   */
  mode?: "full" | "listen_only";
  degraded?: { code: string; reason: string };
}

export interface Manifest {
  schema_version: 1;
  course_version: string;
  generated_at: string;
  files: Record<string, { sha256: string; bytes: number }>;
}

export interface Course extends Lesson {
  importedAt: string;
  audioUrl?: string;
  transcriptUrl?: string;
  /** True for the built-in placeholder course, which is never stored or deleted. */
  isDemo?: boolean;
  /** Bytes of the imported ZIP, shown in the course library. */
  archiveBytes?: number;
}

export interface PracticeRecord {
  episodeId: string;
  sentenceId: string;
  difficulty?: Difficulty;
  retest?: "pass" | "not_yet";
  updatedAt: string;
}

export interface AgentStatus {
  connected: boolean;
  nextRun?: string;
  lastResult?: string;
  courseDirectory?: string;
  needsPair?: boolean;
}
