# Video Processing Pipeline (Refactored)

## Overview

This project provides a web-based platform for downloading YouTube videos and processing them into smaller, potentially enhanced clips. It utilizes a Flask web framework, Celery for background task management, and an agent-based pattern for the initial download workflow.

The system has undergone a significant refactoring. Features like automated full-video transcription, diarization, and AI-driven Q&A/summarization have been removed from the main automated pipeline. The current focus is on robust downloading and providing tools for manual, time-based clipping (both single and batch), with plans to integrate per-clip processing (transcription, editing, metadata) via background tasks.

## Current Features

*   **YouTube Video Submission:** Submit multiple YouTube URLs via the web UI.
*   **Automated Download:** Downloads videos using `yt-dlp` via a background agent (`DownloaderAgent`). Selectable resolution.
*   **Manual Single Clip Creation:** Define start/end times on the video details page to queue a task for creating a single clip.
*   **Manual Batch Clip Creation:** Input multiple timestamps (MM:SS or seconds) to generate multiple clips from a video via a background dispatcher task. Differentiates between "Long" and "Short" format intentions.
*   **Clip Processing (Planned):** Generated clips (from manual/batch) will trigger background tasks to:
    *   Optionally edit using **Moviepy** (e.g., crop/aspect ratio change for "Short" format).
    *   Extract audio from the clip.
    *   Transcribe the clip's audio using **FasterWhisper**.
    *   Generate metadata (title, description, keywords) using the **Google Gemini API**.
*   **Job Management UI:** View list of submitted videos, their status (Pending, Downloading, Ready, Processing Clips, Error, etc.), and progress.
*   **Video Details View:** Inspect video information, view generated clips (with planned transcript/metadata display), access agent run history, and trigger reprocessing or deletion.
*   **Error Log:** View a list of jobs that encountered errors during processing.
*   **Background Task Processing:** Uses Celery and Redis for reliable background execution of downloading and clipping tasks.
*   **Agent Framework:** Uses a basic agent/tool pattern (`agents.py`, `tools.py`) for the download step.

## Technology Stack

*   **Backend:** Python 3.9+, Flask
*   **Background Tasks:** Celery, Redis
*   **Database:** SQLite
*   **Video Download:** yt-dlp
*   **Video/Audio Processing:** FFmpeg (via subprocess)
*   **Video Editing:** Moviepy (Planned Integration)
*   **Transcription (Clips):** FasterWhisper (Planned Integration via Task)
*   **AI Metadata:** Google Gemini API (Planned Integration via Task)
*   **Frontend:** HTML, Bootstrap 5, JavaScript
*   **WSGI Server:** Waitress (default production), Flask Dev Server
*   **Testing:** pytest, pytest-mock

## Architecture

The application uses a standard Flask structure. Core components include:

*   `app.py`: Main Flask application, routes, request handling, task dispatching.
*   `tasks.py`: Celery task definitions (`process_video_orchestrator_task`, `batch_cut_dispatcher_task`, new `process_clip_task`, `create_single_clip_task`).
*   `agents.py`: Agent definitions (currently only `DownloaderAgent`).
*   `tools.py`: Wrappers around utilities/APIs (Download, Media, Analysis, DB, planned Gemini/Editing tools).
*   `database.py`: SQLite schema definition, connection management, CRUD functions.
*   `config.py`: Configuration loading from `.env`.
*   `utils/`: Lower-level helper modules (`download.py`, `media_utils.py`, `error_utils.py`).
*   `analysis/`: Core analysis logic (currently `transcription.py` used by tasks).
*   `templates/`: Jinja2 HTML templates.
*   `static/`: CSS and JavaScript files.
*   `tests/`: Automated tests using pytest.

**Data Flow (Simplified):**
1.  UI -> `app.py` -> `process_video_orchestrator_task` -> `run_agent_task(DownloaderAgent)` -> Download Complete -> Status: Ready.
2.  UI (Batch Clip) -> `app.py` -> `batch_cut_dispatcher_task` -> Dispatches multiple `process_clip_task` instances.
3.  UI (Single Clip) -> `app.py` -> `create_single_clip_task` -> Executes clip processing steps.
4.  `process_clip_task` / `create_single_clip_task`: Cut (FFmpeg) -> Edit (Moviepy) -> Extract Audio (FFmpeg) -> Transcribe (FasterWhisper) -> Generate Metadata (Gemini) -> Store Results (DB).

