"""Current iQiyi parser for public, non-DRM videos."""

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

import requests

from china_platforms import DESKTOP_USER_AGENT


_IQIYI_XOR_KEY = int("75706971676c", 16)
_VF_SUFFIX = "ulc2h7tka0mdrf2lkb1n6m6mulc2htbn"
_FORMAT_HEIGHTS = {
    100: 240,
    200: 344,
    300: 480,
    500: 688,
    600: 1080,
    800: 2160,
}


def is_iqiyi_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    domains = ("iqiyi.com", "iq.com", "pps.tv")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


class IqiyiParser:
    BASE_INFO_URL = "https://pcw-api.iqiyi.com/video/video/baseinfo/{tvid}"
    DASH_ORIGIN = "https://cache.video.iqiyi.com"
    INTERNATIONAL_ORIGIN = "https://www.iq.com"
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
        self.device_id = self._md5(uuid.uuid4().hex)
        self._cache = {}
        self._playlists = {}

    def parse(self, url: str) -> dict:
        cached = self._cache.get(url)
        if cached and time.time() - cached["created_at"] < self.CACHE_SECONDS:
            return cached["data"]

        tvid = self._extract_tvid(url)
        metadata = self._fetch_metadata(tvid, url)
        drm_types = metadata.get("supportedDrmTypes") or []
        if drm_types:
            raise ValueError(
                "爱奇艺已将该内容标记为 DRM 保护，无法提供解析下载；"
                "请改用公开且未加密的视频"
            )

        vid = str(metadata.get("vid") or "")
        if not vid:
            raise ValueError("爱奇艺官方接口未返回视频 vid")

        initial = self._fetch_dash(tvid, vid, 0, url)
        videos = ((initial.get("data") or {}).get("program") or {}).get("video") or []
        available_bids = sorted({
            int(item.get("bid"))
            for item in videos
            if str(item.get("bid") or "").isdigit()
        })

        formats = []
        format_records = {}
        seen = set()
        for requested_bid in available_bids[:8]:
            dash = self._fetch_dash(tvid, vid, requested_bid, url)
            stream, playlist, playlist_base = self._find_public_stream(dash)
            if not stream or not playlist:
                continue

            actual_bid = int(stream.get("bid") or requested_bid)
            resolution = stream.get("scrsz") or ""
            width, height = self._parse_resolution(
                resolution,
                _FORMAT_HEIGHTS.get(actual_bid, 0),
            )
            dedupe_key = (actual_bid, width, height)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            token = hashlib.sha256(
                f"{url}|{actual_bid}|{time.time_ns()}".encode()
            ).hexdigest()[:32]
            created_at = time.time()
            self._playlists[token] = {
                "created_at": created_at,
                "content": playlist,
                "base_url": playlist_base,
                "referer": url,
            }

            format_id = f"iqiyi_hls:{actual_bid}"
            filesize = stream.get("vsize") or stream.get("mp4Size")
            format_record = {
                "token": token,
                "playlist": playlist,
                "base_url": playlist_base,
                "referer": url,
            }
            format_records[format_id] = format_record
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

        if not formats:
            raise ValueError(
                "爱奇艺未返回公开的非 DRM 播放流；"
                "该内容可能需要登录、会员权限或受地区限制"
            )

        formats.sort(key=lambda item: item["height"], reverse=True)
        duration = self._to_int(metadata.get("durationSec"))
        thumbnail = str(metadata.get("imageUrl") or "")
        if thumbnail.startswith("http://"):
            thumbnail = "https://" + thumbnail[7:]

        result = {
            "id": str(metadata.get("tvId") or tvid),
            "title": metadata.get("name") or "爱奇艺视频",
            "thumbnail": thumbnail,
            "duration": duration,
            "duration_string": self._format_duration(duration),
            "uploader": self._uploader_name(metadata),
            "platform": "爱奇艺",
            "view_count": None,
            "upload_date": self._upload_date(metadata.get("publishTime")),
            "description": str(metadata.get("description") or "")[:200],
            "formats": formats,
            "subtitles": [],
            "automatic_captions": [],
        }
        self._cache[url] = {
            "created_at": time.time(),
            "data": result,
            "formats": format_records,
        }
        self._prune_cache()
        return result

    def download(self, url: str, format_id: str) -> dict:
        info, record = self._resolve_format(url, format_id)
        playlist = record["playlist"]
        if self._playlist_is_encrypted(playlist):
            raise ValueError("爱奇艺播放列表使用了加密保护，无法下载")

        segment_urls = [
            urljoin(record["base_url"], line.strip())
            for line in playlist.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not segment_urls:
            raise ValueError("爱奇艺播放列表中没有可下载的视频分片")

        title = self._sanitize_filename(info["title"])
        filename = f"{title or info['id']}.ts"
        filepath = self.download_dir / filename
        temp_path = filepath.with_suffix(".ts.part")
        headers = {
            "User-Agent": DESKTOP_USER_AGENT,
            "Referer": record["referer"],
        }

        try:
            with temp_path.open("wb") as output:
                for segment_url in segment_urls:
                    with self.session.get(
                        segment_url,
                        headers=headers,
                        stream=True,
                        timeout=self.timeout,
                        allow_redirects=True,
                    ) as response:
                        response.raise_for_status()
                        for chunk in response.iter_content(64 * 1024):
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
        info, record = self._resolve_format(url, format_id)
        return {
            "direct_url": f"/api/iqiyi/playlist/{record['token']}.m3u8",
            "ext": "m3u8",
            "filesize": None,
            "title": info["title"],
        }

    def get_playlist(self, token: str) -> str:
        record = self._playlists.get(token)
        if not record or time.time() - record["created_at"] >= self.CACHE_SECONDS:
            self._playlists.pop(token, None)
            raise ValueError("爱奇艺播放列表已过期，请重新解析视频")
        return record["content"]

    def get_subtitles(self, url: str) -> list[dict]:
        """Return public subtitle tracks exposed by iQiyi's official player."""
        tvid = self._extract_tvid(url)
        metadata = self._fetch_metadata(tvid, url)
        play_url = str(metadata.get("playUrl") or metadata.get("albumUrl") or url)
        page_url = self._international_page_url(play_url, url)

        response = self.session.get(
            page_url,
            headers={"Referer": url},
            timeout=self.timeout,
        )
        response.raise_for_status()
        next_data = self._extract_next_data(response.text)
        page_props = (
            ((next_data.get("props") or {}).get("initialProps") or {})
            .get("pageProps") or {}
        )
        pre_player = page_props.get("prePlayerData") or {}
        dash_data = ((pre_player.get("dash") or {}).get("data") or {})
        program = dash_data.get("program") or {}
        subtitle_items = program.get("stl") or []
        subtitle_origin = (
            dash_data.get("dstl")
            or dash_data.get("dm")
            or "https://meta.video.iqiyi.com"
        )

        tracks = []
        for item in subtitle_items:
            if not isinstance(item, dict):
                continue
            language = self._subtitle_language(item)
            for key, ext in (("webvtt", "vtt"), ("srt", "srt"), ("xml", "xml")):
                path = item.get(key)
                if not path:
                    continue
                tracks.append({
                    "language": language,
                    "name": item.get("_name") or language,
                    "ext": ext,
                    "url": urljoin(subtitle_origin, str(path)),
                    "referer": page_url,
                })

        return tracks

    def _resolve_format(self, url: str, format_id: str) -> tuple[dict, dict]:
        info = self.parse(url)
        cached = self._cache[url]
        formats = cached["formats"]
        if format_id not in formats:
            format_id = info["formats"][0]["format_id"]
        return info, formats[format_id]

    def _extract_tvid(self, url: str) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("shareId", "positiveId"):
            if query.get(key):
                page_tvid = self._extract_page_tvid(url)
                if page_tvid:
                    return page_tvid
                try:
                    import base64

                    decoded = base64.b64decode(unquote(query[key][0])).decode()
                    if decoded.isdigit():
                        return decoded
                except (ValueError, UnicodeDecodeError):
                    pass

        match = re.search(r"/[vwp]_([A-Za-z0-9]+)\.html", parsed.path)
        if not match:
            page_tvid = self._extract_page_tvid(url)
            if page_tvid:
                return page_tvid
            raise ValueError("无法识别爱奇艺视频 ID，请使用单个视频详情页地址")

        value = int(match.group(1), 36) ^ _IQIYI_XOR_KEY
        if value < 900000:
            value = 100 * (value + 900000)
        if value <= 0:
            raise ValueError("爱奇艺视频 ID 无效")
        return str(value)

    def _extract_page_tvid(self, url: str) -> str:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException:
            return ""

        try:
            next_data = self._extract_next_data(response.text)
            page_props = (
                ((next_data.get("props") or {}).get("initialProps") or {})
                .get("pageProps") or {}
            )
            pre_player = page_props.get("prePlayerData") or {}
            candidates = [
                pre_player.get("tvid"),
                (((pre_player.get("dash") or {}).get("data") or {}).get("tvid")),
            ]
            for candidate in candidates:
                if str(candidate or "").isdigit():
                    return str(candidate)
        except (ValueError, TypeError):
            pass

        matches = re.findall(r'"tvid"\s*:\s*"?(\d{6,})"?', response.text)
        return matches[-1] if matches else ""

    def _international_page_url(self, play_url: str, original_url: str) -> str:
        original_host = (urlparse(original_url).hostname or "").lower()
        if original_host == "iq.com" or original_host.endswith(".iq.com"):
            parsed = urlparse(original_url)
            query = parse_qs(parsed.query)
            query["lang"] = ["zh_cn"]
            return parsed._replace(query=urlencode(query, doseq=True)).geturl()

        match = re.search(r"/[vwp]_([A-Za-z0-9]+)\.html", play_url)
        if not match:
            raise ValueError("爱奇艺官方元数据未返回可用的字幕页面地址")
        return f"{self.INTERNATIONAL_ORIGIN}/play/{match.group(1)}?lang=zh_cn"

    @staticmethod
    def _extract_next_data(webpage: str) -> dict:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            webpage,
            re.DOTALL,
        )
        if not match:
            raise ValueError("爱奇艺官方页面未返回播放器字幕数据")
        return json.loads(match.group(1))

    @staticmethod
    def _subtitle_language(item: dict) -> str:
        name = str(item.get("_name") or "").lower()
        if "simplified" in name or "简体" in name:
            return "zh-Hans"
        if "traditional" in name or "繁体" in name:
            return "zh-Hant"
        if "english" in name or name == "en":
            return "en"
        return str(item.get("lid") or item.get("_name") or "unknown")

    def _fetch_metadata(self, tvid: str, referer: str) -> dict:
        response = self.session.get(
            self.BASE_INFO_URL.format(tvid=tvid),
            headers={"Referer": referer},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "A00000" or not payload.get("data"):
            raise ValueError(payload.get("msg") or "爱奇艺官方元数据接口返回异常")
        return payload["data"]

    def _fetch_dash(self, tvid: str, vid: str, bid: int, referer: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        params = {
            "tvid": tvid,
            "bid": str(bid),
            "vid": vid,
            "src": "01010031010000000000",
            "vt": "0",
            "rs": "1",
            "uid": "",
            "ori": "pcw",
            "ps": "0",
            "k_uid": self.device_id,
            "pt": "0",
            "d": "0",
            "s": "",
            "lid": "0",
            "cf": "0",
            "ct": "0",
            "authKey": self._md5(self._md5("") + timestamp + tvid),
            "k_tag": "1",
            "dfp": "",
            "locale": "zh_cn",
            "up": "",
            "qd_v": "a1",
            "tm": timestamp,
            "k_ft1": "143486267424900",
            "k_ft4": "1572868",
            "k_ft7": "4",
            "bop": json.dumps(
                {"version": "10.0", "dfp": ""},
                separators=(",", ":"),
            ),
            "sr": "1",
        }
        path = "/dash?" + urlencode(params) + "&ut=0"
        vf = self._md5(path + _VF_SUFFIX)
        response = self.session.get(
            self.DASH_ORIGIN + path + "&vf=" + vf,
            headers={"Referer": referer},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "A00000" or not payload.get("data"):
            raise ValueError(payload.get("msg") or "爱奇艺播放接口返回异常")
        return payload

    def _find_public_stream(self, dash: dict) -> tuple[Optional[dict], str, str]:
        data = dash.get("data") or {}
        videos = ((data.get("program") or {}).get("video") or [])
        for stream in videos:
            playlist = stream.get("m3u8")
            if playlist:
                return stream, playlist, data.get("dm3u8") or self.DASH_ORIGIN

            playlist_url = stream.get("m3u8Url")
            if playlist_url:
                full_url = urljoin(
                    data.get("dm3u8") or self.DASH_ORIGIN,
                    playlist_url,
                )
                response = self.session.get(full_url, timeout=self.timeout)
                response.raise_for_status()
                return stream, response.text, full_url
        return None, "", ""

    def _prune_cache(self):
        cutoff = time.time() - self.CACHE_SECONDS
        self._cache = {
            key: value
            for key, value in self._cache.items()
            if value["created_at"] >= cutoff
        }
        self._playlists = {
            key: value
            for key, value in self._playlists.items()
            if value["created_at"] >= cutoff
        }

    @staticmethod
    def _playlist_is_encrypted(playlist: str) -> bool:
        return bool(re.search(r"#EXT-X-KEY:(?![^\n]*METHOD=NONE)", playlist))

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode()).hexdigest()

    @staticmethod
    def _parse_resolution(value: str, fallback_height: int) -> tuple[int, int]:
        match = re.search(r"(\d+)[xX](\d+)", value or "")
        if match:
            return int(match.group(1)), int(match.group(2))
        return 0, fallback_height

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
    def _upload_date(timestamp) -> str:
        try:
            value = int(timestamp)
            if value > 10_000_000_000:
                value //= 1000
            return time.strftime("%Y%m%d", time.localtime(value))
        except (TypeError, ValueError, OSError):
            return ""

    @staticmethod
    def _uploader_name(metadata: dict) -> str:
        user = metadata.get("user")
        if isinstance(user, dict):
            return user.get("name") or user.get("nickname") or "爱奇艺"
        return "爱奇艺"

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|\n\r\t#@]', "_", value).strip("_. ")
        return cleaned[:90]
