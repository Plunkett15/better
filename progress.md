# Comprehensive Refactoring Implementation Plan (File-Centric View)

This plan details the anticipated modifications and deletions required across the project files to implement the agreed-upon refactoring objectives: UI updates, shifting transcription post-clipping, integrating Gemini for metadata, integrating Moviepy for editing, and addressing general code quality improvements.

---

**Affected Files and Required Work:**

*   **`app.py`**
    *   **Route `video_details`:**
        *   Remove logic fetching/passing the full `videos.transcript` data.
        *   Add logic to fetch clip data, including associated transcripts and metadata, from the new `clips`, `clip_transcripts`, and `clip_metadata` tables (or equivalent).
        *   Pass this structured clip data to the `video_details.html` template.
    *   **Route `trigger_clip_creation`:**
        *   Remove the direct call to `media_tool.create_clip` (FFmpeg execution).
        *   Implement logic to dispatch a new Celery task (e.g., `create_single_clip_task`) to handle the actual clip creation, audio extraction, transcription, editing, and metadata generation for a single clip request.
        *   Return a 202 Accepted response immediately after dispatching the task.
    *   **Route `trigger_batch_cut`:**
        *   Modify to accept an additional parameter (e.g., `clip_type="long"|"short"`) from the request payload (sent by updated `app.js`).
        *   Pass this `clip_type` parameter when dispatching the modified `batch_cut_task`.
    *   **Security:** Remove `@csrf.exempt` decorators from `trigger_clip_creation`, `trigger_batch_cut`, `trigger_reprocess_full`, and any other POST routes currently using it. Ensure Flask-WTF CSRF protection is active.

*   **`tasks.py`**
    *   **Task `process_video_orchestrator_task`:**
        *   Simplify agent dispatch logic. It should likely only dispatch `DownloaderAgent` (or nothing if `skip_download` is true and download is the only agent). Remove references to dispatching `AudioExtractorAgent` or `TranscriberAgent`.
    *   **Task `batch_cut_task`:**
        *   Major Refactor: Change from performing cuts to being a *dispatcher*.
        *   Remove the loop calling `media_tool.create_clip`.
        *   Determine segment list based on input timestamps.
        *   For each segment, dispatch a *new* `process_clip_task` (see below), passing necessary parameters (`video_id`, `start`, `end`, calculated `output_path`, `clip_type`).
        *   Implement logic using Celery `group` or `chord` to manage the parallel execution of `process_clip_task` instances and potentially update the overall video status upon completion.
        *   Remove logic that directly updated `videos.generated_clips`.
    *   **Task `run_agent_task`:**
        *   Review final `except Exception` handling logic – consider if `Ignore()` is always appropriate for unexpected errors.
        *   Ensure `autoretry_for=(ToolError,)` remains relevant for `DownloaderAgent` if it's the only agent using this task runner. *Consider if this generic runner is still needed if only `DownloaderAgent` uses it.*
    *   **New Task `process_clip_task`:**
        *   Create this new task responsible for processing a *single* clip.
        *   Accept parameters: `video_id`, `start_time`, `end_time`, `output_path`, `clip_type`.
        *   **Step 1 (Clip):** Call `media_utils.create_clip` (FFmpeg) to generate the initial clip at `output_path`.
        *   **Step 2 (Edit):** Based on `clip_type`, call new `moviepy` wrapper functions (from `media_utils.py` or `EditingTool`) to apply crop/aspect ratio changes (potentially overwriting the initial clip file).
        *   **Step 3 (Audio):** Call `media_utils.extract_audio` on the (potentially edited) clip file.
        *   **Step 4 (Transcribe):** Call `analysis.transcription.transcribe_audio` on the clip's extracted audio.
        *   **Step 5 (Store Results):** Save the final clip path and timing info to the new `clips` table. Save the transcript to the new `clip_transcripts` table.
        *   **Step 6 (Metadata):** Call the new `GeminiTool` to generate metadata (title, description, etc.).
        *   **Step 7 (Store Metadata):** Save the generated metadata to the new `clip_metadata` table (or update `clips` table).
        *   Implement robust error handling and status updates for each step within this task, updating the corresponding `clips` table record's status.
    *   **New Task `create_single_clip_task` (Optional but Recommended):**
        *   Create this new task, likely very similar to `process_clip_task`, to handle requests from the manual single clip UI form (`trigger_clip_creation` route). This ensures consistency and moves processing off the web worker.

