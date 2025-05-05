# --- Start of File: database.py ---
import sqlite3
import os
import json
import logging
from contextlib import contextmanager
import datetime
from config import Config # Import application configuration

# Get configuration instance
config = Config()
DATABASE_PATH = config.DATABASE_PATH # Get database path from config

logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """
    Provides a managed database connection using a context manager.
    Ensures the connection is closed automatically.
    Configures WAL mode and foreign keys for the connection.

    Yields:
        sqlite3.Connection: An active SQLite database connection object.
    Raises:
        sqlite3.Error: If connection or initial PRAGMA commands fail.
    """
    conn = None
    try:
        db_dir = os.path.dirname(DATABASE_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"Created database directory: {db_dir}")

        conn = sqlite3.connect(DATABASE_PATH, timeout=20.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        logger.critical(f"Database connection or PRAGMA error for '{DATABASE_PATH}': {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()

def _add_column_if_not_exists(cursor, table_name, column_name, column_type):
    """Helper to add a column only if it doesn't exist."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = [column[1] for column in cursor.fetchall()]
    if column_name not in existing_columns:
        try:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type};')
            logger.info(f"Added '{column_name}' column to '{table_name}' table.")
            return True
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                logger.debug(f"Column '{column_name}' already exists in '{table_name}' table.")
                return False # Indicate column already existed
            else:
                logger.error(f"Failed to add column '{column_name}' to '{table_name}': {e}", exc_info=True)
                raise # Re-raise other errors
    return False # Column already existed

def init_db():
    """
    Initializes the database schema. Creates/updates tables and indexes.
    NOTE: Applying this to an existing DB with the old schema is DESTRUCTIVE
    without manual migration steps. Recommend deleting the old DB file first.
    """
    logger.info(f"Initializing/Verifying database schema at '{DATABASE_PATH}'...")
    logger.warning("Schema changes are destructive without manual migration. Ensure DB is new or backed up.")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # === Create/Update `videos` Table ===
            # Drop old table if exists (simplest migration for this refactor)
            # cursor.execute("DROP TABLE IF EXISTS videos;") # Uncomment to force recreation

            # Create table WITHOUT old columns: transcript, audio_path, generated_clips
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_url TEXT NOT NULL UNIQUE, -- Added UNIQUE constraint
                    title TEXT,
                    resolution TEXT,
                    status TEXT DEFAULT 'Pending',          -- Overall status (Pending, Queued, Downloading, Processing, Processed, Error)
                    processing_status TEXT DEFAULT 'Added', -- Current step description
                    file_path TEXT UNIQUE,                  -- Path to downloaded video (Can be NULL initially)
                    error_message TEXT,                   -- Stores the last significant error message
                    processing_mode TEXT DEFAULT 'auto',    -- Kept for initial job setup
                    manual_timestamps TEXT,               -- Kept for batch cutting UI reference
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.debug("`videos` table schema checked/created (New Schema).")

            # Add columns using helper function (if needed in future, e.g. adding processing_mode if it wasn't part of initial create)
            # _add_column_if_not_exists(cursor, 'videos', 'processing_mode', "TEXT DEFAULT 'auto'")
            # _add_column_if_not_exists(cursor, 'videos', 'manual_timestamps', 'TEXT NULL')

            # === Create `clips` Table ===
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    clip_path TEXT NOT NULL UNIQUE, -- Path to the generated clip file
                    start_time REAL NOT NULL,       -- Start time in seconds
                    end_time REAL NOT NULL,         -- End time in seconds
                    clip_type TEXT DEFAULT 'batch', -- 'batch' or 'manual' or 'short' etc.
                    status TEXT DEFAULT 'Pending',  -- Status of this clip's processing (Pending, Processing, Editing, Transcribing, Generating Metadata, Completed, Failed)
                    error_message TEXT,             -- Error specific to this clip's processing
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
                );
            """)
            logger.debug("`clips` table schema checked/created.")

            # === Create `clip_transcripts` Table ===
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clip_transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clip_id INTEGER NOT NULL UNIQUE, -- One transcript per clip
                    transcript_json TEXT,           -- JSON list of segments [{'start', 'end', 'text'}]
                    status TEXT DEFAULT 'Pending',  -- Status of transcription (Pending, Completed, Failed)
                    error_message TEXT,             -- Transcription error
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
                );
            """)
            logger.debug("`clip_transcripts` table schema checked/created.")

            # === Create `clip_metadata` Table ===
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clip_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clip_id INTEGER NOT NULL UNIQUE, -- One metadata set per clip
                    title TEXT,
                    description TEXT,
                    keywords_json TEXT,             -- JSON list of keywords
                    status TEXT DEFAULT 'Pending',  -- Status of metadata generation (Pending, Completed, Failed)
                    error_message TEXT,             -- Metadata generation error
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
                );
            """)
            logger.debug("`clip_metadata` table schema checked/created.")

            # === Create `agent_runs` Table === (Unchanged, kept for download agent tracking)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    agent_type TEXT NOT NULL,           -- e.g., 'downloader', 'batch_cut_dispatcher'
                    target_id TEXT,                     -- Optional: Specific item targeted (less used now)
                    status TEXT NOT NULL,               -- 'Pending', 'Running', 'Success', 'Failed'
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    result_preview TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
                );
            """)
            logger.debug("`agent_runs` table schema checked/created.")

            # === Create `mpps` Table ===
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mpps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    constituency TEXT,
                    party TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.debug("`mpps` table schema checked/created.")


            # === Create Indexes ===
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_status ON videos (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_video_id ON clips (video_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_status ON clips (status)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clip_transcripts_clip_id ON clip_transcripts (clip_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clip_metadata_clip_id ON clip_metadata (clip_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_video_id ON agent_runs (video_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mpps_name ON mpps (name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mpps_active ON mpps (active)")
            logger.debug("Indexes checked/created.")

            # === Create/Update `updated_at` Triggers ===
            # Trigger for 'videos' table (Unchanged)
            cursor.execute('DROP TRIGGER IF EXISTS update_videos_updated_at;')
            cursor.execute('''
                CREATE TRIGGER update_videos_updated_at
                AFTER UPDATE ON videos
                FOR EACH ROW
                WHEN NEW.updated_at = OLD.updated_at
                BEGIN
                    UPDATE videos SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END;
            ''')
            # Trigger for 'mpps' table
            cursor.execute('DROP TRIGGER IF EXISTS update_mpps_updated_at;')
            cursor.execute('''
                CREATE TRIGGER update_mpps_updated_at
                AFTER UPDATE ON mpps
                FOR EACH ROW
                WHEN NEW.updated_at = OLD.updated_at
                BEGIN
                    UPDATE mpps SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END;
            ''')
            logger.debug("`updated_at` triggers checked/created.")

            # === Populate MPPs Table (Example Data) ===
            # This should ideally be managed elsewhere, but included for completeness.
            # Using INSERT OR IGNORE to avoid errors if run multiple times.
            mpp_list = [
                ('Doug Ford', 'Etobicoke North', 'PC', True),
                ('Marit Stiles', 'Davenport', 'NDP', True),
                ('Bonnie Crombie', 'Leader OLP', 'Liberal', True), # Example Leader without seat
                ('John Fraser', 'Ottawa South', 'Liberal', True),
                ('Mike Schreiner', 'Guelph', 'Green', True),
                ('Peter Bethlenfalvy', 'Pickering—Uxbridge', 'PC', True),
                ('Sylvia Jones', 'Dufferin—Caledon', 'PC', True),
                ('Stephen Lecce', 'King—Vaughan', 'PC', True),
                ('Andrea Horwath', 'Hamilton Centre', 'NDP', False), # Example inactive
                # Add all other MPPs here...
            ]
            cursor.executemany("""
                INSERT OR IGNORE INTO mpps (name, constituency, party, active)
                VALUES (?, ?, ?, ?)
            """, mpp_list)
            logger.debug(f"Populated/verified MPPs table with {len(mpp_list)} example entries.")

            conn.commit()
            logger.info("Database schema initialization/verification completed successfully (New Schema).")

    except sqlite3.Error as e:
        logger.critical(f"Database schema initialization FAILED: {e}", exc_info=True)
        raise


# --- Helper Functions --- (Unchanged)

def dict_from_row(row: sqlite3.Row | None) -> dict | None:
    """Converts a sqlite3.Row object to a standard Python dictionary."""
    if row is None: return None
    d = {}
    for key in row.keys():
        val = row[key]
        if isinstance(val, bytes):
            try:
                d[key] = val.decode('utf-8', errors='replace')
                logger.warning(f"Decoded bytes found in column '{key}' for row. Assuming UTF-8.")
            except Exception:
                 d[key] = "[Binary Data Cannot Decode]"
        else:
            d[key] = val
    return d

def safe_json_load(json_string, default_value=None, context_msg=""):
    """Safely parse JSON from DB fields, handling None, empty strings, and errors."""
    if json_string is None or json_string == "":
        return default_value
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in DB {context_msg}: {e}. Field content (first 100 chars): '{str(json_string)[:100]}...'")
        return {"error": f"Invalid JSON data in database field (Error: {e})"}
    except Exception as e:
         logger.error(f"Unexpected error loading JSON {context_msg}: {e}. Field content: '{str(json_string)[:100]}...'", exc_info=True)
         return {"error": f"Unexpected error loading JSON data (Error: {e})"}

# ======================================
# === Video Table CRUD Operations ===
# ======================================

# MODIFIED: Added UNIQUE constraint handling for youtube_url
def add_video_job(youtube_url, title, resolution, processing_mode):
    """Adds a new video job record with initial pending status and processing mode."""
    sql = """
        INSERT INTO videos (youtube_url, title, resolution, status, processing_status, processing_mode)
        VALUES (?, ?, ?, 'Pending', 'Added', ?)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, (youtube_url, title, resolution, processing_mode))
            new_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Added initial video job record ID: {new_id} for URL: {youtube_url} (Mode: {processing_mode})")
            return new_id
    except sqlite3.IntegrityError as e:
         if "UNIQUE constraint failed: videos.youtube_url" in str(e):
             logger.warning(f"Video with URL '{youtube_url}' already exists in the database.")
             # Optionally find and return the existing ID
             existing_id = get_video_id_by_url(youtube_url)
             return existing_id # Return existing ID or None if lookup fails
         else:
              logger.error(f"DB Integrity Error adding video job for {youtube_url}: {e}", exc_info=True)
              return None
    except sqlite3.Error as e:
        logger.error(f"Error adding video job record for {youtube_url} to DB: {e}", exc_info=True)
        return None

