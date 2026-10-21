#!/usr/bin/env python3
"""Turn an SRT into a concise content plan and downloadable media collection."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STOPWORDS = set("""a an the and or but if so to of in on at for from by with as is are was were be been being it its this that these those
they them their he she we you i me my our your what which who how why when where do does did not no yes can could would should will
than then there here into about after before over under more most very just only even also all any each other such some one two three
have has had having because while through between up down out back every another both much many much few""".split())
TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
SRT_BLOCK_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})[^\r\n]*\r?\n(?P<text>.*?)(?=\r?\n\s*\r?\n|\Z)",
    re.S,
)


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Scene:
    start: float
    end: float
    text: str
    query: str


def timestamp(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def read_srt(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    cues = []
    for match in SRT_BLOCK_RE.finditer(raw):
        text = html.unescape(TAG_RE.sub("", match.group("text")))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cues.append(Cue(timestamp(match.group("start")), timestamp(match.group("end")), text))
    if not cues:
        raise ValueError("Không đọc được cue nào trong file SRT. Hãy kiểm tra định dạng phụ đề.")
    return cues


def clean_words(text: str) -> list[str]:
    return [w.lower().strip("'-") for w in WORD_RE.findall(text) if w.lower() not in STOPWORDS]


def query_for(text: str, limit: int = 7) -> str:
    words = clean_words(text)
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    # Preserve narrative order while prioritizing words repeated within a scene.
    chosen = sorted(dict.fromkeys(words), key=lambda w: (-counts[w], words.index(w)))[:limit]
    return " ".join(chosen) if chosen else "historical documentary"


def make_scenes(cues: list[Cue], window: float = 20) -> list[Scene]:
    scenes: list[Scene] = []
    bucket: list[Cue] = []
    bucket_end = cues[0].start + window
    for cue in cues:
        if bucket and cue.start >= bucket_end:
            text = " ".join(c.text for c in bucket)
            scenes.append(Scene(bucket[0].start, bucket[-1].end, text, query_for(text)))
            bucket = []
            bucket_end = cue.start + window
        bucket.append(cue)
    if bucket:
        text = " ".join(c.text for c in bucket)
        scenes.append(Scene(bucket[0].start, bucket[-1].end, text, query_for(text)))
    return scenes


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def estimate(duration: float, image_seconds: float, video_seconds: float, video_ratio: float) -> tuple[int, int]:
    # Images alone must cover the complete timeline; videos are bonus footage.
    # A long downloaded video may later be cut into several short editing inserts.
    images = math.ceil(duration / image_seconds)
    videos = math.floor(images * video_ratio)
    return images, videos


def load_dotenv(folder: Path) -> None:
    envfile = folder / ".env"
    if not envfile.exists():
        return
    for line in envfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def save_plan(path: Path, cues: list[Cue], scenes: list[Scene], duration: float,
              image_count: int, video_count: int, source: str,
              image_seconds: float, video_seconds: float, video_ratio: float) -> None:
    all_text = " ".join(c.text for c in cues)
    summary = (
        f"# Tóm tắt nội dung: {source}\n\n"
        f"- **Thời lượng phụ đề:** {fmt_time(duration)}\n"
        f"- **Số đoạn phụ đề:** {len(cues)}\n"
        f"- **Ý chính:** {query_for(all_text, 12)}\n\n"
        "## Tóm tắt\n\n"
        "Phụ đề kể lại diễn biến theo trình tự thời gian. Chủ đề và các cụm từ dưới đây được trích tự động từ lời thoại để hỗ trợ biên tập và tìm tư liệu; hãy rà soát lại bản tóm tắt trước khi sử dụng chính thức.\n\n"
        "## Các phần nội dung chính\n\n"
    )
    lines = [summary]
    for i, scene in enumerate(scenes, 1):
        excerpt = scene.text[:260] + ("…" if len(scene.text) > 260 else "")
        lines.append(f"{i}. **{fmt_time(scene.start)}–{fmt_time(scene.end)}** — {excerpt}\n   - Từ khóa tìm tư liệu: `{scene.query}`\n")
    lines.append(
        f"\n## Kế hoạch tư liệu\n\n- Ảnh mục tiêu: **{image_count}** để tự phủ toàn bộ thời lượng, mỗi ảnh khoảng {image_seconds:g} giây.\n"
        f"- Clip mục tiêu: **{video_count}** (tối đa khoảng {video_ratio:.0%} số ảnh). Clip dài có thể cắt thành nhiều đoạn {image_seconds:g} giây; các đoạn này có thể thay ảnh khi dựng, không trừ khỏi số ảnh dự phòng.\n"
    )
    path.write_text("".join(lines), encoding="utf-8")
    with (path.parent / "01_scene_plan.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["scene", "start", "end", "search_query", "caption_excerpt"])
        for i, scene in enumerate(scenes, 1):
            writer.writerow([i, fmt_time(scene.start), fmt_time(scene.end), scene.query, scene.text[:500]])


def request_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "SRTMediaPlanner/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"API trả lỗi HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Không kết nối được API: {exc}") from exc
    return {}


def search_pexels(kind: str, query: str, key: str, per_page: int) -> list[dict[str, Any]]:
    endpoint = "photos" if kind == "image" else "videos"
    url = f"https://api.pexels.com/v1/{endpoint}/search?" + urllib.parse.urlencode({"query": query, "per_page": per_page})
    data = request_json(url, {"Authorization": key, "User-Agent": "SRTMediaPlanner/1.0"})
    results = []
    if kind == "image":
        for item in data.get("photos", []):
            results.append({"id": item["id"], "url": item.get("src", {}).get("large2x") or item.get("src", {}).get("large"),
                            "page": item.get("url", ""), "creator": item.get("photographer", ""), "source": "Pexels", "type": "jpg"})
    else:
        for item in data.get("videos", []):
            files = sorted(item.get("video_files", []), key=lambda v: (v.get("width", 0), v.get("height", 0)))
            files = [v for v in files if v.get("file_type") == "video/mp4" and v.get("link")]
            if files:
                selected = next((v for v in files if v.get("width", 0) >= 1280), files[-1])
                results.append({"id": item["id"], "url": selected["link"], "page": item.get("url", ""),
                                "creator": item.get("user", {}).get("name", ""), "source": "Pexels", "type": "mp4"})
    return results


def search_pixabay(kind: str, query: str, key: str, per_page: int) -> list[dict[str, Any]]:
    endpoint = "images" if kind == "image" else "videos"
    params = {"key": key, "q": query, "per_page": min(per_page, 200), "safesearch": "true"}
    if kind == "image":
        params["image_type"] = "photo"
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)
    else:
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(params)
    data = request_json(url)
    results = []
    for item in data.get("hits", []):
        if kind == "image":
            download = item.get("largeImageURL") or item.get("webformatURL")
            ext = Path(urllib.parse.urlparse(download).path).suffix.lstrip(".") or "jpg"
        else:
            files = item.get("videos", {})
            selected = files.get("large") or files.get("medium") or files.get("small")
            if not selected:
                continue
            download = selected.get("url")
            ext = "mp4"
        if download:
            results.append({"id": item.get("id"), "url": download,
                            "page": item.get("pageURL", ""), "creator": item.get("user", ""),
                            "source": "Pixabay", "type": ext})
    return results


def download(url: str, destination: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "SRTMediaPlanner/1.0"})
    with urllib.request.urlopen(req, timeout=90) as response, destination.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Tải về file rỗng")


def collect(kind: str, target: int, scenes: list[Scene], folder: Path, provider: str,
            key: str, max_per_query: int) -> list[dict[str, str]]:
    folder.mkdir(parents=True, exist_ok=True)
    search = search_pexels if provider == "Pexels" else search_pixabay
    seen: set[str] = set()
    records: list[dict[str, str]] = []
    queries = list(dict.fromkeys(scene.query for scene in scenes))
    # Round-robin queries keeps the downloaded collection relevant across the whole narration.
    for query in queries:
        if len(records) >= target:
            break
        try:
            candidates = search(kind, query, key, min(max_per_query, 30))
        except Exception as exc:
            print(f"[cảnh báo] Tìm {kind} '{query}' thất bại: {exc}", file=sys.stderr)
            continue
        for item in candidates:
            identity = str(item.get("id") or item.get("url"))
            if identity in seen or not item.get("url"):
                continue
            seen.add(identity)
            index = len(records) + 1
            dest = folder / f"{kind}_{index:03d}_{item['id']}.{item['type']}"
            try:
                download(item["url"], dest)
            except Exception as exc:
                print(f"[cảnh báo] Không tải được {item.get('page') or item['url']}: {exc}", file=sys.stderr)
                dest.unlink(missing_ok=True)
                continue
            records.append({"kind": kind, "file": str(dest.relative_to(folder.parent)), "query": query,
                            "source": item["source"], "creator": str(item.get("creator", "")),
                            "source_page": str(item.get("page", ""))})
            print(f"  Đã tải {len(records)}/{target}: {dest.name}")
            if len(records) >= target:
                break
    return records


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Tóm tắt SRT, lập kế hoạch cảnh và tải ảnh/video tư liệu.")
    parser.add_argument("srt", type=Path, help="Đường dẫn tới file .srt")
    parser.add_argument("--output", type=Path, help="Thư mục kết quả (mặc định: <tên SRT>_media cạnh file SRT)")
    parser.add_argument("--image-seconds", type=float, default=3, help="Số giây trung bình cho một ảnh (mặc định 3)")
    parser.add_argument("--video-seconds", type=float, default=10, help="Thời lượng tham khảo mỗi clip khi dựng (mặc định 10 giây)")
    parser.add_argument("--video-ratio", type=float, default=0.10, help="Tỷ lệ clip tối đa so với số ảnh dự phòng (mặc định 0.10)")
    parser.add_argument("--max-query-results", type=int, default=80, help="Giới hạn yêu cầu kết quả cho mỗi truy vấn")
    parser.add_argument("--plan-only", action="store_true", help="Chỉ tạo tóm tắt và CSV, không tải media")
    args = parser.parse_args()
    if args.image_seconds <= 0 or args.video_seconds <= 0 or not 0 <= args.video_ratio <= 1:
        parser.error("image-seconds/video-seconds phải > 0 và video-ratio nằm trong 0..1")
    srt = args.srt.expanduser().resolve()
    if not srt.is_file():
        parser.error(f"Không tìm thấy file SRT: {srt}")
    load_dotenv(Path(__file__).resolve().parent)
    output = (args.output or srt.parent / f"{srt.stem}_media").expanduser().resolve()
    try:
        cues = read_srt(srt)
        duration = max(c.end for c in cues)
        images, videos = estimate(duration, args.image_seconds, args.video_seconds, args.video_ratio)
        scenes = make_scenes(cues)
        output.mkdir(parents=True, exist_ok=True)
        (output / "images").mkdir(exist_ok=True)
        (output / "videos").mkdir(exist_ok=True)
        save_plan(output / "00_summary_vi.md", cues, scenes, duration, images, videos, srt.name,
                  args.image_seconds, args.video_seconds, args.video_ratio)
        print(f"Đã lập nội dung: {output}\nThời lượng: {fmt_time(duration)} | mục tiêu: {images} ảnh + {videos} clip")
        if args.plan_only:
            return 0
        pexels_key, pixabay_key = os.getenv("PEXELS_API_KEY", "").strip(), os.getenv("PIXABAY_API_KEY", "").strip()
        if pexels_key:
            provider, key = "Pexels", pexels_key
        elif pixabay_key:
            provider, key = "Pixabay", pixabay_key
        else:
            print("Chưa có API key: đã tạo kế hoạch nhưng chưa thể tìm/tải ảnh và video. Cấu hình PEXELS_API_KEY hoặc PIXABAY_API_KEY trong .env.", file=sys.stderr)
            return 2
        print(f"Đang tìm và tải từ {provider}…")
        image_records = collect("image", images, scenes, output / "images", provider, key, args.max_query_results)
        video_records = collect("video", videos, scenes, output / "videos", provider, key, args.max_query_results)
        with (output / "02_download_manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["kind", "file", "query", "source", "creator", "source_page"])
            writer.writeheader()
            writer.writerows(image_records + video_records)
        print(f"Hoàn tất: tải được {len(image_records)}/{images} ảnh, {len(video_records)}/{videos} clip.\nManifest: {output / '02_download_manifest.csv'}")
        return 0 if image_records or video_records else 3
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
