# --- Start of File: app.py ---
import logging
import logging.handlers
import os
import sys
import json
import datetime
import time
import signal
import atexit

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, abort, send_from_directory)
from werkzeug.utils import secure_filename
from config import Config
import database as db

# --- Import Celery Tasks ---
from celery_app import celery_app
# Import the orchestrator and the generic agent runner (still needed)
# Import the batch cut task (still needed)
# Import the NEW single clip creation task (Placeholder - needs to be created)
from tasks import (process_video_orchestrator_task, run_agent_task,
                   batch_cut_task, create_single_clip_task) # <<< ADDED create_single_clip_task import (placeholder)

# --- Import Utilities ---
from utils import download as download_util # Still needed for get_video_info
from utils import media_utils # Still needed for sanitize_filename, time_str_to_seconds
from utils.media_utils import time_str_to_seconds # Specific import for batch cut
from utils import error_utils

# --- Import Agent Registry (Simplified) ---
from agents import AGENT_REGISTRY # Used to validate agent types (now smaller)

# --- Basic CSRF Protection ---
from flask_wtf.csrf import CSRFProtect

# --- Global Configuration ---
config = Config()

# --- App Initialization & Basic Config ---
app = Flask(__name__, instance_relative_config=False)
app.config.from_object(config)

# --- Initialize CSRF Protection ---
csrf = CSRFProtect(app)
# Note: Ensure WTF_CSRF_ENABLED is True in config (or default) for protection to be active

# ======================================
# === Logging Configuration ===
# ======================================
# (Logging setup remains the same)
log_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(threadName)s] [%(name)s] %(message)s'
)
log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
log_dir = os.path.dirname(config.LOG_FILE_PATH)
if log_dir and not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Error creating log directory {log_dir}: {e}")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
handlers = [console_handler]

if config.LOG_FILE_PATH and log_dir and os.path.exists(log_dir):
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            config.LOG_FILE_PATH, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        handlers.append(file_handler)
    except Exception as e:
        print(f"Error setting up file logger at {config.LOG_FILE_PATH}: {e}")

root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.setLevel(log_level)
for handler in handlers:
    root_logger.addHandler(handler)

logging.getLogger('flask.app').handlers = handlers
logging.getLogger('werkzeug').handlers = handlers
logging.getLogger('flask.app').propagate = False
logging.getLogger('werkzeug').propagate = False

app.logger.info("="*50)
app.logger.info("Flask application starting up...")
app.logger.info(f"Log Level set to: {config.LOG_LEVEL}")
app.logger.info(f"Database Path: {config.DATABASE_PATH}")
app.logger.info(f"CSRF Protection Enabled: {app.config['WTF_CSRF_ENABLED']}")
app.logger.info("="*50)

# ======================================
# === DB Init & Shutdown Logic ===
# ======================================
# (DB init and shutdown logic remains the same)
try:
    with app.app_context():
        db.init_db()
    app.logger.info("Database initialization check complete.")
except Exception as e:
    app.logger.critical(f"FATAL: Database initialization failed: {e}. Application cannot start.", exc_info=True)
    sys.exit(f"Database initialization failed: {e}")

def signal_handler(signum, frame):
    signal_name = signal.Signals(signum).name
    app.logger.warning(f"Received signal {signal_name}. Initiating graceful shutdown...")
    sys.exit(0)

try:
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
except ValueError:
    app.logger.warning("Cannot register signal handlers - likely not running in main thread (e.g., under debugger).")