def get_video_id_by_url(youtube_url):
    """Finds the ID of a video job given its URL."""
    sql = "SELECT id FROM videos WHERE youtube_url = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (youtube_url,)).fetchone()
        return row['id'] if row else None
    except sqlite3.Error as e:
        logger.error(f"Error fetching video ID by URL {youtube_url}: {e}", exc_info=True)
        return None

# --- update_video_path, update_video_status, update_video_error --- (No changes needed)
def update_video_path(video_id, file_path):
    """Updates the main video file path. Handles potential UNIQUE constraint violation."""
    sql = "UPDATE videos SET file_path = ? WHERE id = ?"
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (file_path, video_id))
            conn.commit()
            logger.info(f"Updated file_path for video ID {video_id} to: {file_path}")
            return True
    except sqlite3.IntegrityError as e:
         if "UNIQUE constraint failed: videos.file_path" in str(e):
             logger.error(f"DB Integrity Error updating file path for video {video_id}: Path '{file_path}' likely already exists for another job. Error: {e}")
             update_video_error(video_id, f"File path conflict: '{os.path.basename(file_path)}' may already be associated with another job.", "Setup Error")
             return False
         else:
             logger.error(f"DB Integrity Error updating file_path for video ID {video_id}: {e}", exc_info=True)
             return False
    except sqlite3.Error as e:
        logger.error(f"Error updating file_path for video ID {video_id}: {e}", exc_info=True)
        return False

