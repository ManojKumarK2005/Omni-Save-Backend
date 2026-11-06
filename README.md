# OmniSave Universal Media Downloader — Backend Service

A high-performance Python FastAPI backend proxy using `yt-dlp` and `FFmpeg` to extract and stream downloads across:
* **YouTube** (Videos, Shorts, Music)
* **Instagram** (Reels, Posts, Carousels)
* **TikTok** (No-watermark MP4 & original MP3)
* **Pinterest** (Video Pins & high-res artwork)
* **X (Twitter)** (Media clips & GIFs)
* **Facebook & Reddit**

---

## 🚀 1-Click Free Deployment to Render.com (Takes 3 Minutes)

1. Create a free account on [Render.com](https://render.com/).
2. Push this backend folder to your [GitHub](https://github.com/) repository.
3. On Render, click **"New +"** ➔ **"Web Service"** and connect your GitHub repository.
4. Enter these settings:
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt && apt-get update && apt-get install -y ffmpeg`
   * **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
   * **Instance Type:** Select **Free ($0/month)**.
5. Click **"Create Web Service"**.
6. Render will generate your free HTTPS URL (e.g. `https://omnisave-api.onrender.com`).
7. Open `config.js` in your frontend and set:
   ```javascript
   API: {
     USE_MOCK_ENGINE: false,
     ENDPOINT: "https://omnisave-api.onrender.com/api/info",
     DOWNLOAD_ENDPOINT: "https://omnisave-api.onrender.com/api/download"
   }
   ```

---

## 💻 Running Locally on Your Computer

1. Open your terminal in this directory:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Ensure FFmpeg is installed:
   * **Ubuntu/Debian:** `sudo apt install -y ffmpeg`
   * **macOS:** `brew install ffmpeg`
   * **Windows:** `winget install Gyan.FFmpeg`
3. Start the server:
   ```bash
   uvicorn app:app --port 8000 --reload
   ```
4. Test in your browser: `http://localhost:8000/api/info?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ`
