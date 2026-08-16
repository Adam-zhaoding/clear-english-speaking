import type { Course } from "./types";

const DEMO_DURATION = 100;

const lines: [string, string, string, string, string[]][] = [
  ["Small, repeated practice can make difficult sounds feel familiar.", "小而重复的练习，能让困难的语音逐渐变得熟悉。", "先抓住 small, repeated practice 这个词块。", "说出练习为什么要重复。", ["词块", "重音"]],
  ["You do not need to understand every word on the first listen.", "第一遍听不需要听懂每一个词。", "注意 do not 和 to 的弱读。", "说出第一遍听的目标。", ["弱读"]],
  ["Try to notice one change in the speaker's rhythm.", "试着注意说话者节奏中的一个变化。", "把 notice one 当成一个整体听。", "今天你要注意哪一个语音变化？", ["节奏"]],
  ["Then play the sentence again at its natural speed.", "然后以自然语速再播放这句话。", "留意 then play 的衔接。", "回测时应该使用什么语速？", ["连读"]],
  ["A clear idea is more useful than a perfect score.", "一个清晰的想法，比一个完美分数更有用。", "重音落在 clear idea 和 perfect score。", "这里比较的是哪两件事？", ["重音"]]
];

const spans = lines.map((_, index) => [8 + index * 18, 16 + index * 18] as const);

/**
 * A first-run user has no BBC material yet, so the demo course must still make
 * a sound. Generating the placeholder track here keeps the repository free of
 * binary media while proving that play, seek and speed controls really work.
 * Quiet chime notes separated by silence — a tone held across the whole span
 * just sounds like the player is broken.
 */
function demoAudioUrl(): string {
  const rate = 8000;
  const total = Math.round(DEMO_DURATION * rate);
  const body = new Int16Array(total);
  const note = 0.22;
  const gap = 0.55;
  const amplitude = 2600;
  spans.forEach(([start, end], index) => {
    const base = 440 * 2 ** (index / 12);
    let onset = start;
    let step = 0;
    while (onset + note <= Math.min(end, DEMO_DURATION)) {
      const ratio = step % 3 === 1 ? 1.25 : step % 3 === 2 ? 1.5 : 1;
      const frequency = base * ratio;
      const first = Math.round(onset * rate);
      const length = Math.min(Math.round(note * rate), total - first);
      for (let offset = 0; offset < length; offset += 1) {
        const envelope = (1 - offset / length) ** 2;
        body[first + offset] = Math.round(amplitude * envelope * Math.sin((2 * Math.PI * frequency * offset) / rate));
      }
      onset += gap;
      step += 1;
    }
  });
  const buffer = new ArrayBuffer(44 + body.byteLength);
  const view = new DataView(buffer);
  const ascii = (offset: number, value: string) => [...value].forEach((character, index) => view.setUint8(offset + index, character.charCodeAt(0)));
  ascii(0, "RIFF");
  view.setUint32(4, 36 + body.byteLength, true);
  ascii(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, body.byteLength, true);
  new Int16Array(buffer, 44).set(body);
  return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
}

let cachedAudio = "";

export const DEMO_EPISODE_ID = "demo-local";

export function demoCourse(): Course {
  if (!cachedAudio) cachedAudio = demoAudioUrl();
  return {
    schema_version: 1,
    episode_id: DEMO_EPISODE_ID,
    title: "演示课 · 先把播放器跑通",
    source: { bbc_page_url: "", transcript_url: "" },
    audio: { file: "audio.wav", duration_seconds: DEMO_DURATION },
    transcript: { file: "transcript.pdf" },
    importedAt: new Date().toISOString(),
    audioUrl: cachedAudio,
    isDemo: true,
    sentences: lines.map(([text, translation, focus, check, tags], index) => ({
      id: `s${index + 1}`,
      start: spans[index][0],
      end: spans[index][1],
      text,
      translation_zh: translation,
      glossary: [],
      diagnosis_tags: tags,
      listening_focus: focus,
      comprehension_check: check
    }))
  };
}