# --- REMOVED update_video_audio_path ---
# def update_video_audio_path(video_id, audio_path): ...

def update_video_status(video_id, status=None, processing_status=None):
    """Updates the overall status and/or the detailed processing status."""
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if processing_status is not None:
        updates.append("processing_status = ?")
        params.append(processing_status)

    if not updates:
        logger.warning(f"Called update_video_status for video ID {video_id} with no updates provided.")
        return False

    sql = f"UPDATE videos SET {', '.join(updates)} WHERE id = ?"
    params.append(video_id)

    try:
        with get_db_connection() as conn:
            conn.execute(sql, tuple(params))
            conn.commit()
            log_parts = [f"Video {video_id} status update ->"]
            if status: log_parts.append(f"Overall='{status}'")
            if processing_status: log_parts.append(f"Step='{processing_status}'")
            logger.info(" ".join(log_parts))
            return True
    except sqlite3.Error as e:
        logger.error(f"Error updating status for video ID {video_id}: {e}", exc_info=True)
        return False

def update_video_error(video_id, error_message, processing_status="Processing Error", status="Error"):
    """Marks a job as errored, updating status fields and error message."""
    sql = """
        UPDATE videos
        SET status = ?, processing_status = ?, error_message = ?
        WHERE id = ?
    """
    error_message_truncated = str(error_message)[:3000] if error_message else None
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (status, processing_status, error_message_truncated, video_id))
            conn.commit()
        logger.warning(f"Set ERROR status for video ID {video_id}. Step='{processing_status}', Error='{str(error_message_truncated)[:150]}...'")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error setting error status for video ID {video_id}: {e}", exc_info=True)
        return False