# ======================================
# === Jinja Filters & Context Processors ===
# ======================================
# (Jinja filters and context processors remain the same)
@app.template_filter('datetimeformat')
def format_datetime(value, format='%Y-%m-%d %H:%M'):
    if not value: return "N/A"
    dt_obj = None
    try:
        # Handle ISO format with potential timezone/fractional seconds
        value_str = str(value).split('+')[0].split('.')[0].replace('Z', '').replace('T', ' ')
        dt_obj = datetime.datetime.fromisoformat(value_str)
    except (ValueError, TypeError):
        # Fallback parsing for common formats
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'):
            try:
                dt_obj = datetime.datetime.strptime(str(value), fmt)
                break
            except (ValueError, TypeError):
                continue
    if dt_obj:
         try:
             return dt_obj.strftime(format)
         except ValueError as fmt_err:
              app.logger.warning(f"Could not format datetime object {dt_obj} with format '{format}': {fmt_err}")
              return str(value)
    else:
        app.logger.warning(f"Could not parse datetime value: {value}. Returning original.")
        return str(value)

@app.template_filter('basename')
def basename_filter(value):
     if not value or not isinstance(value, str): return ""
     return os.path.basename(value)

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.datetime.now().year}

@app.context_processor
def utility_processor():
    return dict(config=config)

# ======================================
# === Request Logging Middleware ===
# ======================================
# (Request logging middleware remains the same)
@app.before_request
def log_request_info():
    if request.path.startswith('/static'): return
    log_message = f"Request <-- {request.remote_addr} - {request.method} {request.url}"
    app.logger.debug(log_message)

@app.after_request
def log_response_info(response):
    if request.path.startswith('/static'): return response
    # Avoid logging potentially large successful responses unless debugging
    log_level = logging.DEBUG if response.status_code < 400 else logging.INFO
    app.logger.log(log_level, f"Response --> {request.remote_addr} - {request.method} {request.url} - Status: {response.status_code}")
    return response

# ======================================
# === Routes ===
# ======================================

