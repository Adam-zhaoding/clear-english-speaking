"""Clear English Speaking 备课流水线。

分成两步，中间留给 WorkBuddy 做语言判断：

    第一步  python make_lesson.py prepare --latest
            确定性工作：找期次、下载官方 MP3 与 Transcript PDF、抽正文、
            本地 Whisper 全文词级对齐，产出 draft-request.json

    （中间）WorkBuddy 读 draft-request.json，挑 3-5 句重点句，
            写翻译、词义、A/B/C 卡点，存成 draft.json

    第二步  python make_lesson.py build
            确定性工作：逐字校验选句是否真的来自官方 Transcript、
            匹配词级时间戳、渲染出可直接双击的单文件 HTML

脚本从不编造英文原文，Whisper 只用来给时间戳。

依赖：requests beautifulsoup4 pypdf faster-whisper
"""
from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import mimetypes
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
TEMPLATE = SKILL_ROOT / "assets" / "player-template.html"

LIST_URL = "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english"
DOWNLOAD_HOST = "downloads.bbc.co.uk/learningenglish/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClearEnglish/1.0"

# 定时备课看这一行判断「今天没有新一期」，不要改动它的措辞。
NOTHING_NEW = "NOTHING_NEW"

MIN_SENTENCES = 3
MAX_SENTENCES = 5
EDGE_PADDING = 0.12          # 句子首尾各留一点余量，避免切掉首音尾音
MIN_SIMILARITY = 0.90        # 对齐文本与官方文本的最低相似度
MIN_SENTENCE_SECONDS = 2.0
MAX_SENTENCE_SECONDS = 20.0


def default_courses_dir() -> Path:
    """课程默认落在用户「文档」目录下，Agent 不必向用户要路径。

    这个固定位置同时是定时备课的去重依据：每天醒来先扫这里，看最新一期
    是不是已经备过。换目录就等于失忆，会把同一期反复备一遍。
    """
    home = Path.home()
    for relative in ("Documents", "文档", "OneDrive/Documents", "OneDrive/文档"):
        candidate = home / relative
        if candidate.is_dir():
            return candidate / "ClearEnglish"
    return home / "ClearEnglish"


class PipelineError(Exception):
    """带失败码的中止，便于 Agent 按码给出修复动作。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- 文本规范化
def normalize(text: str) -> str:
    """统一引号、破折号、空白，供逐字校验使用。"""
    text = unicodedata.normalize("NFKC", text)
    for source, target in (("’", "'"), ("‘", "'"), ("“", '"'),
                           ("”", '"'), ("–", "-"), ("—", "-"),
                           (" ", " ")):
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", normalize(text).lower())


# --------------------------------------------------------------------------- 1. 选材
def http_get(url: str, binary: bool = False):
    import requests  # 延迟导入，缺依赖时报错更清楚

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
    response.raise_for_status()
    return response.content if binary else response.text


def already_built(courses_dir: Path, episode_id: str) -> Path | None:
    """这一期是否已经有成品课程页。产物命名是 <期次>_<标题 slug>.html。"""
    if not courses_dir.is_dir():
        return None
    return next(iter(sorted(courses_dir.glob(f"{episode_id}_*.html"))), None)


def list_episodes() -> list[tuple[str, str]]:
    """列表页上的期次，新的在前。返回 (期次号, 页面地址)，同一期只保留一次。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(http_get(LIST_URL), "html.parser")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = anchor["href"]
        if "6-minute-english" not in href:
            continue
        match = re.search(r"ep-?(\d{6})", href)
        if not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        found.append((match.group(1), urljoin(LIST_URL, href)))
    if not found:
        raise PipelineError("no_eligible_episode",
                            "在列表页上找不到期次链接，BBC 页面结构可能变了；改用 --url 指定一期。")
    return found


def find_latest_episode() -> str:
    return list_episodes()[0][1]


def find_unbuilt_episode(courses_dir: Path) -> tuple[str, Path | None]:
    """挑列表上第一期还没备过的。全都备过时返回 (最新一期地址, 它的成品路径)。

    用户每天练，BBC 每周才更新一期。只认最新一期的话，一周里有六天拿不到东西；
    往前找一期没练过的，才是这个工具该有的行为。
    """
    episodes = list_episodes()
    for episode_id, url in episodes:
        if already_built(courses_dir, episode_id) is None:
            return url, None
    newest_id, newest_url = episodes[0]
    return newest_url, already_built(courses_dir, newest_id)