## Setup and Installation

**Prerequisites:**

*   Python 3.9+ and pip.
*   A running Redis instance (note host/port).
*   FFmpeg and ffprobe installed and accessible via the system PATH, OR set `FFMPEG_PATH` / `FFPROBE_PATH` in `.env`.

**Steps:**

1.  **Clone Repository:**
    ```bash
    git clone <your-repository-url> video-processor
    cd video-processor
    ```
2.  **Create Virtual Environment:** (Recommended)
    ```bash
    python -m venv venv
    # Windows: .\venv\Scripts\activate
    # macOS/Linux: source venv/bin/activate
    ```
3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: PyTorch installation might require specific commands based on your system/CUDA setup. Refer to [PyTorch Get Started Locally](https://pytorch.org/get-started/locally/) if needed).*
4.  **Configure Environment:**
    *   Copy `.env.example` to `.env`.
    *   **Edit `.env`:**
        *   **CRITICAL:** Set `FLASK_SECRET_KEY` to a unique, random string.
        *   Verify `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` point to your Redis instance.
        *   Set `GEMINI_API_KEY` if using metadata generation features.
        *   (Optional) Set `FFMPEG_PATH`, `FFPROBE_PATH`.
        *   (Optional) Adjust `FASTER_WHISPER_MODEL`, paths, log level, etc.
5.  **Run the Application:** You need 3 components running simultaneously in separate terminals (ensure your virtual environment is activated in each):
    *   **Terminal 1: Redis Server:** Start your Redis server (e.g., `redis-server`).
    *   **Terminal 2: Celery Worker:**
        ```bash
        celery -A celery_app.celery_app worker --loglevel=info -P solo
        ```
        *(`-P solo` is recommended for easier debugging, especially on Windows. Remove for default prefork pool).*
    *   **Terminal 3: Flask App:**
        ```bash
        python app.py
        ```
        *(This will likely start the Waitress server).*
6.  **Access:** Open your browser to `http://localhost:5001` (or the configured port).

## Usage

1.  **Submit Videos:** Go to the Home page, paste one or more YouTube URLs into the text area, select a download resolution, and click "Add & Start Processing".
2.  **Monitor Progress:** The main table shows the status of submitted jobs. Statuses update periodically.
3.  **View Details:** Click the "Details" button for a specific video.
4.  **Manual Clipping:**
    *   **Single:** Use the "Manual Clip Creation" form, enter start/end times (seconds), and click "Queue Manual Clip Task".
    *   **Batch:** Use the "Manual Batch Cutting" section. Enter timestamps (one per line, or separated by commas/semicolons) into either the "Long Format" or "Short Format" text area. Click the corresponding "Generate [...] Batch Clips" button.
5.  **View Clips:** Generated clips (after background processing completes) will appear in the "Generated Clips" section on the details page, along with their status, planned transcript, and metadata.
6.  **Manage Jobs:** Delete individual jobs from the details page or multiple jobs using the checkboxes and "Delete Selected" button on the index page. View jobs with errors on the "Error Log" page.

## Testing

Automated tests are located in the `tests/` directory and use `pytest`.

To run tests:

1.  Ensure test dependencies are installed (`pip install pytest pytest-mock`).
2.  Navigate to the project root directory.
3.  Run the command:
    ```bash
    pytest
    ```

## Future Work / Roadmap

*   Complete Moviepy integration for automated cropping/aspect ratio changes in `process_clip_task`.
*   Complete Gemini integration for metadata generation in `process_clip_task`.
*   Implement robust status tracking and display for individual clip processing steps.
*   Refactor common logic between `process_clip_task` and `create_single_clip_task`.
*   Explore WebSocket integration to replace polling for status updates.
*   Expand test coverage.

## Contributing

*(Optional: Add contribution guidelines here if applicable).*

## License

*(Optional: Add license information here if applicable).*