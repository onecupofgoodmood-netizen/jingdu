import os
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import unquote

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from downloader import VideoDownloader
from douyin import DouyinParser, is_douyin_url
from iqiyi import IqiyiParser, is_iqiyi_url
from kuaishou import KuaishouParser, is_kuaishou_url
from youku import YoukuParser, is_youku_url
from site_775069 import Site775069Parser, is_775069_url
from database import init_db
from platforms import get_supported_platforms


downloader = VideoDownloader()
douyin_parser = DouyinParser(download_dir=downloader.DOWNLOAD_DIR)
iqiyi_parser = IqiyiParser(download_dir=downloader.DOWNLOAD_DIR)
kuaishou_parser = KuaishouParser(download_dir=downloader.DOWNLOAD_DIR)
youku_parser = YoukuParser(download_dir=downloader.DOWNLOAD_DIR)
site_775069_parser = Site775069Parser(download_dir=downloader.DOWNLOAD_DIR)


def _parse_kuaishou(url: str) -> dict:
    try:
        return kuaishou_parser.parse(url)
    except Exception as custom_error:
        try:
            return downloader.parse_video(url)
        except Exception:
            raise custom_error


def _download_kuaishou(url: str, format_id: str) -> dict:
    try:
        return kuaishou_parser.download(url, format_id)
    except Exception as custom_error:
        try:
            return downloader.download_video(url, format_id)
        except Exception:
            raise custom_error


def _direct_kuaishou(url: str, format_id: str) -> dict:
    try:
        return kuaishou_parser.get_direct_url(url, format_id)
    except Exception as custom_error:
        try:
            return downloader.get_direct_url(url, format_id)
        except Exception:
            raise custom_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    download_dir = downloader.DOWNLOAD_DIR
    if os.path.exists(download_dir):
        for f in os.listdir(download_dir):
            try:
                os.remove(os.path.join(download_dir, f))
            except OSError:
                pass


app = FastAPI(
    title="镜读 API",
    description="基于 yt-dlp 的视频内容分析与下载服务，支持 1800+ 平台",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ParseRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: str = "bestvideo+bestaudio/best"


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "镜读服务运行中"}


@app.get("/api/platforms")
async def supported_platforms():
    return {"success": True, "data": get_supported_platforms()}


@app.post("/api/parse")
async def parse_video(req: ParseRequest):
    """解析视频信息（抖音、快手走专用适配，其他走 yt-dlp）"""
    try:
        loop = asyncio.get_event_loop()
        if is_775069_url(req.url):
            result = await loop.run_in_executor(None, site_775069_parser.parse, req.url)
        elif is_iqiyi_url(req.url):
            result = await loop.run_in_executor(None, iqiyi_parser.parse, req.url)
        elif is_youku_url(req.url):
            result = await loop.run_in_executor(None, youku_parser.parse, req.url)
        elif is_douyin_url(req.url):
            result = await loop.run_in_executor(None, douyin_parser.parse, req.url)
        elif is_kuaishou_url(req.url):
            result = await loop.run_in_executor(None, _parse_kuaishou, req.url)
        else:
            result = await loop.run_in_executor(None, downloader.parse_video, req.url)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail={
            "success": False,
            "error": f"解析失败: {str(e)}"
        })


@app.post("/api/download")
async def download_video(req: DownloadRequest):
    """服务端下载视频后提供文件下载（抖音走专用模块）"""
    try:
        loop = asyncio.get_event_loop()
        if is_775069_url(req.url):
            result = await loop.run_in_executor(
                None, site_775069_parser.download, req.url, req.format_id
            )
        elif is_iqiyi_url(req.url):
            result = await loop.run_in_executor(
                None, iqiyi_parser.download, req.url, req.format_id
            )
        elif is_youku_url(req.url):
            result = await loop.run_in_executor(
                None, youku_parser.download, req.url, req.format_id
            )
        elif is_douyin_url(req.url):
            result = await loop.run_in_executor(None, douyin_parser.download, req.url)
        elif is_kuaishou_url(req.url):
            result = await loop.run_in_executor(
                None, _download_kuaishou, req.url, req.format_id
            )
        else:
            result = await loop.run_in_executor(
                None, downloader.download_video, req.url, req.format_id
            )
        filepath = result["filepath"]
        if not os.path.exists(filepath):
            raise HTTPException(status_code=500, detail="下载的文件不存在")

        return FileResponse(
            path=filepath,
            filename=result["filename"],
            media_type="application/octet-stream",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail={
            "success": False,
            "error": f"下载失败: {str(e)}"
        })



