import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp


SUPPORTED_HOSTS = {"775069.xyz", "www.775069.xyz", "775070.xyz", "www.775070.xyz"}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_PLAY_PATH_PATTERN = re.compile(r"/vodplay/(\d+)-(\d+)-(\d+)(?:\.html|/)?", re.IGNORECASE)
_TITLE_PATTERN = re.compile(r'<h3[^>]*class=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</h3>', re.IGNORECASE | re.DOTALL)
_META_TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_IMG_PATTERN = re.compile(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE)


def is_775069_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host in SUPPORTED_HOSTS


class Site775069Parser:
    """解析 775069.xyz 公开播放页中的 MacCMS 播放数据。"""

    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = (10, 30)

    def parse(self, url: str) -> dict:
        page_url = self._normalize_url(url)
        video_id, sid, nid = self._extract_play_ids(page_url)
        html = self._fetch_text(page_url)
        play_data = self._fetch_play_data(page_url, video_id, sid, nid)
        media_url = self._extract_media_url(play_data)

        title = self._extract_title(html) or f"775069_{video_id}_{sid}_{nid}"
        thumbnail = self._extract_thumbnail(html, page_url)

        return {
            "id": f"{video_id}-{sid}-{nid}",
            "title": title,
            "thumbnail": thumbnail,
            "duration": None,
            "duration_string": "00:00",
            "uploader": "775069.xyz",
            "platform": "775069.xyz",
            "view_count": self._extract_view_count(html),
            "upload_date": self._extract_upload_date(html),
            "description": "",
            "formats": [
                {
                    "format_id": "hls",
                    "ext": "mp4",
                    "resolution": "自动",
                    "height": 0,
                    "filesize": None,
                    "filesize_approx": None,
                    "vcodec": "h264",
                    "acodec": "aac",
                    "has_audio": True,
                    "label": "HLS MP4 (自动清晰度)",
                }
            ],
            "subtitles": [],
            "automatic_captions": [],
            "direct_url": media_url,
        }

    def download(self, url: str, format_id: str = "hls") -> dict:
        parsed = self.parse(url)
        media_url = parsed["direct_url"]
        title = self._sanitize_filename(parsed["title"]) or parsed["id"]

        ydl_opts = {
            "format": "best",
            "outtmpl": str(self.download_dir / f"{title}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "http_headers": {
                **DEFAULT_HEADERS,
                "Referer": self._normalize_url(url),
            },
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(media_url, download=True)

        if not info:
            raise ValueError("下载失败")

        filepath = ydl.prepare_filename(info)
        if not os.path.exists(filepath):
            base, _ = os.path.splitext(filepath)
            mp4_path = base + ".mp4"
            if os.path.exists(mp4_path):
                filepath = mp4_path

        if not os.path.exists(filepath):
            raise ValueError("下载后的文件不存在")

        return {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "title": parsed["title"],
            "ext": Path(filepath).suffix.lstrip(".") or "mp4",
        }

    def get_direct_url(self, url: str, format_id: str = "hls") -> dict:
        parsed = self.parse(url)
        return {
            "direct_url": parsed["direct_url"],
            "ext": "m3u8",
            "filesize": None,
            "title": parsed["title"],
        }

    def _normalize_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        parsed = urlparse(url)
        if parsed.netloc.lower() not in SUPPORTED_HOSTS:
            raise ValueError("暂不支持该域名")
        return url

    def _extract_play_ids(self, url: str) -> tuple[str, str, str]:
        match = _PLAY_PATH_PATTERN.search(urlparse(url).path)
        if not match:
            raise ValueError("无法识别播放页地址，请使用 /vodplay/视频ID-线路-集数.html 格式")
        return match.group(1), match.group(2), match.group(3)

    def _fetch_text(self, url: str) -> str:
        resp = self.session.get(url, timeout=self.timeout, headers={**DEFAULT_HEADERS, "Referer": url})
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        text = resp.text or ""
        if self._is_waf_block(text):
            raise ValueError("站点开启了反爬保护，无法直接获取页面内容")
        return text

    def _fetch_play_data(self, page_url: str, video_id: str, sid: str, nid: str) -> dict:
        """Try multiple API endpoints and sid fallback to get play data."""
        headers_with_ref = {**DEFAULT_HEADERS, "Referer": page_url}

        # Try the correct MacCMS API: /playdata/{video_id}?sid={sid}
        for try_sid in range(int(sid), int(sid) + 5):
            endpoint = urljoin(page_url, f"/playdata/{video_id}")
            resp = self.session.get(endpoint, params={"sid": try_sid}, timeout=self.timeout, headers=headers_with_ref)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                if self._is_waf_block(resp.text or ''):
                    continue  # WAF block, try next sid
                raise
            if data.get("code") == 200 and data.get("url"):
                return data

        # Fallback: try old playdata.php API
        for try_sid in range(int(sid), int(sid) + 5):
            endpoint = urljoin(page_url, "/playdata.php")
            resp = self.session.get(endpoint, params={"id": video_id, "sid": try_sid, "nid": nid}, timeout=self.timeout, headers=headers_with_ref)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                if self._is_waf_block(resp.text or ''):
                    continue
                raise
            if data.get("ok") and (data.get("p") or {}).get("url"):
                return data

        raise ValueError("播放数据接口返回失败")

    def _extract_media_url(self, play_data: dict) -> str:
        # New API format: {"code": 200, "url": "..."}
        media_url = play_data.get("url") or ""
        # Old API format: {"ok": true, "p": {"url": "..."}}
        if not media_url:
            media_url = (play_data.get("p") or {}).get("url") or ""
        if not media_url:
            raise ValueError("播放数据中未找到视频地址")
        return media_url

    def _extract_title(self, html: str) -> str:
        for pattern in (_META_TITLE_PATTERN, _TITLE_PATTERN):
            match = pattern.search(html)
            if match:
                return self._clean_text(match.group(1))
        return ""

    def _extract_thumbnail(self, html: str, page_url: str) -> str:
        match = _IMG_PATTERN.search(html)
        if not match:
            return ""
        return urljoin(page_url, match.group(1).strip())

    def _extract_view_count(self, html: str) -> int | None:
        match = re.search(r'<span[^>]*class=["\']text-red["\'][^>]*>\s*(\d+)\s*</span>\s*次播放', html)
        if not match:
            return None
        return int(match.group(1))

    def _extract_upload_date(self, html: str) -> str:
        match = re.search(r"时间：\s*(\d{4}-\d{2}-\d{2})", html)
        return match.group(1).replace("-", "") if match else ""

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace("黄色仓库-hsck.tv - ", "")
        return text

    def _sanitize_filename(self, name: str) -> str:
        name = self._clean_text(name)
        name = re.sub(r'[\\/*?:"<>|\n\r\t#@]', "_", name).strip("_. ")
        return re.sub(r"_+", "_", name)[:80]