@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles the main page: displaying video list and queuing new videos."""
    if request.method == 'POST':
        # --- Logic for adding new videos remains the same ---
        app.logger.info("Received POST to queue videos from index form")
        youtube_urls_text = request.form.get('urls', '')
        resolution = request.form.get('resolution', config.DEFAULT_RESOLUTION if hasattr(config, 'DEFAULT_RESOLUTION') else '480p')
        raw_urls = [url.strip() for url in youtube_urls_text.splitlines() if url.strip()]

        if not raw_urls:
            flash('Please enter at least one YouTube URL.', 'warning')
            return redirect(url_for('index'))
        if not resolution:
             flash('Please select a resolution.', 'warning')
             return redirect(url_for('index'))

        queued_count = 0
        failed_count = 0
        warning_count = 0
        url_results = []

        for url in raw_urls:
            app.logger.info(f"Processing URL for queueing: {url} (Resolution: {resolution})")
            video_id = None
            try:
                # 1. Fetch Info
                title, fetch_error = download_util.get_video_info(url)
                if title is None:
                     err_msg = f"Failed to fetch info (Video private/unavailable?): {fetch_error}"
                     app.logger.warning(f"Skipping URL '{url}': {err_msg}")
                     url_results.append({'url': url, 'status': 'warning', 'message': err_msg})
                     warning_count += 1
                     continue

                # 2. Add Job to Database (Pass 'auto' for processing_mode)
                video_id = db.add_video_job(url, title, resolution, processing_mode='auto')
                if not video_id:
                    err_msg = "Failed to create database job record."
                    app.logger.error(f"DB Error for URL '{url}': {err_msg}")
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg})
                    failed_count += 1
                    continue

                # 3. Prepare Paths
                safe_title_part = media_utils.sanitize_filename(title)[:60]
                subfolder_name = f"video_{video_id}_{safe_title_part}"
                download_subdir = os.path.join(config.DOWNLOAD_DIR, subfolder_name)
                # Base filename, extension added by yt-dlp or predicted
                video_filename_base = f"video_{resolution}"
                # Predict path for DB storage, yt-dlp might use different container
                predicted_final_path = os.path.join(download_subdir, video_filename_base + ".mp4")

                try:
                    os.makedirs(download_subdir, exist_ok=True)
                except OSError as e:
                    err_msg = f"Failed to create download directory '{download_subdir}': {e}"
                    app.logger.error(err_msg)
                    db.update_video_error(video_id, err_msg, "Setup Error")
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg})
                    failed_count += 1
                    continue

                # 4. Update DB Path
                path_updated = db.update_video_path(video_id, predicted_final_path)
                if not path_updated:
                    err_msg = f"Database error setting initial file path for Job ID {video_id}."
                    app.logger.error(f"Critical Error for URL '{url}': {err_msg}")
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg})
                    failed_count += 1
                    continue

                # 5. Dispatch Celery Orchestrator Task
                task = process_video_orchestrator_task.delay(video_id)
                db.update_video_status(video_id, status='Queued', processing_status='Waiting for Orchestrator')

                app.logger.info(f"Successfully queued Video ID: {video_id} (Task ID: {task.id}) for URL: {url}")
                url_results.append({'url': url, 'status': 'success', 'message': f"Queued '{title}' (Job ID: {video_id})."})
                queued_count += 1

            except Exception as e:
                error_message_formatted = error_utils.format_error(e, include_traceback=False)
                app.logger.error(f"Unexpected error queuing URL {url}: {e}", exc_info=True)
                if video_id:
                    db.update_video_error(video_id, f"Unexpected setup error: {error_message_formatted}", "Setup Error")
                url_results.append({'url': url, 'status': 'error', 'message': f"Unexpected setup error: {error_message_formatted}"})
                failed_count += 1
                continue

        # Flash Summary Messages
        if queued_count > 0: flash(f"{queued_count} video(s) successfully added to the processing queue.", "success")
        warning_msgs = [f"Warning for '{res['url']}': {res['message']}" for res in url_results if res['status'] == 'warning']
        error_msgs = [f"Error for '{res['url']}': {res['message']}" for res in url_results if res['status'] == 'error']
        if warning_msgs: flash("\n".join(warning_msgs[:3]) + ('...' if len(warning_msgs) > 3 else ''), "warning")
        if error_msgs: flash("\n".join(error_msgs[:3]) + ('...' if len(error_msgs) > 3 else ''), "danger")

        return redirect(url_for('index'))

    # --- Handle GET Request ---
    try:
        videos = db.get_all_videos(order_by='created_at', desc=True)
    except Exception as e:
        app.logger.error(f"Error retrieving videos for index page: {e}", exc_info=True)
        flash("Error fetching video list. Database might be unavailable.", "danger")
        videos = []

    return render_template('index.html', videos=videos)

# MODIFIED: Fetch and pass structured clip data instead of full transcript
@app.route('/video/<int:video_id>')
def video_details(video_id):
    """Displays detailed information and results for a specific video job."""
    app.logger.info(f"Request for details of Video ID: {video_id}")
    try:
        # Fetch main video data (includes basic info, paths, status, etc.)
        # Assumes get_video_by_id is updated to NOT fetch the old 'transcript' column
        video_data = db.get_video_by_id(video_id)
        if not video_data:
            app.logger.warning(f"Video details request failed: ID {video_id} not found.")
            abort(404, description=f"Video job with ID {video_id} not found.")

        # --- Load related data safely (Simplified & Modified) ---
        # REMOVED: transcript_data = db.safe_json_load(video_data.get('transcript'), ...)

        # Placeholder for fetching structured clip data (clips, transcripts, metadata)
        # This assumes a new DB function `get_clips_with_details` will be created
        # in database.py that joins clips, clip_transcripts, clip_metadata tables.
        clips_detailed_data = []
        try:
            # clips_detailed_data = db.get_clips_with_details(video_id) # <<< UNCOMMENT when DB function exists
            app.logger.debug(f"Placeholder: Would fetch detailed clip data for video {video_id} here.")
            # Example structure expected by template might be:
            # clips_detailed_data = [
            #   {'id': 1, 'path': '...', 'start': 0.0, 'end': 10.0, 'status': 'Completed', 'transcript': [...], 'metadata': {'title': '...', 'desc': '...'}},
            #   {'id': 2, 'path': '...', ...}
            # ]
            pass # Keep clips_detailed_data as empty list for now
        except Exception as db_clip_err:
            app.logger.error(f"Error fetching detailed clip data for video {video_id}: {db_clip_err}", exc_info=True)
            flash("Error loading generated clip details.", "warning")
            # clips_detailed_data will remain empty

        # Load agent runs (still relevant)
        agent_runs = db.get_agent_runs(video_id)

        # --- Calculate derived status (logic remains the same, based on video_data.status) ---
        status = video_data.get('status', 'Unknown').lower()
        proc_status = video_data.get('processing_status', 'N/A')
        overall_status = 'Unknown'
        overall_status_class = 'unknown'

        if status == 'error':
            overall_status = 'Error'
            overall_status_class = 'error'
        elif status == 'processed':
            overall_status = 'Complete' # Note: 'Processed' might mean different things now (e.g., download done, awaiting clips?)
            overall_status_class = 'complete' # Need to redefine what 'Processed' means in the new workflow.
        elif status == 'processing':
            overall_status = 'Processing'
            overall_status_class = 'processing'
        elif status == 'downloading':
             overall_status = 'Downloading'
             overall_status_class = 'running'
        elif status == 'queued':
            overall_status = 'Queued'
            overall_status_class = 'queued'
        elif status == 'pending':
            overall_status = 'Pending'
            overall_status_class = 'pending'
        # Consider adding statuses like 'Clipping', 'Transcribing Clips', 'Generating Metadata'

        # Add derived status to the dictionary passed to the template
        video_dict = dict(video_data)
        video_dict['overall_status'] = overall_status
        video_dict['overall_status_class'] = overall_status_class

        return render_template(
            'video_details.html',
            video=video_dict,
            clips_detailed_data=clips_detailed_data, # <<< CHANGED: Pass detailed clip data
            # REMOVED: transcript_data=transcript_data, generated_clips=generated_clips
            agent_runs=agent_runs,
            available_agents=list(AGENT_REGISTRY.keys()), # Pass remaining agent names
        )
    except Exception as e:
        app.logger.error(f"Error loading details page for Video ID {video_id}: {e}", exc_info=True)
        flash("Error loading video details page.", "danger")
        return redirect(url_for('index'))


# --- error_log, delete_videos, serve_clip routes remain the same ---
@app.route('/errors')
def error_log():
    """Displays a page listing videos that have encountered errors."""
    app.logger.info("Accessing error log page")
    try:
        error_videos = db.get_videos_with_errors() # Uses simplified logic now
    except Exception as e:
        app.logger.error(f"Error fetching error videos from DB: {e}", exc_info=True)
        flash("Error fetching the list of errored videos.", "danger")
        error_videos = []
    return render_template('error_log.html', error_videos=error_videos)

@app.route('/delete-videos', methods=['POST'])
def delete_videos():
    """Deletes selected video jobs and associated files."""
    record_ids_str = request.form.getlist('selected_videos')
    if not record_ids_str:
        flash('No videos selected for deletion.', 'warning')
        return redirect(request.referrer or url_for('index'))
    try:
        video_ids_to_delete = [int(id_str) for id_str in record_ids_str]
    except ValueError:
        flash('Invalid video ID format received.', 'danger')
        return redirect(request.referrer or url_for('index'))

    app.logger.warning(f"Processing request to DELETE Video IDs: {video_ids_to_delete}")
    deleted_db_count = 0
    files_deleted_count = 0
    files_failed_count = 0
    dirs_removed_count = 0
    dirs_failed_count = 0

    # Fetch video data *before* deleting records to get paths
    videos_data = [db.get_video_by_id(vid) for vid in video_ids_to_delete]

    try:
        # Delete DB records first (CASCADE should handle related clips/transcripts/metadata)
        deleted_db_count = db.delete_video_records(video_ids_to_delete)
        if deleted_db_count != len(video_ids_to_delete):
             flash(f'Warning: Requested deletion of {len(video_ids_to_delete)} videos, but only {deleted_db_count} records were found/deleted in DB.', 'warning')
        if deleted_db_count > 0:
             flash(f'Successfully deleted {deleted_db_count} job record(s) and related data from the database.', 'success')
    except Exception as db_del_err:
        app.logger.error(f"Error deleting video records from DB: {db_del_err}", exc_info=True)
        flash("Error occurred while deleting database records.", "danger")
        # Proceed with file deletion attempt even if DB delete failed partially

    # --- File Deletion Logic ---
    dirs_to_try_remove = set()
    for video in videos_data:
        if not video: continue
        paths_to_delete = []
        # Main video file and its directory
        main_video_path = video.get('file_path')
        if main_video_path and isinstance(main_video_path, str):
             paths_to_delete.append(main_video_path)
             subdir = os.path.dirname(main_video_path)
             # Ensure it's within the expected base download directory before adding for removal
             if subdir and subdir.startswith(config.DOWNLOAD_DIR) and os.path.normpath(subdir) != os.path.normpath(config.DOWNLOAD_DIR):
                 dirs_to_try_remove.add(subdir)

        # Old audio file path (if it exists)
        audio_file_path = video.get('audio_path') # Fetch old path if it exists
        if audio_file_path and isinstance(audio_file_path, str): paths_to_delete.append(audio_file_path)

        # Clip files (fetch paths from the new clips table - placeholder)
        try:
            # clips_info = db.get_clips_for_video(video['id']) # <<< UNCOMMENT when DB function exists
            clips_info = [] # Placeholder
            if clips_info:
                clip_paths = [c['clip_path'] for c in clips_info if c.get('clip_path')]
                safe_clip_paths = [p for p in clip_paths if p and isinstance(p, str) and p.startswith(config.PROCESSED_CLIPS_DIR)]
                paths_to_delete.extend(safe_clip_paths)
                # Also add clip parent dirs if they are unique subdirs within PROCESSED_CLIPS_DIR
                for clip_p in safe_clip_paths:
                     clip_subdir = os.path.dirname(clip_p)
                     if clip_subdir and clip_subdir.startswith(config.PROCESSED_CLIPS_DIR) and os.path.normpath(clip_subdir) != os.path.normpath(config.PROCESSED_CLIPS_DIR):
                          dirs_to_try_remove.add(clip_subdir)
        except Exception as clip_fetch_err:
            app.logger.error(f"Error fetching clip paths during deletion for video {video['id']}: {clip_fetch_err}")

        # Delete identified files
        for path in paths_to_delete:
            if not path or not isinstance(path, str): continue
            # Security check: ensure path is within allowed directories
            if not (path.startswith(config.DOWNLOAD_DIR) or path.startswith(config.PROCESSED_CLIPS_DIR)):
                app.logger.error(f"Security Risk: Attempted to delete file outside allowed directories: {path}. Skipping.")
                files_failed_count += 1
                continue
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    files_deleted_count += 1
                    app.logger.info(f"Deleted file: {path}")
                except OSError as e:
                    app.logger.error(f"Error deleting file '{path}': {e}")
                    files_failed_count += 1

    # Attempt to remove directories (only if empty)
    for dir_path in sorted(list(dirs_to_try_remove), reverse=True): # Process deepest first
         # Security check again
         if not (dir_path.startswith(config.DOWNLOAD_DIR) or dir_path.startswith(config.PROCESSED_CLIPS_DIR)):
             app.logger.error(f"Security Risk: Attempted to delete directory outside allowed base paths: {dir_path}. Skipping.")
             dirs_failed_count += 1
             continue
         if os.path.exists(dir_path) and os.path.isdir(dir_path):
             try:
                 if not os.listdir(dir_path): # Check if empty
                     os.rmdir(dir_path)
                     dirs_removed_count += 1
                     app.logger.info(f"Removed empty directory: {dir_path}")
                 else:
                     app.logger.warning(f"Directory '{dir_path}' not empty, skipping removal.")
             except OSError as e:
                 app.logger.error(f"Error removing directory '{dir_path}': {e}")
                 dirs_failed_count += 1

    # Report results
    if files_deleted_count > 0: flash(f"Deleted {files_deleted_count} associated local files.", "info")
    if dirs_removed_count > 0: flash(f"Removed {dirs_removed_count} associated empty local directories.", "info")
    if files_failed_count > 0: flash(f"Failed to delete {files_failed_count} local files (check logs).", "warning")
    if dirs_failed_count > 0: flash(f"Failed to remove {dirs_failed_count} local directories (check logs).", "warning")

    return redirect(request.referrer or url_for('index'))


# MODIFIED: Dispatch background task instead of running FFmpeg directly
# REMOVED: @csrf.exempt
@app.route('/clip/<int:video_id>', methods=['POST'])
# @csrf.exempt # <<< REMOVED - CSRF protection now active
def trigger_clip_creation(video_id):
    """Dispatches a background task to create a single clip."""
    app.logger.info(f"Received request to queue manual clip task for Video ID: {video_id}")

    # --- Parameter Validation (similar to before) ---
    video = db.get_video_by_id(video_id)
    if not video:
        return jsonify({"success": False, "error": "Video record not found."}), 404

    source_video_path = video.get('file_path')
    if not source_video_path or not os.path.exists(source_video_path):
         return jsonify({"success": False, "error": "Original video file is missing or inaccessible."}), 400

    try:
        start_time = request.form.get('start_time', type=float)
        end_time = request.form.get('end_time', type=float)
        # Keep these for potential use in naming or context, though text isn't used for clipping itself
        segment_text_raw = request.form.get('text', '')
        segment_index_str = request.form.get('segment_index', 'manual')
    except Exception as form_err:
         app.logger.warning(f"Invalid form data for manual clip (Video {video_id}): {form_err}")
         return jsonify({"success": False, "error": "Invalid form data received."}), 400

    if start_time is None or end_time is None:
         return jsonify({"success": False, "error": "Missing required start/end time."}), 400

    duration = round(end_time - start_time, 3)
    min_dur = config.CLIP_MIN_DURATION_SECONDS
    manual_max_dur = config.CLIP_MANUAL_MAX_DURATION_SECONDS

    if duration < min_dur:
         return jsonify({"success": False, "error": f"Clip duration ({duration:.2f}s) too short (min: {min_dur}s)."}), 400
    if duration > manual_max_dur:
        return jsonify({"success": False, "error": f"Clip duration ({duration:.2f}s) too long for manual clip (max: {manual_max_dur}s)."}), 400
    if start_time < 0:
        # Allow start_time=0, just clamp if slightly negative due to UI input
        start_time = 0.0

    # --- Dispatch Task ---
    # REMOVED: Direct call to media_tool.create_clip and db.add_generated_clip

    # Define parameters for the new task
    # Note: The task will need to generate the output path itself
    task_args = (video_id, start_time, end_time)
    # Optionally pass other info if the task needs it (e.g., for naming conventions)
    task_kwargs = {'clip_type': 'manual', 'context_text': segment_text_raw[:50]} # Example optional kwargs

    # Use the _dispatch_task helper
    return _dispatch_task(
        create_single_clip_task, # <<< Use the new task (placeholder)
        *task_args,
        # **task_kwargs, # Uncomment if using kwargs
        success_msg="Single clip generation task queued.",
        error_msg="Failed to queue single clip generation task."
    )


@app.route('/clips/<path:filename>')
def serve_clip(filename):
    """Serves generated clip files from the PROCESSED_CLIPS_DIR."""
    # --- Logic remains the same ---
    clips_dir = config.PROCESSED_CLIPS_DIR
    if not filename or ".." in filename or filename.startswith(("/", "\\")):
        app.logger.warning(f"Attempt to access invalid clip path: {filename}")
        abort(400, description="Invalid filename.")
    # Use os.path.abspath for more robust path checking
    base_dir = os.path.abspath(clips_dir)
    safe_path = os.path.abspath(os.path.join(base_dir, filename))
    if not safe_path.startswith(base_dir + os.sep) and safe_path != base_dir :
         app.logger.error(f"Security Alert: Attempt to access file outside clips directory: {filename} (Resolved: {safe_path})")
         abort(404, description="File not found.")
    if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
        app.logger.warning(f"Clip file not found at path: {safe_path}")
        abort(404, description="Clip file not found.")
    try:
        return send_from_directory(
            clips_dir, filename, as_attachment=False, mimetype='video/mp4', conditional=True
        )
    except Exception as serve_err:
         app.logger.error(f"Error serving file '{filename}' from '{clips_dir}': {serve_err}", exc_info=True)
         abort(500, description="Error serving file.")


@app.route('/status_updates')
def status_updates():
    """
    Returns JSON data for videos currently in a processing or queued state.
    Used by the frontend for polling-based UI updates.
    """
    # --- Logic remains the same, but the meaning/values of 'status' might change ---
    try:
        # Query for statuses that indicate activity
        # Need to adjust these based on the new workflow (e.g., add 'Clipping'?)
        active_statuses = ['Pending', 'Queued', 'Downloading', 'Processing', 'Clipping', 'Transcribing Clips', 'Generating Metadata'] # Example adjusted statuses
        videos = db.get_videos_by_statuses(active_statuses)
        updates = []
        for video in videos:
            updates.append({
                'id': video['id'],
                'status': video['status'], # Overall status
                'processing_status': video['processing_status'], # Current step/agent
                'updated_at': format_datetime(video['updated_at'], '%H:%M:%S') # Short time format
            })
        return jsonify(updates)
    except Exception as e:
        app.logger.error(f"Error fetching status updates: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch status updates"}), 500


# ===============================================
# === Agent and Regeneration Task Routes ===
# ===============================================

# --- Helper for Task Dispatching --- (Kept)
def _dispatch_task(task_func, *args, success_msg="Task queued.", error_msg="Failed to queue task.", **kwargs):
    """Helper to dispatch a Celery task and return JSON response."""
    try:
        task = task_func.delay(*args, **kwargs) # Pass kwargs through
        app.logger.info(f"Dispatched Celery task {task.id} for function {task_func.name} with args {args} and kwargs {kwargs}")
        return jsonify({"success": True, "message": success_msg, "task_id": task.id}), 202 # 202 Accepted
    except Exception as e:
        app.logger.error(f"Failed to dispatch Celery task {task_func.name}: {e}", exc_info=True)
        return jsonify({"success": False, "error": error_msg}), 500

# --- Route for Full Reprocessing ---
# REMOVED: @csrf.exempt
@app.route('/reprocess_full/<int:video_id>', methods=['POST'])
# @csrf.exempt # <<< REMOVED
def trigger_reprocess_full(video_id):
    """Triggers the full analysis pipeline (excluding download)."""
    app.logger.warning(f"Received request to REPROCESS FULL ANALYSIS for Video ID {video_id}")
    if not db.get_video_by_id(video_id):
        return jsonify({"success": False, "error": "Video record not found."}), 404

    # Reset analysis results in DB first (Uses the updated reset function)
    # This will now delete clip/transcript/metadata records.
    if not db.reset_video_analysis_results(video_id):
        app.logger.error(f"Failed to reset analysis results in DB for video {video_id} before reprocessing.")
        return jsonify({"success": False, "error": "Database error during reset before reprocessing."}), 500

    # Dispatch the orchestrator task with skip_download=True
    # Note: Orchestrator logic needs update based on pipeline changes
    return _dispatch_task(
        process_video_orchestrator_task,
        video_id, True, # Pass skip_download=True
        success_msg="Full analysis reprocessing task queued (skipping download).",
        error_msg="Failed to queue full reprocessing task."
    )


# --- Route for Manual Batch Cutting ---
# MODIFIED: Accept clip_type, remove @csrf.exempt
# REMOVED: @csrf.exempt
@app.route('/video/<int:video_id>/batch_cut', methods=['POST'])
# @csrf.exempt # <<< REMOVED
def trigger_batch_cut(video_id):
    """Receives timestamp list and dispatches the batch cutting task."""
    if not request.is_json:
        return jsonify({"success": False, "error": "Request must be JSON"}), 415

    data = request.get_json()
    timestamp_strings = data.get('timestamps')
    clip_type = data.get('clip_type', 'long') # <<< ADDED: Get clip_type, default to 'long'

    if not isinstance(timestamp_strings, list):
        return jsonify({"success": False, "error": "Invalid data format: 'timestamps' must be a list."}), 400

    app.logger.info(f"Received request for batch cut on Video ID {video_id} with {len(timestamp_strings)} timestamps (Type: {clip_type}).")

    valid_timestamps = []
    errors = []
    for ts_str in timestamp_strings:
        seconds = time_str_to_seconds(ts_str)
        if seconds is not None and seconds >= 0:
            valid_timestamps.append(seconds)
        else:
            errors.append(f"Invalid format: '{ts_str}'")

    if errors:
        return jsonify({"success": False, "error": f"Invalid timestamp formats found: {'; '.join(errors)}"}), 400
    if not valid_timestamps:
         return jsonify({"success": False, "error": "No valid timestamps provided."}), 400

    valid_timestamps = sorted(list(set(valid_timestamps)))

    video = db.get_video_by_id(video_id)
    if not video:
        return jsonify({"success": False, "error": "Video record not found."}), 404

    # Optional: Save raw timestamps back to DB (still potentially useful for reference)
    db.update_video_result(video_id, 'manual_timestamps', "\n".join(timestamp_strings))

    # Dispatch Celery Task, passing the clip_type
    return _dispatch_task(
        batch_cut_task, # Note: batch_cut_task needs modification to accept clip_type
        video_id,
        valid_timestamps,
        clip_type, # <<< ADDED: Pass clip_type to the task
        success_msg="Batch clip generation task queued.",
        error_msg="Failed to queue batch clip generation task."
    )


# ======================================
# === Main Execution Guard ===
# ======================================
# (Main execution guard remains the same)
if __name__ == '__main__':
    use_waitress = not app.debug
    if use_waitress:
        try:
            from waitress import serve
            host = '0.0.0.0'
            port = config.PORT
            threads = int(os.environ.get('WAITRESS_THREADS', 8)) # Make threads configurable
            app.logger.info(f"Starting production server with Waitress on http://{host}:{port}/ with {threads} threads")
            serve(app, host=host, port=port, threads=threads)
        except ImportError:
            app.logger.error("Waitress not installed. Run 'pip install waitress'. Falling back to Flask development server.")
            app.run(host='0.0.0.0', port=config.PORT, debug=True)
        except Exception as serve_err:
             app.logger.critical(f"Failed to start Waitress server: {serve_err}", exc_info=True)
             sys.exit(1)
    else:
        # Use reloader=True for development convenience
        app.logger.info(f"Starting Flask development server on http://0.0.0.0:{config.PORT}/ (Debug: {app.debug}, Reloader: True)")
        app.run(host='0.0.0.0', port=config.PORT, debug=True, use_reloader=True)

# --- END OF FILE: app.py ---