class Parse775069DataRequest(BaseModel):
    url: str
    video_id: str
    sid: str
    nid: str
    playdata_json: str


@app.post("/api/parse/775069-data")
async def parse_775069_from_browser(req: Parse775069DataRequest):
    """接收浏览器端获取的 playdata JSON，由后端解析为统一格式"""
    import json as _json
    try:
        play_data = _json.loads(req.playdata_json)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=400, detail={
            "success": False, "error": "播放数据 JSON 格式无效"
        })

    try:
        media_url = play_data.get("url") or (play_data.get("p") or {}).get("url") or ""
        if not media_url:
            raise ValueError("播放数据中未找到视频地址")

        loop = asyncio.get_event_loop()
        # Parse the page HTML in background if needed for metadata
        page_url = req.url
        video_id = req.video_id
        sid = req.sid
        nid = req.nid

        # Use site_775069_parser for metadata extraction from page
        try:
            # Try fetching page for title/thumbnail
            html = await loop.run_in_executor(None, site_775069_parser._fetch_text, page_url)
            title = site_775069_parser._extract_title(html) or f"775069_{video_id}_{sid}_{nid}"
            thumbnail = site_775069_parser._extract_thumbnail(html, page_url)
            view_count = site_775069_parser._extract_view_count(html)
            upload_date = site_775069_parser._extract_upload_date(html)
        except Exception:
            title = f"775069_{video_id}_{sid}_{nid}"
            thumbnail = ""
            view_count = None
            upload_date = ""

        result = {
            "id": f"{video_id}-{sid}-{nid}",
            "title": title,
            "thumbnail": thumbnail,
            "duration": None,
            "duration_string": "00:00",
            "uploader": "775069.xyz",
            "platform": "775069.xyz",
            "view_count": view_count,
            "upload_date": upload_date,
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
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail={
            "success": False, "error": f"解析失败: {str(e)}"
        })



@app.post("/api/direct-url")
async def get_direct_url(req: DownloadRequest):
    """获取视频直链"""
    try:
        loop = asyncio.get_event_loop()
        if is_775069_url(req.url):
            result = await loop.run_in_executor(
                None, site_775069_parser.get_direct_url, req.url, req.format_id
            )
        elif is_iqiyi_url(req.url):
            result = await loop.run_in_executor(
                None, iqiyi_parser.get_direct_url, req.url, req.format_id
            )
        elif is_youku_url(req.url):
            result = await loop.run_in_executor(
                None, youku_parser.get_direct_url, req.url, req.format_id
            )
        elif is_kuaishou_url(req.url):
            result = await loop.run_in_executor(
                None, _direct_kuaishou, req.url, req.format_id
            )
        else:
            result = await loop.run_in_executor(
                None, downloader.get_direct_url, req.url, req.format_id
            )
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail={
            "success": False,
            "error": f"获取直链失败: {str(e)}"
        })


@app.get("/api/iqiyi/playlist/{token}.m3u8")
async def iqiyi_playlist(token: str):
    """Serve a short-lived, signed iQiyi HLS playlist."""
    try:
        playlist = iqiyi_parser.get_playlist(token)
        return StreamingResponse(
            iter([playlist.encode("utf-8")]),
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/proxy/thumbnail")
async def proxy_thumbnail(url: str = Query(..., description="缩略图URL")):
    """代理获取视频缩略图，绕过防盗链"""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": url,
            })
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return StreamingResponse(
                iter([resp.content]),
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except Exception:
        raise HTTPException(status_code=502, detail="缩略图加载失败")


# 挂载功能模块路由
from api_summarize import router as summarize_router
from api_auth import router as auth_router
from api_payment import router as payment_router

app.include_router(summarize_router)
app.include_router(auth_router)
app.include_router(payment_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
