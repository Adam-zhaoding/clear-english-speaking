from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .course import CourseBuildError

PDF_RE = re.compile(r"https://downloads\.bbc\.co\.uk/learningenglish/[^\"'\s<>]+?\.pdf(?:\?[^\"'\s<>]*)?", re.I)
MP3_RE = re.compile(r"https://[^\"'\s]+?\.mp3(?:\?[^\"'\s]*)?", re.I)
EPISODE_RE = re.compile(r"(?:ep-)?(\d{6})(?:[/?#]|$)", re.I)


@dataclass(frozen=True)
class OfficialAssets:
    episode_id: str
    page_url: str
    mp3_url: str
    transcript_url: str


def _transcript_url(html: str) -> str | None:
    """Select a BBC transcript PDF without ever accepting a worksheet.

    BBC has used both ``*_transcript.pdf`` and an unlabelled main PDF for the
    same 6 Minute English transcript.  Prefer the explicit name; otherwise an
    unlabelled PDF is safe only when it is the sole non-worksheet BBC PDF.
    """
    urls = list(dict.fromkeys(match.group(0) for match in PDF_RE.finditer(html)))
    candidates = [url for url in urls if "worksheet" not in url.lower()]
    explicit = [url for url in candidates if re.search(r"_transcript_?\.pdf(?:\?|$)", url, re.I)]
    if explicit:
        return explicit[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def fetch_official_page(page_url: str) -> str:
    """Read a BBC page, turning transport failures into a course error code.

    Network problems are the most common reason a build stops on a normal
    machine, so they must never surface as a Python traceback.
    """
    request = urllib.request.Request(page_url, headers={"User-Agent": "ClearEnglish/0.1 (personal learning tool)"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as error:
        raise CourseBuildError("bbc_page_not_found" if error.code == 404 else "bbc_page_unreachable") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise CourseBuildError("bbc_page_unreachable") from error


def discover_official_assets(page_url: str) -> OfficialAssets:
    if not re.match(r"^https://www\.bbc\.(co\.uk|com)/learningenglish/", page_url, re.I):
        raise CourseBuildError("non_official_bbc_page")
    html = fetch_official_page(page_url)
    transcript = _transcript_url(html); mp3 = MP3_RE.search(html); episode = EPISODE_RE.search(page_url)
    if not transcript: raise CourseBuildError("official_transcript_missing")
    if not mp3: raise CourseBuildError("official_mp3_missing")
    if not episode: raise CourseBuildError("episode_id_missing")
    return OfficialAssets(episode.group(1), page_url, mp3.group(0), transcript)
