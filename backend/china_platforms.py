"""Shared configuration for mainland China video platforms."""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ChinaPlatform:
    key: str
    name: str
    domains: tuple[str, ...]
    referer: str


CHINA_PLATFORMS = (
    ChinaPlatform(
        key="iqiyi",
        name="爱奇艺",
        domains=("iqiyi.com", "pps.tv", "iq.com"),
        referer="https://www.iqiyi.com/",
    ),
    ChinaPlatform(
        key="youku",
        name="优酷",
        domains=("youku.com", "tudou.com"),
        referer="https://www.youku.com/",
    ),
    ChinaPlatform(
        key="mgtv",
        name="芒果TV",
        domains=("mgtv.com", "hunantv.com"),
        referer="https://www.mgtv.com/",
    ),
    ChinaPlatform(
        key="douyin",
        name="抖音",
        domains=("douyin.com", "iesdouyin.com"),
        referer="https://www.douyin.com/",
    ),
    ChinaPlatform(
        key="kuaishou",
        name="快手",
        domains=(
            "kuaishou.com",
            "kuaishouapp.com",
            "gifshow.com",
            "chenzhongtech.com",
            "kwai.com",
            "kuai.com",
        ),
        referer="https://www.kuaishou.com/",
    ),
    ChinaPlatform(
        key="tencent",
        name="腾讯视频",
        domains=("v.qq.com", "video.qq.com", "wetv.vip"),
        referer="https://v.qq.com/",
    ),
)


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def detect_china_platform(url: str) -> Optional[ChinaPlatform]:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None

    for platform in CHINA_PLATFORMS:
        if any(_host_matches(host, domain) for domain in platform.domains):
            return platform
    return None


def ytdlp_options_for_url(url: str) -> dict:
    platform = detect_china_platform(url)
    if not platform:
        return {}

    return {
        "http_headers": {
            "User-Agent": DESKTOP_USER_AGENT,
            "Referer": platform.referer,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        "geo_bypass": True,
    }


def display_platform_name(url: str, extracted_name: str) -> str:
    platform = detect_china_platform(url)
    return platform.name if platform else extracted_name


def platform_error(url: str, error: Exception) -> str:
    platform = detect_china_platform(url)
    if not platform:
        return str(error)

    message = str(error)
    lowered = message.lower()
    if any(token in lowered for token in ("drm", "vip", "login", "sign in", "private", "付费", "会员")):
        reason = "该视频需要登录、会员权限或使用了 DRM 保护"
    elif any(token in lowered for token in ("geo", "region", "country", "地区", "版权原因")):
        reason = "该视频存在地区或版权访问限制"
    elif "can't find any video" in lowered or "no video" in lowered:
        reason = "页面中未找到公开视频，请确认使用的是单个视频详情页且内容仍可播放"
    elif "unsupported url" in lowered:
        reason = "暂时无法识别该分享链接，请尝试使用视频详情页地址"
    else:
        reason = message

    return f"{platform.name}解析失败：{reason}"