def pick_transcript(candidates: list[str]) -> str:
    """PDF 甄别规则。文件名永远不能单独让一个 PDF 过关，它还要通过下游逐字校验。"""
    pool = [url for url in candidates if DOWNLOAD_HOST in url and url.lower().endswith(".pdf")]
    pool = [url for url in pool if "worksheet" not in url.lower()]
    if not pool:
        raise PipelineError("official_transcript_missing", "这一期没有可用的官方 Transcript PDF。")

    labelled = [url for url in pool if re.search(r"transcript_?\.pdf$", url.lower())]
    if labelled:
        return labelled[0]
    unique = list(dict.fromkeys(pool))
    if len(unique) == 1:
        return unique[0]
    raise PipelineError(
        "official_transcript_missing",
        f"有 {len(unique)} 个无标注的 PDF 候选，无法判断哪个是正式 Transcript：{unique}",
    )


@dataclass
class Episode:
    url: str
    episode_id: str
    title: str
    audio_url: str
    transcript_url: str


def parse_episode(page_url: str) -> Episode:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(http_get(page_url), "html.parser")
    links = [urljoin(page_url, anchor["href"]) for anchor in soup.select("a[href]")]

    audio = [url for url in links if DOWNLOAD_HOST in url and url.lower().endswith(".mp3")]
    if not audio:
        raise PipelineError("official_mp3_missing",
                            "官方页面上没有发现可下载的 MP3；不要从 transcript 文件名推断音频名。")
    audio_url = audio[0]

    transcript_url = pick_transcript(links)
    match = re.search(r"/(\d{6})_", audio_url)
    episode_id = match.group(1) if match else hashlib.sha1(audio_url.encode()).hexdigest()[:6]

    return Episode(page_url, episode_id, episode_title(soup, audio_url), audio_url, transcript_url)


GENERIC_TITLES = {"learning english", "bbc learning english", "6 minute english", "home"}


def episode_title(soup, audio_url: str) -> str:
    """页面 h1 常常是站点名，所以优先 og:title，最后从已确认的音频文件名回推。"""
    candidates = []
    for selector, attribute in (('meta[property="og:title"]', "content"),
                                ('meta[name="twitter:title"]', "content")):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            candidates.append(node[attribute])
    candidates += [node.get_text() for node in soup.select("h1, h2")]

    for raw in candidates:
        title = normalize(raw)
        # BBC 的 og:title 形如「BBC Learning English - 6 Minute English / Who does the housework?」
        if "/" in title:
            title = title.rsplit("/", 1)[-1]
        title = re.sub(r"^\s*(BBC\s+)?Learning English\s*[-–:|]\s*", "", title, flags=re.I)
        title = re.sub(r"^\s*6 Minute English\s*[-–:|]\s*", "", title, flags=re.I)
        title = re.sub(r"\s*[-–|]\s*BBC.*$", "", title).strip()
        if title and title.lower() not in GENERIC_TITLES and len(title) > 3:
            return title

    # 回退：从音频文件名回推。注意方向——音频是从页面上发现的，
    # 这里只是用它的名字反推标题，不是从文件名去猜音频地址。
    stem = Path(audio_url).stem
    stem = re.sub(r"^\d{6}_", "", stem)
    stem = re.sub(r"^6_minute_english_", "", stem)
    stem = re.sub(r"_?download_?$", "", stem)
    words = [part for part in stem.split("_") if part]
    return " ".join(word.capitalize() for word in words) or "6 Minute English"


# --------------------------------------------------------------------------- 2. Transcript
def extract_transcript(pdf_path: Path) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as error:  # noqa: BLE001
        raise PipelineError("official_transcript_missing", f"PDF 正文抽取失败：{error}") from error

    text = normalize("\n".join(pages))
    if len(text) < 400:
        raise PipelineError("official_transcript_missing",
                            f"抽取到的正文只有 {len(text)} 字，明显不是完整 Transcript。")
    return text


# --------------------------------------------------------------------------- 3. 对齐
@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float = 1.0