# MODIFIED: Simplified allowed columns
def update_video_result(video_id, column_name, data_to_store):
    """Updates a specific result column (e.g., manual_timestamps)."""
    allowed_columns = ['manual_timestamps'] # Only remaining text column

    if column_name not in allowed_columns:
        logger.error(f"Invalid or deprecated column name '{column_name}' specified for update_video_result.")
        return False

    final_value = str(data_to_store) if data_to_store is not None else None

    sql = f"UPDATE videos SET {column_name} = ? WHERE id = ?"
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (final_value, video_id))
            conn.commit()
        log_data_preview = str(final_value)[:100] + ('...' if final_value and len(str(final_value)) > 100 else '') if final_value else 'NULL'
        logger.info(f"Stored results in column '{column_name}' for video ID {video_id}. Preview: {log_data_preview}")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating column '{column_name}' for video ID {video_id}: {e}", exc_info=True)
        return False

# --- REMOVED add_generated_clip ---

# --- Video Retrieval Functions ---

# MODIFIED: Select only existing columns
def get_video_by_id(video_id):
    """Fetches a single video job record by ID."""
    sql = """SELECT id, youtube_url, title, resolution, status, processing_status,
                    file_path, error_message, created_at, updated_at,
                    processing_mode, manual_timestamps
             FROM videos WHERE id = ?"""
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (video_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching video by ID {video_id}: {e}", exc_info=True)
        return None

# MODIFIED: Select only existing columns, simplified derived status slightly
def get_all_videos(order_by='created_at', desc=True):
    """Fetches all video job records, calculating derived status for UI."""
    direction = 'DESC' if desc else 'ASC'
    # Update allowed columns
    allowed_columns = ['id', 'title', 'status', 'created_at', 'updated_at', 'resolution', 'processing_status', 'processing_mode']
    if order_by not in allowed_columns:
        original_order_by = order_by
        order_by = 'created_at' # Safe default
        logger.warning(f"Invalid 'order_by' column specified ('{original_order_by}'). Falling back to '{order_by}'.")

    # Select only existing columns
    sql = f"""SELECT id, youtube_url, title, resolution, status, processing_status,
                     error_message, created_at, updated_at, processing_mode
              FROM videos ORDER BY {order_by} {direction}"""
    videos = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql).fetchall()
            for row in rows:
                 video_dict = dict_from_row(row)
                 if video_dict:
                     # --- Calculate derived status for UI (Simplified) ---
                     status = video_dict.get('status', 'Unknown').lower()
                     proc_status = video_dict.get('processing_status', 'N/A')
                     overall_status = 'Unknown'
                     overall_status_class = 'unknown'
                     current_step_display = proc_status

                     if status == 'error':
                         overall_status = 'Error'
                         overall_status_class = 'error'
                         current_step_display = f"Failed: {proc_status}"
                     elif status == 'processed':
                         # 'Processed' now likely means ready for clipping or clipping done
                         overall_status = 'Ready' # Or 'Clipping Done'?
                         overall_status_class = 'complete'
                     elif status == 'processing':
                         overall_status = 'Processing'
                         overall_status_class = 'processing'
                     elif status == 'downloading':
                          overall_status = 'Downloading'
                          overall_status_class = 'running' # Use 'running' color
                     elif status == 'queued':
                         overall_status = 'Queued'
                         overall_status_class = 'queued'
                     elif status == 'pending':
                         overall_status = 'Pending'
                         overall_status_class = 'pending'
                     # Add checks for new statuses like 'Clipping', 'Transcribing Clips' etc.

                     video_dict['overall_status'] = overall_status
                     video_dict['overall_status_class'] = overall_status_class
                     video_dict['current_step_display'] = current_step_display

                     videos.append(video_dict)
        return videos
    except sqlite3.Error as e:
        logger.error(f"Error fetching all videos from DB: {e}", exc_info=True)
        return []

# MODIFIED: Select only existing columns
def get_videos_with_errors():
    """Fetches videos marked with error status."""
    sql = """
        SELECT id, title, status, processing_status, error_message, updated_at
        FROM videos
        WHERE status = 'Error'
        ORDER BY updated_at DESC
     """
    videos_with_errors = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql).fetchall()
            for row in rows:
                video_dict = dict_from_row(row)
                if video_dict:
                    # Determine the step where the error occurred
                    first_error_step = video_dict.get('processing_status', 'Unknown Error Step')
                    video_dict['first_error_step'] = first_error_step
                    video_dict['first_error_message'] = video_dict.get('error_message')
                    videos_with_errors.append(video_dict)
        return videos_with_errors
    except sqlite3.Error as e:
        logger.error(f"Error fetching videos with errors from DB: {e}", exc_info=True)
        return []

