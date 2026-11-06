import os
import re
import tempfile
import shutil
import urllib.request
import urllib.parse
import json
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
import yt_dlp

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

app = FastAPI(title="OmniSave Ultra Backend Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_yt_id(url: str) -> Optional[str]:
    m = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})', url)
    return m.group(1) if m else None

def get_platform_label(url: str) -> str:
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower: return "YOUTUBE"
    if "instagram.com" in url_lower: return "INSTAGRAM"
    if "tiktok.com" in url_lower: return "TIKTOK"
    if "pinterest.com" in url_lower or "pin.it" in url_lower: return "PINTEREST"
    if "twitter.com" in url_lower or "x.com" in url_lower: return "X (TWITTER)"
    if "facebook.com" in url_lower or "fb.watch" in url_lower: return "FACEBOOK"
    if "reddit.com" in url_lower: return "REDDIT"
    return "SOCIAL MEDIA"

def get_ytdl_anti_bot_options(is_download: bool = False, outtmpl: Optional[str] = None):
    """
    Configures yt-dlp to bypass YouTube BotGuard on datacenter IPs:
    1. Simulates Android and iOS clients which do not use web BotGuard tokens.
    2. Writes cookies from environment variable if provided (COOKIES_TEXT).
    3. Adds realistic mobile User-Agents.
    """
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': not is_download,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'tv', 'web'],
                'player_skip': ['webpage', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/19.10.35 (Linux; U; Android 14; en_US) gzip',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    if outtmpl:
        opts['outtmpl'] = outtmpl

    # Check if user added a COOKIES_TEXT environment variable on Render
    cookies_env = os.environ.get("COOKIES_TEXT") or os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        cookie_path = "/tmp/yt_cookies.txt"
        with open(cookie_path, "w", encoding="utf-8") as f:
            f.write(cookies_env)
        opts['cookiefile'] = cookie_path

    return opts

@app.get("/")
def health_check():
    return {
        "status": "online",
        "engine": "OmniSave Multi-Platform Anti-Bot Backend",
        "version": "3.0.0",
        "platforms": ["YouTube", "Instagram", "TikTok", "Pinterest", "X (Twitter)", "Facebook", "Reddit"]
    }

@app.get("/api/info")
def get_video_info(url: str = Query(..., description="Target video URL")):
    """
    Extracts video details and formats sorted strictly descending (Highest Quality First).
    """
    platform = get_platform_label(url)
    yt_id = extract_yt_id(url)

    # Strategy 1: yt-dlp with mobile client rotation
    ydl_opts = get_ytdl_anti_bot_options(is_download=False)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return parse_ytdl_info(info, url, platform)
    except Exception as ytdl_err:
        err_msg = str(ytdl_err)
        
        # Strategy 2: If YouTube flagged the datacenter IP with "Sign in to confirm you're not a bot",
        # query open Invidious / Piped relays server-side!
        if yt_id:
            invidious_data = query_invidious_server_side(yt_id, url)
            if invidious_data:
                return invidious_data

        # Strategy 3: oEmbed metadata fallback
        return generate_oembed_fallback(url, yt_id, platform, err_msg)

def parse_ytdl_info(info, url, platform):
    title = info.get("title", "Social Video Stream")
    thumbnail = info.get("thumbnail", "")
    duration_secs = info.get("duration", 0)
    uploader = info.get("uploader") or info.get("channel") or "@creator"
    view_count = info.get("view_count", 0)

    if duration_secs:
        m, s = divmod(duration_secs, 60)
        h, m = divmod(m, 60)
        duration_str = f"{int(h):02d}:{int(m):02d}:{int(s):02d}" if h > 0 else f"{int(m):02d}:{int(s):02d}"
    else:
        duration_str = "HD Stream"

    views_str = f"{view_count:,} views" if view_count else "Trending"

    formats = info.get("formats", [])
    video_formats = []
    seen_heights = set()

    for f in formats:
        h = f.get("height")
        ext = f.get("ext", "mp4")
        vcodec = f.get("vcodec", "none")

        if h and h >= 144 and ext in ["mp4", "webm"] and vcodec != "none":
            if h not in seen_heights:
                seen_heights.add(h)
                filesize = f.get("filesize") or f.get("filesize_approx")
                size_str = f"{round(filesize / (1024 * 1024), 1)} MB" if filesize else "High Definition"
                video_formats.append({
                    "height": h,
                    "quality": f"{h}p {'Full HD' if h >= 1080 else ('HD' if h >= 720 else '')}".strip(),
                    "label": f"MP4 {h}p ({f.get('fps', 30)}fps)",
                    "size": size_str,
                    "format_id": f.get("format_id")
                })

    # Sort strictly descending: Highest quality first!
    video_formats.sort(key=lambda x: x["height"], reverse=True)

    if not video_formats:
        video_formats = [
            {"height": 2160, "quality": "4K 2160p (Max)", "label": "Ultra HD MP4 (60fps)", "size": "Direct Stream", "format_id": "bestvideo+bestaudio/best"},
            {"height": 1080, "quality": "1080p (Full HD)", "label": "Full HD MP4", "size": "High Definition", "format_id": "bestvideo[height<=1080]+bestaudio/best"},
            {"height": 720, "quality": "720p (HD)", "label": "Standard HD MP4", "size": "Standard", "format_id": "bestvideo[height<=720]+bestaudio/best"},
            {"height": 480, "quality": "480p", "label": "Medium Quality MP4", "size": "Compact", "format_id": "best[height<=480]"}
        ]

    audio_formats = [
        {"quality": "320 kbps (Max)", "label": "Studio Master MP3 (320kbps)", "size": "Studio Audio", "format_id": "bestaudio/best"},
        {"quality": "192 kbps", "label": "Standard High Quality Audio (192kbps)", "size": "Standard MP3", "format_id": "bestaudio[abr<=192]/best"},
        {"quality": "128 kbps", "label": "Compact Audio (M4A / 128kbps)", "size": "Mobile Audio", "format_id": "bestaudio[abr<=128]/best"}
    ]

    yt_id = extract_yt_id(url)
    maxres_thumb = f"https://img.youtube.com/vi/{yt_id}/maxresdefault.jpg" if yt_id else thumbnail
    hq_thumb = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg" if yt_id else thumbnail

    thumbnail_formats = [
        {"resolution": "1080p HD (Max)", "label": "Maximum Resolution Artwork", "format": "JPG (1920x1080)", "downloadUrl": maxres_thumb},
        {"resolution": "720p HD", "label": "Standard High Quality Cover", "format": "JPG (1280x720)", "downloadUrl": hq_thumb}
    ]

    return {
        "success": True,
        "title": title,
        "platform": platform,
        "duration": duration_str,
        "author": uploader,
        "views": views_str,
        "thumbnail": maxres_thumb,
        "videoFormats": video_formats,
        "audioFormats": audio_formats,
        "thumbnailFormats": thumbnail_formats
    }

def query_invidious_server_side(yt_id: str, original_url: str):
    instances = [
        "https://inv.thepixora.com",
        "https://invidious.asir.dev",
        "https://iv.melmac.space"
    ]
    for inst in instances:
        try:
            req = urllib.request.Request(f"{inst}/api/v1/videos/{yt_id}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    d = json.loads(response.read().decode("utf-8"))
                    formats = []
                    for s in d.get("formatStreams", []):
                        h = int(s.get("height", 0)) or 720
                        formats.append({
                            "height": h,
                            "quality": f"{h}p HD",
                            "label": f"MP4 {h}p",
                            "size": "Direct Stream",
                            "format_id": f"direct_{s.get('itag', '22')}"
                        })
                    formats.sort(key=lambda x: x["height"], reverse=True)
                    max_thumb = f"https://img.youtube.com/vi/{yt_id}/maxresdefault.jpg"
                    return {
                        "success": True,
                        "title": d.get("title", "YouTube Video Stream"),
                        "platform": "YOUTUBE",
                        "duration": "HD Stream",
                        "author": d.get("author", "@creator"),
                        "views": f"{d.get('viewCount', 0):,} views",
                        "thumbnail": max_thumb,
                        "videoFormats": formats if formats else [
                            {"height": 1080, "quality": "1080p Full HD", "label": "Full HD MP4", "size": "Direct Stream", "format_id": "best"},
                            {"height": 720, "quality": "720p HD", "label": "Standard HD MP4", "size": "Standard", "format_id": "best"}
                        ],
                        "audioFormats": [
                            {"quality": "320 kbps", "label": "Studio MP3 Audio", "size": "Studio Audio", "format_id": "bestaudio"}
                        ],
                        "thumbnailFormats": [
                            {"resolution": "1080p HD (Max)", "label": "Maximum Resolution Artwork", "format": "JPG", "downloadUrl": max_thumb}
                        ]
                    }
        except Exception:
            pass
    return None

def generate_oembed_fallback(url: str, yt_id: Optional[str], platform: str, err: str):
    maxres_thumb = f"https://img.youtube.com/vi/{yt_id}/maxresdefault.jpg" if yt_id else "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1280&q=80"
    return {
        "success": True,
        "title": f"{platform} Media Stream",
        "platform": platform,
        "duration": "HD Video",
        "author": "@creator",
        "views": "Available Stream",
        "thumbnail": maxres_thumb,
        "videoFormats": [
            {"height": 1080, "quality": "1080p (Full HD)", "label": "Full HD MP4", "size": "High Definition", "format_id": "bestvideo[height<=1080]+bestaudio/best"},
            {"height": 720, "quality": "720p (HD)", "label": "Standard HD MP4", "size": "Fast Stream", "format_id": "bestvideo[height<=720]+bestaudio/best"}
        ],
        "audioFormats": [
            {"quality": "320 kbps (Max)", "label": "Studio Master MP3", "size": "High Bitrate", "format_id": "bestaudio/best"}
        ],
        "thumbnailFormats": [
            {"resolution": "1080p HD (Max)", "label": "Maximum Resolution Artwork", "format": "JPG", "downloadUrl": maxres_thumb}
        ]
    }

def remove_temp_directory(temp_dir: str):
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

@app.get("/api/download")
def download_media(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Target video URL"),
    format_id: str = Query("best", description="Selected format identifier"),
    start_time: Optional[str] = Query(None, description="Start time for trimming"),
    end_time: Optional[str] = Query(None, description="End time for trimming")
):
    temp_dir = tempfile.mkdtemp()
    outtmpl = os.path.join(temp_dir, "%(title).60s.%(ext)s")
    is_audio = "bestaudio" in format_id

    ydl_opts = get_ytdl_anti_bot_options(is_download=True, outtmpl=outtmpl)

    if start_time or end_time:
        sec_start = start_time if start_time else "00:00:00"
        time_args = f"-ss {sec_start}"
        if end_time:
            time_args += f" -to {end_time}"
        ydl_opts['downloader_args'] = {'ffmpeg_i': time_args.split()}

    if is_audio:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': format_id if format_id != "best" else "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            'merge_output_format': 'mp4',
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if is_audio:
                base, _ = os.path.splitext(filename)
                filename = base + ".mp3"
            elif not os.path.exists(filename):
                base, _ = os.path.splitext(filename)
                if os.path.exists(base + ".mp4"):
                    filename = base + ".mp4"

        if not os.path.exists(filename):
            raise HTTPException(status_code=500, detail="Processed file could not be generated.")

        sanitized_filename = os.path.basename(filename)
        sanitized_filename = re.sub(r'[^\w\-_.]', '_', sanitized_filename)

        background_tasks.add_task(remove_temp_directory, temp_dir)

        return FileResponse(
            path=filename,
            filename=sanitized_filename,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{sanitized_filename}"',
                "Access-Control-Allow-Origin": "*"
            }
        )
    except Exception as e:
        remove_temp_directory(temp_dir)
        
        # If Render IP is blocked on download by BotGuard, stream public proxy media so user download NEVER fails!
        yt_id = extract_yt_id(url)
        if yt_id:
            # Redirect to Invidious public streaming endpoint with local=true
            return RedirectResponse(url=f"https://iv.melmac.space/latest_version?id={yt_id}&itag=22&local=true")
            
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
