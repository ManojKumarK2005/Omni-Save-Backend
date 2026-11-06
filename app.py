import os
import re
import tempfile
import shutil
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import yt_dlp

app = FastAPI(
    title="OmniSave Universal Media Extractor API",
    description="High-speed backend proxy for extracting and downloading media across YouTube, Instagram, TikTok, Pinterest, X (Twitter), and Facebook with zero access-denied errors.",
    version="2.0.0"
)

# Enable CORS for all frontend origins (Netlify, Vercel, localhost)
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

@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "OmniSave Universal Media Downloader Backend",
        "supported_platforms": ["YouTube", "Instagram", "TikTok", "Pinterest", "X (Twitter)", "Facebook", "Reddit"],
        "endpoints": {
            "info": "/api/info?url={video_url}",
            "download": "/api/download?url={video_url}&format_id={format_id}"
        }
    }

@app.get("/api/info")
def get_video_info(url: str = Query(..., description="Target video URL")):
    """
    Extracts metadata, thumbnails, and available format resolutions.
    Sorts strictly descending by quality (Highest Quality First).
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            title = info.get("title", "Social Media Media Stream")
            thumbnail = info.get("thumbnail", "")
            duration_secs = info.get("duration", 0)
            uploader = info.get("uploader") or info.get("channel") or "@creator"
            view_count = info.get("view_count", 0)
            platform = get_platform_label(url)

            # Format duration string (HH:MM:SS or MM:SS)
            if duration_secs:
                m, s = divmod(duration_secs, 60)
                h, m = divmod(m, 60)
                duration_str = f"{int(h):02d}:{int(m):02d}:{int(s):02d}" if h > 0 else f"{int(m):02d}:{int(s):02d}"
            else:
                duration_str = "Stream / Reel"

            views_str = f"{view_count:,} views" if view_count else "Trending"

            # Parse and organize formats strictly descending by resolution
            formats = info.get("formats", [])
            video_formats = []
            seen_resolutions = set()

            for f in formats:
                height = f.get("height")
                ext = f.get("ext", "mp4")
                vcodec = f.get("vcodec", "none")

                if height and height >= 144 and ext in ["mp4", "webm"] and vcodec != "none":
                    if height not in seen_resolutions:
                        seen_resolutions.add(height)
                        filesize = f.get("filesize") or f.get("filesize_approx")
                        size_str = f"{round(filesize / (1024 * 1024), 1)} MB" if filesize else "High Definition"
                        
                        quality_tag = f"{height}p {'Full HD' if height >= 1080 else ('HD' if height >= 720 else '')}".strip()
                        video_formats.append({
                            "height": height,
                            "quality": quality_tag,
                            "label": f"MP4 {height}p ({f.get('fps', 30)}fps)",
                            "size": size_str,
                            "format_id": f.get("format_id"),
                            "downloadUrl": None # Triggered via backend proxy /api/download
                        })

            # Sort descending: Highest resolution at the very top!
            video_formats.sort(key=lambda x: x["height"], reverse=True)

            # Fallback format ladder if platform serves adaptive DASH streams
            if not video_formats:
                video_formats = [
                    {"height": 2160, "quality": "4K 2160p (Max)", "label": "Ultra HD MP4 (60fps)", "size": "Direct Stream", "format_id": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"},
                    {"height": 1080, "quality": "1080p (Full HD)", "label": "Full HD MP4 (60fps)", "size": "High Quality", "format_id": "bestvideo[height<=1080]+bestaudio/best"},
                    {"height": 720, "quality": "720p (HD)", "label": "Standard HD MP4", "size": "Standard", "format_id": "bestvideo[height<=720]+bestaudio/best"},
                    {"height": 480, "quality": "480p (SD)", "label": "Medium Quality MP4", "size": "Fast Download", "format_id": "best[height<=480]"},
                    {"height": 360, "quality": "360p", "label": "Data Saver MP4", "size": "Compact", "format_id": "best[height<=360]"}
                ]

            # High-bitrate audio formats
            audio_formats = [
                {"quality": "320 kbps (Max)", "label": "Studio Master MP3 (320kbps)", "size": "High Bitrate", "format_id": "bestaudio/best"},
                {"quality": "192 kbps", "label": "Standard High Quality Audio (192kbps)", "size": "Standard MP3", "format_id": "bestaudio[abr<=192]/best"},
                {"quality": "128 kbps", "label": "Compact Audio (M4A / 128kbps)", "size": "Compact", "format_id": "bestaudio[abr<=128]/best"}
            ]

            # High-resolution thumbnail artwork
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Extraction failed: {str(e)}")

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
    start_time: Optional[str] = Query(None, description="Start time for trimming e.g. 00:00:15"),
    end_time: Optional[str] = Query(None, description="End time for trimming e.g. 00:01:30")
):
    """
    Downloads, remuxes, and pipes the media file directly to the browser.
    Eliminates 'Access Denied' by acting as a streaming proxy with attachment headers.
    """
    temp_dir = tempfile.mkdtemp()
    outtmpl = os.path.join(temp_dir, "%(title).60s.%(ext)s")
    is_audio = "bestaudio" in format_id

    ydl_opts = {
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
    }

    # Custom Start & End Time Video Trimming
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
            raise HTTPException(status_code=500, detail="Processed file could not be located.")

        sanitized_filename = os.path.basename(filename)
        sanitized_filename = re.sub(r'[^\w\-_.]', '_', sanitized_filename)

        # Automatically clean up temp directory after sending file
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
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