# --- get_videos_by_statuses, delete_video_records --- (No changes needed)
def get_videos_by_statuses(statuses: list[str]):
    """Fetches specific columns for videos matching a list of statuses (for UI updates)."""
    if not statuses: return []
    placeholders = ','.join('?' for _ in statuses)
    # Select existing columns
    sql = f"""
        SELECT id, status, processing_status, updated_at
        FROM videos WHERE status IN ({placeholders}) ORDER BY updated_at DESC
    """
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql, tuple(statuses)).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching videos by statuses {statuses}: {e}", exc_info=True)
        return []

def delete_video_records(video_ids: list[int]):
    """Deletes multiple video records and relies on CASCADE delete for related data."""
    if not video_ids:
        logger.warning("Attempted to delete videos with an empty ID list.")
        return 0
    if not all(isinstance(vid, int) for vid in video_ids):
         logger.error(f"Invalid video ID type in list for deletion: {video_ids}")
         return 0

    placeholders = ','.join('?' for _ in video_ids)
    sql = f"DELETE FROM videos WHERE id IN ({placeholders})"
    deleted_count = 0
    try:
        with get_db_connection() as conn:
            # Ensure foreign keys are enabled for CASCADE to work
            conn.execute("PRAGMA foreign_keys=ON;")
            cursor = conn.execute(sql, tuple(video_ids))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} video record(s) and related data (via CASCADE) for IDs: {video_ids}.")
            else:
                logger.warning(f"Attempted to delete video IDs {video_ids}, but no matching records were found in the database.")
            return deleted_count
    except sqlite3.Error as e:
        logger.error(f"Error deleting video records {video_ids} from DB: {e}", exc_info=True)
        return 0

# ======================================
# === Agent Related DB Operations ===
# ======================================
# --- add_agent_run, update_agent_run_status, get_agent_runs --- (Unchanged)
def add_agent_run(video_id, agent_type, target_id=None, status='Pending'):
    """Creates a new record in the agent_runs table, returning the new run ID."""
    sql = """
        INSERT INTO agent_runs (video_id, agent_type, target_id, status, started_at, finished_at, result_preview, error_message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """
    start_time = datetime.datetime.now(datetime.timezone.utc) if status == 'Running' else None
    finished_at = datetime.datetime.now(datetime.timezone.utc) if status in ['Success', 'Failed'] else None
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, (video_id, agent_type, target_id, status, start_time, finished_at, None, None))
            run_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Created agent run record ID {run_id} for Video {video_id}, Agent '{agent_type}', Target '{target_id}', Status '{status}'.")
            return run_id
    except sqlite3.Error as e:
        logger.error(f"Error adding agent run record for Video {video_id}, Agent '{agent_type}': {e}", exc_info=True)
        return None

def update_agent_run_status(run_id, status, error_message=None, result_preview=None):
    """Updates the status, finish time, and optionally error/result for an agent run."""
    finished_at = datetime.datetime.now(datetime.timezone.utc) if status in ['Success', 'Failed'] else None
    updates = ["status = ?"]
    params = [status]

    if finished_at:
        updates.append("finished_at = ?")
        params.append(finished_at)
    if error_message:
        updates.append("error_message = ?")
        params.append(str(error_message)[:2000])
    else: # Clear error message if status is not Failed
         if status != 'Failed':
              updates.append("error_message = NULL")
    if result_preview:
         updates.append("result_preview = ?")
         params.append(str(result_preview)[:500])
    # Removed clearing result_preview on fail, might want to keep last successful preview?

    sql = f"UPDATE agent_runs SET {', '.join(updates)} WHERE id = ?"
    params.append(run_id)

    try:
        with get_db_connection() as conn:
            conn.execute(sql, tuple(params))
            conn.commit()
            logger.info(f"Updated agent run ID {run_id} to status '{status}'.")
            return True
    except sqlite3.Error as e:
        logger.error(f"Error updating agent run ID {run_id} status to '{status}': {e}", exc_info=True)
        return False

def get_agent_runs(video_id, agent_type=None, target_id=None):
    """Retrieves agent run records for a video, optionally filtering."""
    sql = "SELECT * FROM agent_runs WHERE video_id = ?"
    params = [video_id]
    if agent_type:
        sql += " AND agent_type = ?"
        params.append(agent_type)
    if target_id:
        sql += " AND target_id = ?"
        params.append(target_id)
    sql += " ORDER BY created_at DESC"

    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching agent runs for video ID {video_id}: {e}", exc_info=True)
        return []

# ======================================
# === NEW: Clip Related DB Operations ===
# ======================================

