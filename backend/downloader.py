import os
import re
import shutil
import time
import httpx
import yt_dlp
from typing import Optional
from urllib.parse import urlparse

from china_platforms import (
    detect_china_platform,
    display_platform_name,
    platform_error,
    ytdlp_options_for_url,
)


def _find_ffmpeg_path() -> Optional[str]:
    """查找 ffmpeg 可执行文件路径"""
    if shutil.which("ffmpeg"):
        return os.path.dirname(shutil.which("ffmpeg"))
    try:
        import static_ffmpeg
        paths = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        return os.path.dirname(paths[0])
    except Exception:
        return None


BILIBILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def is_bilibili_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host == "b23.tv" or host.endswith("bilibili.com")


MAINLAND_RESTRICTED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
)


def _ensure_platform_reachable(url: str) -> None:
    region = os.getenv("DEPLOY_REGION", "").strip().lower()
    if region not in {"cn", "china", "cn-mainland"}:
        return

    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return

    if any(host == domain or host.endswith(f".{domain}") for domain in MAINLAND_RESTRICTED_HOSTS):
        raise ValueError(
            "当前服务部署在中国大陆，无法直接访问该境外平台。"
            "请使用香港或海外服务器部署后端。"
        )


def _is_bilibili_api_format(format_id: str) -> bool:
    return format_id.startswith("bilibili_api:")