@dataclass
class Alignment:
    words: list[Word] = field(default_factory=list)
    model_name: str = "base.en"
    duration: float = 0.0


def transcribe(audio_path: Path, model_name: str = "base.en") -> Alignment:
    from faster_whisper import WhisperModel

    log(f"  本地 Whisper（{model_name}）对齐中，一集 6 分钟大约 1 分钟…")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), word_timestamps=True, language="en")

    words: list[Word] = []
    for segment in segments:
        for word in segment.words or []:
            token = word.word.strip()
            if token:
                words.append(Word(token, float(word.start), float(word.end),
                                  float(getattr(word, "probability", 1.0))))
    if not words:
        raise PipelineError("alignment_low_confidence", "Whisper 没有产出任何词级时间戳。")
    return Alignment(words, model_name, float(info.duration))


def locate(sentence: str, alignment: Alignment) -> dict:
    """在词序列里找出这句话对应的时间段。找不到够像的就明确报错，不硬凑。"""
    target = tokenize(sentence)
    if not target:
        raise PipelineError("sentence_not_in_official_transcript", "空句子。")

    pool = [tokenize(word.text) for word in alignment.words]
    flat = [token[0] if token else "" for token in pool]

    best = {"score": 0.0, "start": -1, "end": -1}
    span = len(target)
    first = target[0]
    for index, token in enumerate(flat):
        if token != first and difflib.SequenceMatcher(None, token, first).ratio() < 0.8:
            continue
        for width in (span - 2, span - 1, span, span + 1, span + 2):
            if width < 1 or index + width > len(flat):
                continue
            window = flat[index:index + width]
            score = difflib.SequenceMatcher(None, window, target).ratio()
            if score > best["score"]:
                best = {"score": score, "start": index, "end": index + width - 1}

    if best["score"] < MIN_SIMILARITY:
        raise PipelineError(
            "alignment_low_confidence",
            f"这一句在音频里只匹配到 {best['score']:.2f} 的相似度，低于 {MIN_SIMILARITY}：{sentence[:60]}…",
        )

    head = alignment.words[best["start"]]
    tail = alignment.words[best["end"]]
    start = max(0.0, head.start - EDGE_PADDING)
    end = min(alignment.duration or tail.end + EDGE_PADDING, tail.end + EDGE_PADDING)
    length = end - start
    if length < MIN_SENTENCE_SECONDS or length > MAX_SENTENCE_SECONDS:
        raise PipelineError(
            "invalid_sentence_timing",
            f"这一句时长 {length:.1f}s，超出 {MIN_SENTENCE_SECONDS}-{MAX_SENTENCE_SECONDS}s：{sentence[:60]}…",
        )

    covered = alignment.words[best["start"]:best["end"] + 1]
    probability = sum(word.probability for word in covered) / max(len(covered), 1)
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "text_similarity": round(best["score"], 4),
        "average_probability": round(probability, 4),
        "word_start_index": best["start"],
        "word_end_index": best["end"],
        "score": round((best["score"] + probability) / 2, 6),
    }


# --------------------------------------------------------------------------- 4. 渲染
def render(lesson: dict, audio_path: Path, output: Path, embed: bool = True) -> Path:
    if not TEMPLATE.exists():
        raise PipelineError("needs_source_validation", f"找不到播放器模板：{TEMPLATE}")

    template = TEMPLATE.read_text(encoding="utf-8")
    if embed:
        mime = mimetypes.guess_type(audio_path.name)[0] or "audio/mpeg"
        encoded = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        source = f"data:{mime};base64,{encoded}"
    else:
        source = lesson["episode"]["audio_url"]

    html = (template
            .replace("__LESSON_JSON__", json.dumps(lesson, ensure_ascii=False))
            .replace("__AUDIO_SRC__", source)
            .replace("__TITLE__", lesson["episode"]["title"]))

    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output)          # 原子写：中断不留半成品
    return output


