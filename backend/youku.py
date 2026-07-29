"""Youku parser that does not depend on the optional mmstat endpoint."""

import re
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

from china_platforms import DESKTOP_USER_AGENT


def is_youku_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    domains = ("youku.com", "tudou.com")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


class YoukuParser:
    UPS_URL = "https://ups.youku.com/ups/get.json"
    CACHE_SECONDS = 600

    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DESKTOP_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.timeout = (10, 30)
        self._cache = {}

    def parse(self, url: str) -> dict:
        cached = self._cache.get(url)
        if cached and time.time() - cached["created_at"] < self.CACHE_SECONDS:
            return cached["data"]

        video_id = self._extract_video_id(url)
        payload = self._fetch_ups(video_id, url)
        video = payload.get("video") or {}
        uploader = payload.get("uploader") or {}
        formats = []
        records = {}

        for stream in payload.get("stream") or []:
            if stream.get("channel_type") == "tail":
                continue
            media_url = stream.get("m3u8_url")
            if not media_url:
                continue

            stream_type = str(stream.get("stream_type") or len(formats))
            format_id = f"youku_hls:{stream_type}"
            height = self._to_int(stream.get("height")) or 0
            width = self._to_int(stream.get("width")) or 0
            filesize = self._to_int(stream.get("size"))
            formats.append({
                "format_id": format_id,
                "ext": "ts",
                "resolution": (
                    f"{width}x{height}" if width and height else f"{height}p"
                    if height else "自动"
                ),
                "height": height,
                "filesize": filesize,
                "filesize_approx": filesize,
                "vcodec": "h264",
                "acodec": "aac",
                "has_audio": True,
                "is_audio_only": False,
                "label": (
                    f"{height}p HLS (视频+音频)"
                    if height else "HLS (视频+音频)"
                ),
            })
            records[format_id] = media_url

        if not formats:
            raise ValueError(
                "优酷未返回公开的非 DRM 播放流；"
                "该内容可能需要登录、会员权限或受地区限制"
            )

        formats.sort(key=lambda item: item["height"], reverse=True)
        duration = self._to_int(float(video.get("seconds") or 0))
        result = {
            "id": video_id,
            "title": video.get("title") or "优酷视频",
            "thumbnail": video.get("logo") or "",
            "duration": duration,
            "duration_string": self._format_duration(duration),
            "uploader": video.get("username") or uploader.get("username") or "优酷",
            "platform": "优酷",
            "view_count": None,
            "upload_date": "",
            "description": "",
            "formats": formats,
            "subtitles": [],
            "automatic_captions": [],
        }
        self._cache[url] = {
            "created_at": time.time(),
            "data": result,
            "formats": records,
        }
        return result

    def download(self, url: str, format_id: str) -> dict:
        info, playlist_url = self._resolve_format(url, format_id)
        headers = {
            "User-Agent": DESKTOP_USER_AGENT,
            "Referer": url,
        }
        response = self.session.get(
            playlist_url,
            headers=headers,
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        playlist = response.text
        if re.search(r"#EXT-X-KEY:(?![^\n]*METHOD=NONE)", playlist):
            raise ValueError("优酷播放列表使用了加密保护，无法下载")

        segment_urls = [
            urljoin(playlist_url, line.strip())
            for line in playlist.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not segment_urls:
            raise ValueError("优酷播放列表中没有可下载的视频分片")

        title = self._sanitize_filename(info["title"])
        filename = f"{title or info['id']}.ts"
        filepath = self.download_dir / filename
        temp_path = filepath.with_suffix(".ts.part")
        try:
            with temp_path.open("wb") as output:
                for segment_url in segment_urls:
                    with self.session.get(
                        segment_url,
                        headers=headers,
                        stream=True,
                        timeout=self.timeout,
                        allow_redirects=True,
                    ) as segment:
                        segment.raise_for_status()
                        for chunk in segment.iter_content(64 * 1024):
                            if chunk:
                                output.write(chunk)
            temp_path.replace(filepath)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return {
            "filepath": str(filepath),
            "filename": filename,
            "title": info["title"],
            "ext": "ts",
        }

    def get_direct_url(self, url: str, format_id: str) -> dict:
        info, playlist_url = self._resolve_format(url, format_id)
        return {
            "direct_url": playlist_url,
            "ext": "m3u8",
            "filesize": None,
            "title": info["title"],
        }

    def _resolve_format(self, url: str, format_id: str) -> tuple[dict, str]:
        info = self.parse(url)
        records = self._cache[url]["formats"]
        if format_id not in records:
            format_id = info["formats"][0]["format_id"]
        return info, records[format_id]

    def _fetch_ups(self, video_id: str, referer: str) -> dict:
        response = self.session.get(
            self.UPS_URL,
            params={
                "vid": video_id,
                "ccode": "0564",
                "client_ip": "192.168.1.1",
                "utid": uuid.uuid4().hex[:24],
                "client_ts": time.time() / 1000,
            },
            headers={"Referer": referer},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        error = data.get("error")
        if error:
            note = error.get("note") or "优酷播放接口返回异常"
            raise ValueError(note)
        return data

    @staticmethod
    def _extract_video_id(url: str) -> str:
        match = re.search(
            r"(?:id_|sid/)([A-Za-z0-9=]+)",
            url,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("无法识别优酷视频 ID，请使用单个视频详情页地址")
        return match.group(1)

    @staticmethod
    def _to_int(value) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_duration(seconds: Optional[int]) -> str:
        if not seconds:
            return "00:00"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|\n\r\t#@]', "_", value).strip("_. ")
        return cleaned[:90]
