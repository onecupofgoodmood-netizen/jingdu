"""Supported platform metadata for the public API and frontend display."""

import yt_dlp


PLATFORM_GROUPS = [
    {
        "key": "video",
        "name": "视频平台",
        "platforms": [
            "YouTube",
            "Bilibili",
            "抖音",
            "TikTok",
            "爱奇艺",
            "优酷",
            "芒果TV",
            "腾讯视频",
            "快手",
            "Vimeo",
            "Dailymotion",
            "Twitch",
            "Niconico",
            "微博视频",
        ],
    },
    {
        "key": "audio",
        "name": "音频平台",
        "platforms": [
            "SoundCloud",
            "Bandcamp",
            "Mixcloud",
            "Audiomack",
            "Podcast",
            "YouTube Music",
        ],
    },
    {
        "key": "social",
        "name": "社交媒体",
        "platforms": [
            "Instagram",
            "Facebook",
            "X / Twitter",
            "Reddit",
            "Pinterest",
            "Tumblr",
            "LinkedIn",
        ],
    },
]


SPECIAL_SUPPORT = [
    {
        "name": "Bilibili",
        "mode": "yt-dlp + 官方公开 API 兜底",
        "notes": "降低 412 拦截导致解析失败的概率",
    },
    {
        "name": "抖音",
        "mode": "专用解析模块",
        "notes": "支持常见分享链接和无水印视频地址解析",
    },
    {
        "name": "快手",
        "mode": "专用解析模块 + 通用解析兜底",
        "notes": "支持公开分享短链接和视频详情页",
    },
    {
        "name": "爱奇艺 / 优酷 / 芒果TV / 腾讯视频",
        "mode": "平台专用提取器 + HLS 格式兼容",
        "notes": "支持公开、非 DRM、当前地区可访问的视频流",
    },
]


def get_supported_platforms() -> dict:
    extractors = yt_dlp.extractor.gen_extractors()
    return {
        "engine": "yt-dlp",
        "yt_dlp_version": yt_dlp.version.__version__,
        "extractor_count": len(extractors),
        "groups": PLATFORM_GROUPS,
        "special_support": SPECIAL_SUPPORT,
        "notice": "请仅解析和下载你拥有版权、已获授权或平台允许保存的内容。",
    }