*   **`agents.py`**
    *   **Class `AudioExtractorAgent`:**
        *   Remove the dispatch call to `TranscriberAgent`.
        *   *Consider Deletion:* If full audio extraction serves no other purpose in the refactored workflow, delete this agent class entirely.
    *   **Class `TranscriberAgent`:**
        *   Delete the entire class definition.
    *   **`AGENT_REGISTRY`:**
        *   Remove the entry for `TranscriberAgent`.
        *   Remove the entry for `AudioExtractorAgent` if the class is deleted.
    *   **Error Handling:** Review `AgentError` vs `ToolError` usage in remaining agents (likely just `DownloaderAgent`).

*   **`tools.py`**
    *   **Class `DatabaseTool`:**
        *   Refactor methods like `update_video_result` to avoid duplicating logic present in `database.py`. Either call `database.py` functions or make the Tool the single source of truth for DB interaction logic.
    *   **New Class `GeminiTool`:**
        *   Create this new class to encapsulate all interactions with the Google Gemini API.
        *   Include methods for authentication, generating metadata (e.g., `generate_metadata_for_clip(clip_path_or_transcript)`), handling API errors, rate limits, and parsing responses.
    *   **New Class `EditingTool` (Alternative to modifying `media_utils.py`):**
        *   Consider creating this tool to encapsulate `moviepy` operations (crop, resize) instead of putting wrappers directly in `media_utils.py`.
    *   **Error Handling:** Ensure `ToolError` is raised appropriately for transient or recoverable errors originating from tool operations (including new Gemini/Moviepy tools).

*   **`database.py`**
    *   **Schema Changes:**
        *   Modify `videos` table: `DROP COLUMN transcript;`. Consider `DROP COLUMN audio_path;`.
        *   Create `clips` table (columns: `id`, `video_id`, `clip_path`, `start_time`, `end_time`, `status`, `error_message`, etc.). Add `FOREIGN KEY` to `videos` with `ON DELETE CASCADE`.
        *   Create `clip_transcripts` table (columns: `id`, `clip_id`, `transcript_json`, `status`, etc.). Add `FOREIGN KEY` to `clips` with `ON DELETE CASCADE`.
        *   Create `clip_metadata` table (columns: `id`, `clip_id`, `title`, `description`, `keywords_json`, etc.). Add `FOREIGN KEY` to `clips` with `ON DELETE CASCADE`.
        *   *Migration Strategy:* Plan how to apply these changes to an existing database (e.g., using `ALTER TABLE`, creating new tables, potentially migrating existing `generated_clips` data if feasible).
    *   **Function `update_video_result`:** Consolidate logic with `DatabaseTool` or ensure it's the sole implementation.
    *   **Function `add_generated_clip`:** Likely remove or repurpose; adding clips will now involve inserting into the `clips` table.
    *   **Function `reset_video_analysis_results`:** Update to remove references to `videos.transcript`/`audio_path` and add `DELETE` statements for the new `clips`, `clip_transcripts`, `clip_metadata` tables based on `video_id`.
    *   **New Functions:** Add CRUD functions (`add_clip`, `update_clip_status`, `get_clips_for_video`, `add_clip_transcript`, `add_clip_metadata`, etc.) for the new tables.
    *   **Existing Functions (`get_all_videos`, `get_video_by_id`, etc.):** Update `SELECT` statements to reflect removed columns from `videos`.

