"""Parser for public Kuaishou share and short-video pages."""

import html as html_lib
import json
import re
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests

from china_platforms import DESKTOP_USER_AGENT


_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_MEDIA_URL_KEYS = (
    "photoUrl",
    "originPhotoUrl",
    "playUrl",
    "videoUrl",
    "srcNoMark",
)
_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Mobile Safari/537.36"
)


def is_kuaishou_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    domains = (
        "kuaishou.com",
        "kuaishouapp.com",
        "gifshow.com",
        "chenzhongtech.com",
        "kwai.com",
        "kuai.com",
    )
    return any(host == domain or host.endswith("." + domain) for domain in domains)


class _PageDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.scripts = []
        self._script_parts = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            content = attrs.get("content")
            if key and content:
                self.meta[key.lower()] = content
        elif tag == "script":
            self._script_parts = []

    def handle_data(self, data):
        if self._script_parts is not None:
            self._script_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script_parts is not None:
            value = "".join(self._script_parts).strip()
            if value:
                self.scripts.append(value)
            self._script_parts = None


class KuaishouParser:
    GRAPHQL_URL = "https://www.kuaishou.com/graphql"

    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DESKTOP_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.kuaishou.com/",
        })
        self.session.cookies.set("did", f"web_{uuid.uuid4().hex}", domain=".kuaishou.com")
        self.session.cookies.set("didv", str(int(time.time() * 1000)), domain=".kuaishou.com")
        self.timeout = (10, 30)
        self._cache = {}

    def parse(self, value: str) -> dict:
        share_url = self._extract_url(value)
        cached = self._cache.get(share_url)
        if cached and time.time() - cached["created_at"] < 600:
            return cached["data"]

        resolved_url, page_html = self._resolve_page(share_url)
        photo_id = self._extract_photo_id(resolved_url, page_html)

        page_data = self._extract_page_data(page_html)
        data = page_data
        media_url = self._find_media_url(page_data)

        if not media_url and photo_id:
            mobile_data = self._fetch_mobile_page(photo_id)
            media_url = self._find_media_url(mobile_data)
            if media_url:
                data = mobile_data

        if not media_url and photo_id:
            api_data = self._fetch_graphql(photo_id)
            media_url = self._find_media_url(api_data)
            if media_url:
                data = api_data

        if not media_url:
            raise ValueError(
                "快手页面未返回公开的视频地址；请使用公开视频详情页或分享短链接，"
                "登录可见、私密和 DRM 内容暂不支持"
            )

        photo = self._find_photo_node(data) or {}
        author = photo.get("author") if isinstance(photo.get("author"), dict) else {}
        title = (
            photo.get("caption")
            or photo.get("title")
            or page_data.get("title")
            or f"快手视频_{photo_id or 'video'}"
        )
        thumbnail = (
            self._first_url(photo.get("coverUrls"))
            or photo.get("coverUrl")
            or page_data.get("thumbnail")
            or ""
        )
        duration_ms = photo.get("duration") or page_data.get("duration")
        duration = self._duration_seconds(duration_ms)
        width = self._to_int(photo.get("width") or page_data.get("width"))
        height = self._to_int(photo.get("height") or page_data.get("height"))

        result = {
            "id": str(photo.get("id") or photo_id or "kuaishou"),
            "title": str(title),
            "thumbnail": thumbnail,
            "duration": duration,
            "duration_string": self._format_duration(duration),
            "uploader": (
                author.get("name")
                or photo.get("userName")
                or page_data.get("uploader")
                or "快手用户"
            ),
            "platform": "快手",
            "view_count": self._to_int(photo.get("viewCount") or photo.get("likeCount")),
            "upload_date": "",
            "description": str(title)[:200],
            "formats": [{
                "format_id": "kuaishou_direct",
                "ext": "mp4",
                "resolution": f"{width}x{height}" if width and height else "原始",
                "height": height or 0,
                "filesize": None,
                "filesize_approx": None,
                "vcodec": "h264",
                "acodec": "aac",
                "has_audio": True,
                "is_audio_only": False,
                "label": f"{height}p MP4 (原始画质)" if height else "MP4 (原始画质)",
                "_direct_url": media_url,
            }],
            "subtitles": [],
            "automatic_captions": [],
        }
        self._cache[share_url] = {"created_at": time.time(), "data": result}
        return result

    def download(self, url: str, format_id: str = "kuaishou_direct") -> dict:
        info = self.parse(url)
        direct_url = info["formats"][0]["_direct_url"]
        title = re.sub(r'[\\/*?:"<>|\n\r\t#@]', "_", info["title"]).strip("_. ")[:70]
        filename = f"{title or info['id']}.mp4"
        filepath = self.download_dir / filename

        with self.session.get(
            direct_url,
            stream=True,
            timeout=self.timeout,
            allow_redirects=True,
            headers={"Referer": url, "User-Agent": DESKTOP_USER_AGENT},
        ) as response:
            response.raise_for_status()
            temp_path = filepath.with_suffix(".mp4.part")
            with temp_path.open("wb") as output:
                for chunk in response.iter_content(64 * 1024):
                    if chunk:
                        output.write(chunk)
            temp_path.replace(filepath)

        return {
            "filepath": str(filepath),
            "filename": filename,
            "title": info["title"],
            "ext": "mp4",
        }

    def get_direct_url(self, url: str, format_id: str = "kuaishou_direct") -> dict:
        info = self.parse(url)
        return {
            "direct_url": info["formats"][0]["_direct_url"],
            "ext": "mp4",
            "filesize": None,
            "title": info["title"],
        }

    def _extract_url(self, value: str) -> str:
        match = _URL_PATTERN.search(value)
        if not match:
            raise ValueError("未找到有效的快手链接")
        return match.group(0).strip("\"'").rstrip(").,;!?")

    def _resolve_page(self, url: str) -> tuple[str, str]:
        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        return response.url, response.text or ""

    def _extract_photo_id(self, url: str, page_html: str) -> Optional[str]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("photoId", "photo_id", "shareObjectId"):
            if query.get(key):
                return query[key][0]

        for pattern in (
            r"/short-video/([A-Za-z0-9_-]+)",
            r"/f/([A-Za-z0-9_-]+)",
            r"/photo/([A-Za-z0-9_-]+)",
            r"/video/([A-Za-z0-9_-]+)",
            r'"photoId"\s*:\s*"([A-Za-z0-9_-]+)"',
        ):
            match = re.search(pattern, url if pattern.startswith("/") else page_html)
            if match:
                return match.group(1)
        return None

    def _fetch_graphql(self, photo_id: str) -> dict:
        query = """
        query visionVideoDetail($photoId: String, $page: String, $webPageArea: String) {
          visionVideoDetail(photoId: $photoId, page: $page, webPageArea: $webPageArea) {
            status
            type
            author { id name headerUrl }
            photo {
              id duration caption likeCount viewCount coverUrl photoUrl photoH265Url
              width height
              manifest {
                adaptationSet {
                  representation { id url backupUrl width height qualityType }
                }
              }
            }
          }
        }
        """
        try:
            response = self.session.post(
                self.GRAPHQL_URL,
                json={
                    "operationName": "visionVideoDetail",
                    "variables": {
                        "photoId": photo_id,
                        "page": "detail",
                        "webPageArea": "brilliant",
                    },
                    "query": query,
                },
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://www.kuaishou.com",
                    "Referer": f"https://www.kuaishou.com/short-video/{photo_id}",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            detail = (payload.get("data") or {}).get("visionVideoDetail") or {}
            if detail.get("status") not in (None, 1, 2):
                return {}
            return detail
        except (requests.RequestException, ValueError):
            return {}

    def _fetch_mobile_page(self, photo_id: str) -> dict:
        hosts = (
            "v.m.chenzhongtech.com",
            "m.gifshow.com",
            "v.kuaishou.com",
        )
        for host in hosts:
            try:
                response = requests.get(
                    f"https://{host}/fw/photo/{photo_id}",
                    params={"shareToken": uuid.uuid4().hex[:8]},
                    headers={
                        "User-Agent": _MOBILE_USER_AGENT,
                        "Accept": "*/*",
                    },
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                response.raise_for_status()
                data = self._extract_page_data(response.text or "")
                if self._find_media_url(data):
                    return data
            except requests.RequestException:
                continue
        return {}

    def _extract_page_data(self, page_html: str) -> dict:
        parser = _PageDataParser()
        try:
            parser.feed(page_html)
        except Exception:
            pass

        result = {
            "title": parser.meta.get("og:title") or parser.meta.get("twitter:title"),
            "thumbnail": parser.meta.get("og:image") or parser.meta.get("twitter:image"),
            "photoUrl": parser.meta.get("og:video") or parser.meta.get("og:video:url"),
        }

        for script in parser.scripts:
            candidate = script.strip().rstrip(";")
            if candidate.startswith("window.") and "=" in candidate:
                candidate = candidate.split("=", 1)[1].strip().rstrip(";")
            if not candidate.startswith(("{", "[")):
                continue
            try:
                data = json.loads(candidate)
            except ValueError:
                continue
            if self._find_media_url(data):
                return {**result, "pageData": data}

        for key in _MEDIA_URL_KEYS:
            match = re.search(
                rf'["\']{key}["\']\s*:\s*["\']([^"\']+)["\']',
                page_html,
            )
            if match:
                result[key] = self._clean_url(match.group(1))
                break
        return result

    def _find_photo_node(self, data: Any) -> Optional[dict]:
        if isinstance(data, dict):
            photo = data.get("photo")
            if isinstance(photo, dict):
                if isinstance(data.get("author"), dict) and "author" not in photo:
                    photo = {**photo, "author": data["author"]}
                return photo
            for value in data.values():
                found = self._find_photo_node(value)
                if found:
                    return found
        elif isinstance(data, list):
            for value in data:
                found = self._find_photo_node(value)
                if found:
                    return found
        return None

    def _find_media_url(self, data: Any) -> str:
        if isinstance(data, dict):
            for key in _MEDIA_URL_KEYS:
                value = data.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return self._clean_url(value)

            representations = data.get("representation")
            if isinstance(representations, list):
                for item in representations:
                    if not isinstance(item, dict):
                        continue
                    for key in ("url", "backupUrl"):
                        value = item.get(key)
                        if isinstance(value, str) and value.startswith(("http://", "https://")):
                            return self._clean_url(value)

            for value in data.values():
                found = self._find_media_url(value)
                if found:
                    return found
        elif isinstance(data, list):
            for value in data:
                found = self._find_media_url(value)
                if found:
                    return found
        return ""

    @staticmethod
    def _clean_url(value: str) -> str:
        return html_lib.unescape(value).replace("\\u002F", "/").replace("\\/", "/")

    @staticmethod
    def _first_url(value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    return item
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    return item["url"]
        return ""

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _duration_seconds(cls, value: Any) -> Optional[int]:
        duration = cls._to_int(value)
        if duration is None:
            return None
        return duration // 1000 if duration > 1000 else duration

    @staticmethod
    def _format_duration(seconds: Optional[int]) -> str:
        if not seconds:
            return "00:00"
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