# --------------------------------------------------------------------------- prepare
def command_prepare(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    log("第一步 · 备课准备")
    # 不给 --courses 也照查默认课程目录，免得漏给参数就退化成每天重备。
    courses_dir = Path(args.courses).resolve() if args.courses else default_courses_dir()

    if args.url:
        page_url = args.url
    else:
        # 用户每天练，BBC 每周才更新一期。只盯最新一期的话，一周里有六天
        # 拿不到新东西，所以往前找第一期还没备过的。
        page_url, exhausted = find_unbuilt_episode(courses_dir)
        if exhausted is not None:
            log(f"  列表上的期次都已经备过了，最近一期：{exhausted.name}")
            log(f"{NOTHING_NEW}")
            return
    log(f"  期次页面：{page_url}")

    episode = parse_episode(page_url)
    log(f"  标题：{episode.title}（{episode.episode_id}）")

    # --url 指定的一期也要挡一道，免得手动重跑时又备一遍同样的内容。
    # 挡在下载 7MB 音频、跑一分钟 Whisper 之前。
    built = already_built(courses_dir, episode.episode_id)
    if built:
        log(f"  这一期已经备过了：{built.name}")
        log(f"{NOTHING_NEW} {episode.episode_id}")
        return

    audio_path = workspace / f"{episode.episode_id}.mp3"
    pdf_path = workspace / f"{episode.episode_id}.pdf"
    if not audio_path.exists():
        log("  下载官方音频…")
        audio_path.write_bytes(http_get(episode.audio_url, binary=True))
    if not pdf_path.exists():
        log("  下载官方 Transcript…")
        pdf_path.write_bytes(http_get(episode.transcript_url, binary=True))

    transcript = extract_transcript(pdf_path)
    log(f"  Transcript 正文 {len(transcript)} 字")

    alignment = transcribe(audio_path, args.model)
    log(f"  词级时间戳 {len(alignment.words)} 个，音频 {alignment.duration:.0f}s")

    request = {
        "schemaVersion": 1,
        "episode": {
            "id": episode.episode_id,
            "title": episode.title,
            "bbc_page_url": episode.url,
            "audio_url": episode.audio_url,
            "transcript_pdf_url": episode.transcript_url,
            "duration_seconds": round(alignment.duration, 2),
        },
        "audio_file": audio_path.name,
        "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        "model_name": alignment.model_name,
        "transcript_text": transcript,
        "instruction": (
            f"从 transcript_text 里挑 {MIN_SENTENCES}-{MAX_SENTENCES} 句重点句，"
            "英文必须逐字照抄，另写 translation_zh、glossary、diagnosis_tags(A/B/C) "
            "和 listening_focus，存成 draft.json。"
        ),
    }
    target = workspace / "draft-request.json"
    target.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"\n准备完成 → {target}")
    log("下一步：让 WorkBuddy 读这个文件挑句子、写翻译，存成 draft.json，然后运行 build。")