def add_clip(video_id: int, clip_path: str, start_time: float, end_time: float, status: str = 'Pending', clip_type: str = 'batch') -> int | None:
    """Adds a new record to the 'clips' table and returns the new clip ID."""
    sql = """
        INSERT INTO clips (video_id, clip_path, start_time, end_time, status, clip_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, (video_id, clip_path, start_time, end_time, status, clip_type))
            new_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Added clip record ID: {new_id} for Video {video_id}, Path: {clip_path}")
            return new_id
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: clips.clip_path" in str(e):
             logger.error(f"DB Integrity Error: Clip path '{clip_path}' already exists.")
             # Handle duplicate path - maybe find existing clip ID?
             existing_clip = get_clip_by_path(clip_path)
             return existing_clip['id'] if existing_clip else None
        else:
             logger.error(f"DB Integrity Error adding clip for video {video_id}: {e}", exc_info=True)
             return None
    except sqlite3.Error as e:
        logger.error(f"Error adding clip record for video {video_id}: {e}", exc_info=True)
        return None

def update_clip_status(clip_id: int, status: str, error_message: str | None = None) -> bool:
    """Updates the status and optionally error message for a specific clip record."""
    sql = "UPDATE clips SET status = ?, error_message = ? WHERE id = ?"
    error_message_truncated = str(error_message)[:2000] if error_message else None
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (status, error_message_truncated, clip_id))
            conn.commit()
        logger.info(f"Updated clip ID {clip_id} status to '{status}'.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating status for clip ID {clip_id}: {e}", exc_info=True)
        return False

def update_clip_path(clip_id: int, clip_path: str) -> bool:
    """Updates the file path for a specific clip record (e.g., after editing)."""
    sql = "UPDATE clips SET clip_path = ? WHERE id = ?"
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (clip_path, clip_id))
            conn.commit()
        logger.info(f"Updated clip ID {clip_id} path to '{clip_path}'.")
        return True
    except sqlite3.IntegrityError as e: # Handle potential UNIQUE constraint violation
         logger.error(f"DB Integrity Error updating path for clip {clip_id}: Path '{clip_path}' likely already exists. Error: {e}")
         return False
    except sqlite3.Error as e:
        logger.error(f"Error updating path for clip ID {clip_id}: {e}", exc_info=True)
        return False

def get_clip_by_id(clip_id: int) -> dict | None:
    """Fetches a single clip record by its ID."""
    sql = "SELECT * FROM clips WHERE id = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (clip_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching clip by ID {clip_id}: {e}", exc_info=True)
        return None

def get_clip_by_path(clip_path: str) -> dict | None:
    """Fetches a single clip record by its path."""
    sql = "SELECT * FROM clips WHERE clip_path = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (clip_path,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching clip by path {clip_path}: {e}", exc_info=True)
        return None

def get_clips_for_video(video_id: int) -> list[dict]:
    """Retrieves all clip records associated with a video ID."""
    sql = "SELECT * FROM clips WHERE video_id = ? ORDER BY start_time ASC"
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql, (video_id,)).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching clips for video ID {video_id}: {e}", exc_info=True)
        return []

def add_clip_transcript(clip_id: int, transcript_data: list, status: str = 'Completed') -> bool:
    """Adds transcript data to the 'clip_transcripts' table."""
    sql = """
        INSERT INTO clip_transcripts (clip_id, transcript_json, status)
        VALUES (?, ?, ?)
        ON CONFLICT(clip_id) DO UPDATE SET
            transcript_json=excluded.transcript_json,
            status=excluded.status,
            error_message=NULL; -- Clear error on successful update
    """
    try:
        json_data = json.dumps(transcript_data, ensure_ascii=False)
        with get_db_connection() as conn:
            conn.execute(sql, (clip_id, json_data, status))
            conn.commit()
        logger.info(f"Added/Updated transcript for clip ID: {clip_id}")
        return True
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON data provided for clip {clip_id} transcript: {e}")
        # Optionally update status to Failed here
        update_clip_transcript_status(clip_id, 'Failed', f"Invalid JSON data: {e}")
        return False
    except sqlite3.Error as e:
        logger.error(f"Error adding transcript for clip ID {clip_id}: {e}", exc_info=True)
        update_clip_transcript_status(clip_id, 'Failed', f"DB error: {e}")
        return False

def update_clip_transcript_status(clip_id: int, status: str, error_message: str | None = None) -> bool:
    """Updates the status and error for a clip transcript record."""
    # Use INSERT OR IGNORE first to ensure a record exists, then UPDATE
    sql_ensure = "INSERT OR IGNORE INTO clip_transcripts (clip_id, status) VALUES (?, ?);"
    sql_update = "UPDATE clip_transcripts SET status = ?, error_message = ? WHERE clip_id = ?;"
    error_message_truncated = str(error_message)[:1000] if error_message else None
    try:
        with get_db_connection() as conn:
            conn.execute(sql_ensure, (clip_id, 'Pending')) # Ensure record exists
            conn.execute(sql_update, (status, error_message_truncated, clip_id))
            conn.commit()
        logger.info(f"Updated transcript status for clip ID {clip_id} to '{status}'.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating transcript status for clip ID {clip_id}: {e}", exc_info=True)
        return False

def get_clip_transcript(clip_id: int) -> dict | None:
    """Retrieves the transcript record for a specific clip."""
    sql = "SELECT * FROM clip_transcripts WHERE clip_id = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (clip_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching transcript for clip ID {clip_id}: {e}", exc_info=True)
        return None

def add_clip_metadata(clip_id: int, metadata_dict: dict, status: str = 'Completed') -> bool:
    """Adds metadata to the 'clip_metadata' table."""
    sql = """
        INSERT INTO clip_metadata (clip_id, title, description, keywords_json, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(clip_id) DO UPDATE SET
            title=excluded.title,
            description=excluded.description,
            keywords_json=excluded.keywords_json,
            status=excluded.status,
            error_message=NULL; -- Clear error on successful update
    """
    try:
        title = metadata_dict.get('title')
        description = metadata_dict.get('description')
        keywords = metadata_dict.get('keywords', [])
        keywords_json_data = json.dumps(keywords, ensure_ascii=False) if isinstance(keywords, list) else None

        with get_db_connection() as conn:
            conn.execute(sql, (clip_id, title, description, keywords_json_data, status))
            conn.commit()
        logger.info(f"Added/Updated metadata for clip ID: {clip_id}")
        return True
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON data provided for clip {clip_id} metadata keywords: {e}")
        update_clip_metadata_status(clip_id, 'Failed', f"Invalid JSON keywords: {e}")
        return False
    except sqlite3.Error as e:
        logger.error(f"Error adding metadata for clip ID {clip_id}: {e}", exc_info=True)
        update_clip_metadata_status(clip_id, 'Failed', f"DB error: {e}")
        return False

def update_clip_metadata_status(clip_id: int, status: str, error_message: str | None = None) -> bool:
    """Updates the status and error for a clip metadata record."""
    sql_ensure = "INSERT OR IGNORE INTO clip_metadata (clip_id, status) VALUES (?, ?);"
    sql_update = "UPDATE clip_metadata SET status = ?, error_message = ? WHERE clip_id = ?;"
    error_message_truncated = str(error_message)[:1000] if error_message else None
    try:
        with get_db_connection() as conn:
            conn.execute(sql_ensure, (clip_id, 'Pending')) # Ensure record exists
            conn.execute(sql_update, (status, error_message_truncated, clip_id))
            conn.commit()
        logger.info(f"Updated metadata status for clip ID {clip_id} to '{status}'.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating metadata status for clip ID {clip_id}: {e}", exc_info=True)
        return False

def get_clip_metadata(clip_id: int) -> dict | None:
    """Retrieves the metadata record for a specific clip."""
    sql = "SELECT * FROM clip_metadata WHERE clip_id = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (clip_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching metadata for clip ID {clip_id}: {e}", exc_info=True)
        return None

def get_clips_with_details(video_id: int) -> list[dict]:
    """Retrieves clips joined with their transcript and metadata."""
    sql = """
        SELECT
            c.id AS clip_id, c.video_id, c.clip_path, c.start_time, c.end_time,
            c.clip_type, c.status AS clip_status, c.error_message AS clip_error, c.created_at,
            ct.transcript_json, ct.status AS transcript_status, ct.error_message AS transcript_error,
            cm.title, cm.description, cm.keywords_json, cm.status AS metadata_status, cm.error_message AS metadata_error
        FROM clips c
        LEFT JOIN clip_transcripts ct ON c.id = ct.clip_id
        LEFT JOIN clip_metadata cm ON c.id = cm.clip_id
        WHERE c.video_id = ?
        ORDER BY c.start_time ASC
    """
    clips_detailed = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql, (video_id,)).fetchall()
            for row in rows:
                clip_dict = dict_from_row(row)
                # Parse JSON fields safely
                clip_dict['transcript'] = safe_json_load(clip_dict.get('transcript_json'), default_value=None, context_msg=f"clip {clip_dict['clip_id']} transcript")
                clip_dict['keywords'] = safe_json_load(clip_dict.get('keywords_json'), default_value=[], context_msg=f"clip {clip_dict['clip_id']} keywords")
                # Remove raw JSON fields if desired
                clip_dict.pop('transcript_json', None)
                clip_dict.pop('keywords_json', None)
                clips_detailed.append(clip_dict)
        return clips_detailed
    except sqlite3.Error as e:
        logger.error(f"Error fetching detailed clips for video ID {video_id}: {e}", exc_info=True)
        return []

# ======================================
# === NEW: MPP Table CRUD Operations ===
# ======================================

def add_mpp(name: str, constituency: str | None, party: str | None, active: bool = True) -> int | None:
    """Adds a new MPP record."""
    sql = """
        INSERT INTO mpps (name, constituency, party, active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            constituency=excluded.constituency,
            party=excluded.party,
            active=excluded.active,
            updated_at=CURRENT_TIMESTAMP;
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, (name, constituency, party, active))
            conn.commit()
            # Get the ID (might be existing or new)
            mpp = get_mpp_by_name(name)
            new_id = mpp['id'] if mpp else None
            if new_id:
                 logger.info(f"Added/Updated MPP record ID: {new_id}, Name: {name}")
            return new_id
    except sqlite3.Error as e:
        logger.error(f"Error adding/updating MPP {name}: {e}", exc_info=True)
        return None

def update_mpp(mpp_id: int, name: str = None, constituency: str = None, party: str = None, active: bool = None) -> bool:
    """Updates an existing MPP record by ID."""
    updates = []
    params = []
    if name is not None: updates.append("name = ?"); params.append(name)
    if constituency is not None: updates.append("constituency = ?"); params.append(constituency)
    if party is not None: updates.append("party = ?"); params.append(party)
    if active is not None: updates.append("active = ?"); params.append(active)

    if not updates: return False

    sql = f"UPDATE mpps SET {', '.join(updates)} WHERE id = ?"
    params.append(mpp_id)
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, tuple(params))
            conn.commit()
            if cursor.rowcount == 0:
                 logger.warning(f"Update MPP failed: No record found for ID {mpp_id}")
                 return False
            logger.info(f"Updated MPP record ID: {mpp_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"Error updating MPP ID {mpp_id}: {e}", exc_info=True)
        return False

def get_mpp_by_id(mpp_id: int) -> dict | None:
    """Fetches an MPP by ID."""
    sql = "SELECT * FROM mpps WHERE id = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (mpp_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching MPP by ID {mpp_id}: {e}", exc_info=True)
        return None