*   **`utils/media_utils.py`**
    *   **Function `_run_ffmpeg_command`:** Review error hint parsing/logging.
    *   **New Functions (if not using `EditingTool`):** Add wrapper functions for `moviepy` crop and resize operations, handling inputs, outputs, and exceptions.
    *   **Function `check_ffmpeg_tools`:** Modify to check for and prioritize an optional `FFPROBE_PATH` config variable.
    *   **Function `sanitize_filename`:** No changes anticipated unless new issues arise.
    *   **Function `get_video_duration`:** No changes anticipated.

*   **`config.py`**
    *   **Add:** Gemini API Key and related configuration variables.
    *   **Add:** Optional `FFPROBE_PATH` variable.
    *   **Add:** Potential `moviepy` configuration (e.g., default crop settings).
    *   **Modify:** Harden `FLASK_SECRET_KEY` default (e.g., raise error if not set).
    *   **Refactor:** Consider moving `check_and_create_dirs` call to app initialization. Explore singleton pattern or direct Flask config usage (`app.config`).

*   **`.env.example` / `.env`**
    *   **Add:** Placeholders/values for new Gemini API config.
    *   **Add:** Placeholder for optional `FFPROBE_PATH`.
    *   **Add:** Placeholders for potential `moviepy` config.
    *   **Modify:** Ensure `FLASK_SECRET_KEY` is set securely.

*   **`requirements.txt`**
    *   **Add:** `moviepy`.
    *   **Add:** Google Cloud client libraries for Gemini (e.g., `google-cloud-aiplatform`).
    *   **Review/Update:** Ensure all existing dependencies are appropriately version-pinned for stability.

*   **`templates/video_details.html`**
    *   **Modify:** Major updates to the "Generated Clips" section to iterate through structured clip data (including path, transcript, metadata) fetched from the backend. Display transcript and metadata for each clip.
    *   **Modify:** Update the "Manual Batch Cutting" section with distinct input fields ("Long"/"Short").
    *   **Remove:** Sections related to displaying the old full transcript, polished transcript, Q&A, summaries, etc.

*   **`static/js/app.js`**
    *   **Modify:** Update `batchCutBtn` event listener for new input fields and payload structure.
    *   **Modify:** Implement CSRF token header inclusion in `fetch` calls.
    *   **Refine:** Improve AJAX error handling display using `showFeedback`.
    *   **Remove:** Code related to deleted UI features.

*   **`static/css/style.css`**
    *   **Remove:** Styles for deleted UI components.
    *   **Add/Modify:** Styles for new batch input fields and potentially for displaying per-clip metadata/transcripts.

*   **New Directory: `tests/`**
    *   **Add:** `pytest.ini` or `pyproject.toml` [tool.pytest.ini_options] for configuration.
    *   **Add:** Test files (`test_*.py`) covering:
        *   Utilities (`utils/media_utils.py`, `utils/error_utils.py`)
        *   Database functions (`database.py`)
        *   Tools (`tools.py` - mocking underlying calls/APIs)
        *   Tasks (`tasks.py` - mocking tools/DB, testing task logic and dispatching)
        *   Flask routes (`app.py` - using `app.test_client()`)

*   **Potentially Deleted Files/Directories:**
    *   *(Confirm based on final implementation)* If `AudioExtractorAgent` is removed, its references might disappear.
    *   Any utility files (`utils/`) or analysis files (`analysis/`) that were *only* used by the now-deleted agents/features (e.g., diarization, Q&A pairing, alignment utils) should be deleted.

---

**Concluding Note:** This file-centric plan provides a detailed overview of the required changes across the codebase. However, the interconnected nature of these changes means that modifications in one file will likely necessitate adjustments in others not immediately obvious. Implementation should proceed iteratively, with thorough testing at each stage to manage complexity and ensure correctness. This plan serves as the comprehensive starting blueprint for the refactoring effort.