class VideoDownloader:
    """yt-dlp 封装层，提供视频解析、下载、直链获取能力"""

    DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")

    def __init__(self):
        os.makedirs(self.DOWNLOAD_DIR, exist_ok=True)
        self.ffmpeg_path = _find_ffmpeg_path()
        self.has_ffmpeg = self.ffmpeg_path is not None

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", name)

    @staticmethod
    def _format_filesize(size: Optional[int]) -> str:
        if not size:
            return "未知大小"
        if size < 1024 * 1024:
            return f"{size / 1024:.0f}KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f}MB"
        return f"{size / (1024 * 1024 * 1024):.2f}GB"

    @staticmethod
    def _format_duration(seconds: Optional[int]) -> str:
        if not seconds:
            return "00:00"
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def _parse_bvid(url: str) -> Optional[str]:
        match = re.search(r"(BV[a-zA-Z0-9]+)", url)
        return match.group(1) if match else None

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http://"):
            return "https://" + url[7:]
        return url

    def _bilibili_headers(self, bvid: str = "") -> dict:
        headers = dict(BILIBILI_HEADERS)
        if bvid:
            headers["Referer"] = f"https://www.bilibili.com/video/{bvid}/"
        headers["Origin"] = "https://www.bilibili.com"
        return headers

    def _get_bilibili_view(self, url: str) -> dict:
        bvid = self._parse_bvid(url)
        if not bvid:
            raise ValueError("无法识别 B 站 BV 号")

        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        with httpx.Client(follow_redirects=True, timeout=15) as client:
            resp = client.get(api_url, headers=self._bilibili_headers(bvid))
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("code") != 0 or not payload.get("data"):
            raise ValueError(payload.get("message") or "B 站视频信息接口返回异常")
        return payload["data"]

    def _get_bilibili_playurl(self, bvid: str, cid: int, qn: int = 80, fnval: int = 0) -> dict:
        api_url = (
            "https://api.bilibili.com/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn={qn}&fnval={fnval}&fourk=1"
        )
        with httpx.Client(follow_redirects=True, timeout=15) as client:
            resp = client.get(api_url, headers=self._bilibili_headers(bvid))
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("code") != 0 or not payload.get("data"):
            raise ValueError(payload.get("message") or "B 站播放地址接口返回异常")
        return payload["data"]

    def _parse_bilibili_api(self, url: str) -> dict:
        """B 站 API 兜底解析，用于规避 yt-dlp 偶发 412。"""
        view = self._get_bilibili_view(url)
        bvid = view["bvid"]
        pages = view.get("pages") or []
        cid = view.get("cid") or (pages[0].get("cid") if pages else None)
        if not cid:
            raise ValueError("B 站视频缺少 cid，无法获取播放地址")

        play = self._get_bilibili_playurl(bvid, cid, qn=80, fnval=0)
        formats = self._extract_bilibili_api_formats(play)

        stat = view.get("stat") or {}
        owner = view.get("owner") or {}
        return {
            "id": bvid,
            "title": view.get("title", "未知标题"),
            "thumbnail": self._normalize_image_url(view.get("pic", "")),
            "duration": view.get("duration"),
            "duration_string": self._format_duration(view.get("duration")),
            "uploader": owner.get("name", "未知"),
            "platform": "BiliBili",
            "view_count": stat.get("view"),
            "upload_date": time.strftime("%Y%m%d", time.localtime(view.get("pubdate", 0))) if view.get("pubdate") else "",
            "description": (view.get("desc") or "")[:200],
            "formats": formats,
            "subtitles": [s.get("lan") for s in (view.get("subtitle", {}).get("list") or []) if s.get("lan")],
            "automatic_captions": [],
        }

    def _extract_bilibili_api_formats(self, play: dict) -> list:
        formats = []
        seen = set()

        for item in play.get("durl") or []:
            quality = play.get("quality") or 16
            url = item.get("url")
            if not url:
                continue
            key = ("mp4", quality)
            if key in seen:
                continue
            seen.add(key)

            size = item.get("size")
            height_label = {
                112: "1080P+",
                80: "1080P",
                64: "720P",
                32: "480P",
                16: "360P",
            }.get(quality, f"QN{quality}")
            formats.append({
                "format_id": f"bilibili_api:mp4:{quality}",
                "ext": "mp4",
                "resolution": height_label,
                "height": 1080 if quality in (80, 112) else 720 if quality == 64 else 480 if quality == 32 else 360,
                "filesize": size,
                "filesize_approx": size,
                "vcodec": "h264",
                "acodec": "aac",
                "has_audio": True,
                "label": f"{height_label} MP4 ({self._format_filesize(size)})",
            })

        dash = play.get("dash") or {}
        for video in dash.get("video") or []:
            base_url = video.get("baseUrl") or video.get("base_url")
            height = video.get("height") or 0
            bandwidth = video.get("bandwidth")
            codecs = video.get("codecs") or "video"
            if not base_url or not height:
                continue
            key = ("dash", height, codecs)
            if key in seen:
                continue
            seen.add(key)

            formats.append({
                "format_id": f"bilibili_api:dash:{video.get('id', height)}:{height}",
                "ext": "mp4",
                "resolution": f"{video.get('width', '?')}x{height}",
                "height": height,
                "filesize": None,
                "filesize_approx": None,
                "vcodec": codecs,
                "acodec": None,
                "has_audio": False,
                "label": f"{height}p MP4 (仅视频, {self._format_filesize(bandwidth)}/s)",
            })

        formats.sort(key=lambda item: (not item["has_audio"], -item["height"]))
        return formats[:15]

    def parse_video(self, url: str) -> dict:
        """解析视频信息，不下载文件"""
        _ensure_platform_reachable(url)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
        }
        ydl_opts.update(ytdlp_options_for_url(url))
        if is_bilibili_url(url):
            ydl_opts["http_headers"] = BILIBILI_HEADERS

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            if is_bilibili_url(url):
                return self._parse_bilibili_api(url)
            if detect_china_platform(url):
                raise ValueError(platform_error(url, exc)) from exc
            raise

        if not info:
            raise ValueError("无法解析该链接")

        detected_platform = detect_china_platform(url)
        assume_muxed = bool(
            detected_platform
            and detected_platform.key in {"iqiyi", "youku", "mgtv", "tencent"}
        )
        formats = self._extract_formats(info, assume_muxed=assume_muxed)
        if detected_platform and not formats:
            raise ValueError(
                f"{detected_platform.name}未返回公开的非 DRM 视频流；"
                "该内容可能需要登录、会员权限或受地区限制"
            )
        platform = display_platform_name(
            url,
            info.get("extractor", info.get("extractor_key", "Unknown")),
        )

        return {
            "id": info.get("id", ""),
            "title": info.get("title", "未知标题"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "duration_string": self._format_duration(info.get("duration")),
            "uploader": info.get("uploader", info.get("channel", "未知")),
            "platform": platform,
            "view_count": info.get("view_count"),
            "upload_date": info.get("upload_date", ""),
            "description": (info.get("description") or "")[:200],
            "formats": formats,
            "subtitles": list(info.get("subtitles", {}).keys()),
            "automatic_captions": list(info.get("automatic_captions", {}).keys())[:5],
        }

    def _extract_formats(self, info: dict, assume_muxed: bool = False) -> list:
        """从 yt-dlp info 中提取并整理可用格式，兼容视频和纯音频平台。"""
        raw_formats = info.get("formats", [])
        if not raw_formats and info.get("url"):
            raw_formats = [info]
        if not raw_formats:
            return []

        seen = set()
        results = []

        for f in raw_formats:
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            height = f.get("height")
            width = f.get("width")
            ext = f.get("ext", "mp4")
            abr = f.get("abr") or f.get("tbr")

            has_video = (
                vcodec != "none"
                if vcodec is not None
                else bool(height or width or f.get("video_ext"))
            )
            has_audio = (
                acodec != "none"
                if acodec is not None
                else bool(has_video and not f.get("audio_ext"))
            )
            if assume_muxed and has_video:
                has_audio = True
                if acodec in (None, "none"):
                    acodec = "unknown"

            if not has_video and not has_audio:
                continue

            filesize = f.get("filesize") or f.get("filesize_approx")
            size_label = self._format_filesize(filesize)

            if has_video:
                resolution = f"{width or '?'}x{height}" if height else "未知"
            else:
                resolution = f"{int(abr)}kbps" if abr else "音频"

            if has_video and has_audio:
                label = f"{height}p {ext.upper()} ({size_label})"
                key = (height, ext, "av")
            elif has_video:
                label = f"{height}p {ext.upper()} (仅视频, {size_label})"
                key = (height, ext, "v")
            else:
                bitrate_label = f"{int(abr)}kbps" if abr else "音频"
                label = f"{bitrate_label} {ext.upper()} ({size_label})"
                key = (abr, ext, "a")

            if key in seen:
                continue
            seen.add(key)

            results.append({
                "format_id": f.get("format_id", ""),
                "ext": ext,
                "resolution": resolution,
                "height": height or 0,
                "filesize": filesize,
                "filesize_approx": filesize,
                "vcodec": vcodec if has_video else None,
                "acodec": acodec if has_audio else None,
                "has_audio": has_audio,
                "is_audio_only": bool(has_audio and not has_video),
                "label": label,
            })

        results.sort(
            key=lambda x: (
                0 if x.get("has_audio") and x.get("height", 0) > 0 else 1 if x.get("height", 0) > 0 else 2,
                -x.get("height", 0),
                -(x.get("filesize") or x.get("filesize_approx") or 0),
            )
        )

        if not any(r["has_audio"] for r in results) and results:
            best_video = results[0]
            merged = {
                **best_video,
                "format_id": f"bestvideo+bestaudio/best",
                "label": f"{best_video['height']}p 最佳 (视频+音频合并)",
                "has_audio": True,
                "acodec": "merged",
            }
            results.insert(0, merged)

        return results[:15]

    def download_video(self, url: str, format_id: str) -> dict:
        """下载视频到服务器临时目录，返回文件路径和元数据"""
        _ensure_platform_reachable(url)
        if is_bilibili_url(url) and _is_bilibili_api_format(format_id):
            return self._download_bilibili_api(url, format_id)

        if not self.has_ffmpeg and "+" in format_id:
            format_id = "best"

        ydl_opts = {
            "format": format_id,
            "outtmpl": os.path.join(self.DOWNLOAD_DIR, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        ydl_opts.update(ytdlp_options_for_url(url))
        if is_bilibili_url(url):
            ydl_opts["http_headers"] = BILIBILI_HEADERS

        if self.has_ffmpeg:
            ydl_opts["ffmpeg_location"] = self.ffmpeg_path
            ydl_opts["merge_output_format"] = "mp4"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:
            if detect_china_platform(url):
                raise ValueError(platform_error(url, exc)) from exc
            raise

        if not info:
            raise ValueError("下载失败")

        title = self._sanitize_filename(info.get("title", "video"))
        ext = info.get("ext", "mp4")
        filename = f"{title}.{ext}"
        filepath = os.path.join(self.DOWNLOAD_DIR, filename)

        if not os.path.exists(filepath):
            prepared = ydl.prepare_filename(info)
            if os.path.exists(prepared):
                filepath = prepared
                filename = os.path.basename(prepared)
            else:
                for f in os.listdir(self.DOWNLOAD_DIR):
                    if title in f:
                        filepath = os.path.join(self.DOWNLOAD_DIR, f)
                        filename = f
                        break

        return {
            "filepath": filepath,
            "filename": filename,
            "title": info.get("title", "video"),
            "ext": ext,
        }

    def _resolve_bilibili_api_direct_url(self, url: str, format_id: str) -> dict:
        view = self._get_bilibili_view(url)
        bvid = view["bvid"]
        pages = view.get("pages") or []
        cid = view.get("cid") or (pages[0].get("cid") if pages else None)
        if not cid:
            raise ValueError("B 站视频缺少 cid，无法获取播放地址")

        parts = format_id.split(":")
        if len(parts) < 3:
            raise ValueError("B 站格式参数无效")

        if parts[1] == "mp4":
            qn = int(parts[2])
            play = self._get_bilibili_playurl(bvid, cid, qn=qn, fnval=0)
            durls = play.get("durl") or []
            if not durls:
                raise ValueError("B 站未返回 MP4 下载地址")
            direct_url = durls[0].get("url")
            filesize = durls[0].get("size")
            ext = "mp4"
        elif parts[1] == "dash":
            target_height = int(parts[3]) if len(parts) > 3 else 0
            play = self._get_bilibili_playurl(bvid, cid, qn=max(target_height, 80), fnval=16)
            videos = (play.get("dash") or {}).get("video") or []
            picked = next((v for v in videos if int(v.get("height") or 0) == target_height), None) or (videos[0] if videos else None)
            if not picked:
                raise ValueError("B 站未返回 DASH 视频地址")
            direct_url = picked.get("baseUrl") or picked.get("base_url")
            filesize = None
            ext = "mp4"
        else:
            raise ValueError("不支持的 B 站格式")

        if not direct_url:
            raise ValueError("B 站未返回可用直链")

        return {
            "direct_url": direct_url,
            "ext": ext,
            "filesize": filesize,
            "title": view.get("title", "video"),
            "headers": self._bilibili_headers(bvid),
        }

    def _download_bilibili_api(self, url: str, format_id: str) -> dict:
        direct = self._resolve_bilibili_api_direct_url(url, format_id)
        title = self._sanitize_filename(direct.get("title") or "bilibili_video")
        ext = direct.get("ext", "mp4")
        filename = f"{title}.{ext}"
        filepath = os.path.join(self.DOWNLOAD_DIR, filename)

        with httpx.Client(follow_redirects=True, timeout=120) as client:
            with client.stream("GET", direct["direct_url"], headers=direct["headers"]) as resp:
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_bytes():
                        if chunk:
                            f.write(chunk)

        return {
            "filepath": filepath,
            "filename": filename,
            "title": direct.get("title", "video"),
            "ext": ext,
        }

    def get_direct_url(self, url: str, format_id: str) -> dict:
        """获取视频直链"""
        _ensure_platform_reachable(url)
        if is_bilibili_url(url) and _is_bilibili_api_format(format_id):
            direct = self._resolve_bilibili_api_direct_url(url, format_id)
            return {
                "direct_url": direct["direct_url"],
                "ext": direct["ext"],
                "filesize": direct["filesize"],
                "title": direct["title"],
            }

        ydl_opts = {
            "format": format_id,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        ydl_opts.update(ytdlp_options_for_url(url))
        if is_bilibili_url(url):
            ydl_opts["http_headers"] = BILIBILI_HEADERS

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            if detect_china_platform(url):
                raise ValueError(platform_error(url, exc)) from exc
            raise

        if not info:
            raise ValueError("无法获取直链")

        direct_url = info.get("url")
        if not direct_url:
            requested = info.get("requested_formats")
            if requested and len(requested) > 0:
                direct_url = requested[0].get("url")

        if not direct_url:
            raise ValueError("该视频不支持直链下载，请使用服务端下载模式")

        return {
            "direct_url": direct_url,
            "ext": info.get("ext", "mp4"),
            "filesize": info.get("filesize") or info.get("filesize_approx"),
            "title": info.get("title", "video"),
        }