def get_mpp_by_name(name: str) -> dict | None:
    """Fetches an MPP by name."""
    sql = "SELECT * FROM mpps WHERE name = ?"
    try:
        with get_db_connection() as conn:
            row = conn.execute(sql, (name,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e:
        logger.error(f"Error fetching MPP by name {name}: {e}", exc_info=True)
        return None

def get_all_mpps(active_only: bool = True) -> list[dict]:
    """Fetches all MPP records, optionally filtering for active ones."""
    sql = "SELECT * FROM mpps"
    params = []
    if active_only:
        sql += " WHERE active = ?"
        params.append(True)
    sql += " ORDER BY name ASC"
    try:
        with get_db_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Error fetching all MPPs (active_only={active_only}): {e}", exc_info=True)
        return []

# ======================================
# === Reset Functions (For Regeneration) ===
# ======================================

# MODIFIED: Reset only remaining fields, explicitly delete Agent Runs (Clips handled by CASCADE on video delete)
def reset_video_analysis_results(video_id):
    """
    Resets processing status for a video, preparing it for reprocessing.
    Clears error messages and agent run history.
    Sets status to 'Pending', processing_status to 'Reprocessing Requested'.
    Does NOT delete associated clips/transcripts/metadata directly (rely on CASCADE if video is deleted later).
    """
    logger.warning(f"Resetting status and agent runs for Video ID: {video_id} for reprocessing.")
    # Update videos table: Reset status, processing_status, error_message
    sql_update_video = """
        UPDATE videos
        SET
            status = 'Pending',
            processing_status = 'Reprocessing Requested',
            error_message = NULL,
            manual_timestamps = NULL -- Also reset timestamps if desired
        WHERE id = ?
    """
    # Delete related agent runs
    sql_delete_agents = "DELETE FROM agent_runs WHERE video_id = ?"
    # Note: Deleting from clips, clip_transcripts, clip_metadata is NOT done here.
    # If a reset should clear clips, add explicit DELETEs for those tables by video_id.
    # For now, assume reset only affects status and agent runs for re-triggering download/processing.

    try:
        with get_db_connection() as conn:
            conn.execute("PRAGMA foreign_keys=ON;") # Ensure FKs are on for this connection
            conn.execute(sql_update_video, (video_id,))
            conn.execute(sql_delete_agents, (video_id,))
            conn.commit()
        logger.info(f"Successfully reset status and agent runs for Video ID: {video_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error resetting analysis results for video ID {video_id}: {e}", exc_info=True)
        return False

# --- END OF FILE database.py ---