# --------------------------------------------------------------------------- build
def command_build(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    request_path = workspace / "draft-request.json"
    draft_path = workspace / "draft.json"
    for path in (request_path, draft_path):
        if not path.exists():
            raise PipelineError("needs_source_validation", f"缺少 {path.name}，先跑 prepare 并让 Agent 写好草案。")

    request = json.loads(request_path.read_text(encoding="utf-8"))
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    transcript = normalize(request["transcript_text"])
    audio_path = workspace / request["audio_file"]

    raw = draft.get("sentences") or []
    log(f"第二步 · 校验并渲染（草案给了 {len(raw)} 句）")

    # 逐字校验：英文必须真的来自官方 Transcript
    verified = []
    for index, item in enumerate(raw):
        text = normalize(str(item.get("text", "")))
        if not text:
            log(f"  × 第 {index + 1} 句是空的，丢弃")
            continue
        if text not in transcript:
            log(f"  × 第 {index + 1} 句不在官方 Transcript 里，丢弃：{text[:56]}…")
            continue
        verified.append((item, text))
    log(f"  逐字校验通过 {len(verified)} 句")

    alignment = None
    sentences = []
    for item, text in verified:
        if len(sentences) >= MAX_SENTENCES:
            break
        if alignment is None:
            alignment = transcribe(audio_path, request.get("model_name", "base.en"))
        try:
            timing = locate(text, alignment)
        except PipelineError as error:
            log(f"  × {error.code}：{text[:56]}…")
            continue
        sentences.append({
            "id": f"s{len(sentences) + 1}",
            "text": text,
            "translation_zh": str(item.get("translation_zh", "")).strip(),
            "glossary": [
                {"surface": str(entry.get("surface", "")).strip(),
                 "meaning": str(entry.get("meaning", "")).strip()}
                for entry in (item.get("glossary") or [])
                if str(entry.get("surface", "")).strip()
            ],
            "diagnosis_tags": [str(tag).upper() for tag in (item.get("diagnosis_tags") or [])
                               if str(tag).upper() in {"A", "B", "C"}],
            "listening_focus": str(item.get("listening_focus", "")).strip(),
            **timing,
        })

    # 按音频时间排序。选句顺序由 AI 决定，但练习要跟着音频走；
    # 桌面版导入课程包时也要求句子升序不重叠，乱序会被判 invalid_sentence_timing。
    sentences.sort(key=lambda row: row["start"])
    for position, row in enumerate(sentences, start=1):
        row["id"] = f"s{position}"

    # 句子层失败不让整集报废：凑不齐就退回只可收听
    mode = "full" if len(sentences) >= MIN_SENTENCES else "listen_only"
    if mode == "listen_only":
        log(f"  ! 只凑齐 {len(sentences)} 句（需要 {MIN_SENTENCES} 句），"
            "退回「只可收听」，整集音频照样能播。")
        sentences = []
    else:
        log(f"  对齐成功 {len(sentences)} 句")

    lesson = {
        "version": 1,
        "mode": mode,
        "generated_at": args.now or "",
        "episode": request["episode"],
        "shadow": {
            "algorithm_version": "bbc-shadow-align-v2",
            "model_name": request.get("model_name", "base.en"),
            "audio_sha256": request["audio_sha256"],
            "sentences": sentences,
        },
    }

    slug = re.sub(r"[^a-z0-9]+", "-", request["episode"]["title"].lower()).strip("-")[:48]
    stem = f"{request['episode']['id']}_{slug or 'lesson'}"
    output_dir = Path(args.output).resolve() if args.output else default_courses_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / f"{stem}.lesson.json").write_text(
        json.dumps(lesson, ensure_ascii=False, indent=2), encoding="utf-8")
    html = render(lesson, audio_path, output_dir / f"{stem}.html", embed=not args.no_embed)

    size = html.stat().st_size / 1024 / 1024
    log(f"\n课程已生成 → {html}")
    log(f"  模式 {mode} · {len(sentences)} 句训练 · {size:.1f} MB")
    log("  双击这个文件就能开始练：播放、变速、循环、跟读、录音全都可用。")
    log("  第一次点录音时浏览器会问一次麦克风权限，允许一次即可，之后每句都不再打断。")


# --------------------------------------------------------------------------- CLI
def main() -> None:
    parser = argparse.ArgumentParser(description="Clear English Speaking 备课流水线")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="下载官方素材并做全文对齐")
    prepare.add_argument("--url", help="指定 BBC 6 Minute English 期次页；不给就取最新一期")
    prepare.add_argument("--latest", action="store_true", help="取最新一期（默认行为）")
    prepare.add_argument("--workspace", default="lesson-work", help="工作目录")
    prepare.add_argument("--model", default="base.en", help="Whisper 模型，精度不够可换 small.en")
    prepare.add_argument("--courses", help="课程输出目录，默认「文档 / ClearEnglish」。"
                                           "开跑前先查这一期是否已备过，"
                                           f"备过则打印 {NOTHING_NEW} 并直接结束")
    prepare.set_defaults(handler=command_prepare)

    build = sub.add_parser("build", help="校验草案并渲染成单文件 HTML")
    build.add_argument("--workspace", default="lesson-work", help="工作目录")
    build.add_argument("--output", help="课程输出目录，默认「文档 / ClearEnglish」；"
                                        "只有用户主动要求换地方时才给")
    build.add_argument("--no-embed", action="store_true", help="不内嵌音频，改用官方远程地址（文件小但要联网）")
    build.add_argument("--now", help="写进课程的生成时间")
    build.set_defaults(handler=command_build)

    args = parser.parse_args()
    try:
        args.handler(args)
    except PipelineError as error:
        log(f"\n[{error.code}] {error.message}")
        sys.exit(2)
    except ImportError as error:
        log(f"\n缺少依赖：{error}")
        log("装一下：pip install requests beautifulsoup4 pypdf faster-whisper")
        sys.exit(3)


if __name__ == "__main__":
    main()
