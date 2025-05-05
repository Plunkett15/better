# --- START OF FILE config.py ---
import os
import torch
from dotenv import load_dotenv
import logging
import sys # For exiting on missing secret key

# --- Load Environment Variables ---
_basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(_basedir, '.env')

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded configuration settings from .env file.")
else:
    print("Warning: .env file not found. Using system environment variables or default settings.")

class Config:
    """Application Configuration Class"""

    # --- Core Flask Settings ---
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
    if not SECRET_KEY:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("FATAL ERROR: FLASK_SECRET_KEY is not set in your environment/.env file!")
        print("Please generate a secure key (e.g., python -c 'import secrets; print(secrets.token_hex(24))')")
        print("and set it in your .env file.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        sys.exit(1) # Exit if secret key is missing

    PORT = int(os.environ.get('PORT', 5001))
    WTF_CSRF_ENABLED = os.environ.get('WTF_CSRF_ENABLED', 'true').lower() == 'true'

    # --- Application Paths ---
    APP_ROOT = _basedir
    INSTANCE_FOLDER_PATH = os.environ.get('INSTANCE_FOLDER_PATH', os.path.join(APP_ROOT, 'instance'))
    DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(INSTANCE_FOLDER_PATH, 'videos.db'))
    DOWNLOAD_DIR = os.environ.get('DOWNLOAD_DIR', os.path.join(APP_ROOT, 'downloads'))
    PROCESSED_CLIPS_DIR = os.environ.get('PROCESSED_CLIPS_DIR', os.path.join(APP_ROOT, 'processed_clips'))

    # --- Logging Settings ---
    LOG_FILE_PATH = os.environ.get('LOG_FILE_PATH', os.path.join(INSTANCE_FOLDER_PATH, 'app.log'))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

    # --- Processing & Hardware Settings ---
    try:
        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        print(f"Warning: Error checking torch/cuda availability: {e}. Defaulting device to 'cpu'.")
        DEVICE = "cpu"
    print(f"Configuration: Determined processing device: {DEVICE.upper()}")

    # --- Faster-Whisper (Transcription) Settings ---
    FASTER_WHISPER_MODEL = os.environ.get('FASTER_WHISPER_MODEL', 'base.en')
    _default_compute = 'int8' if DEVICE == 'cpu' else 'float16'
    FASTER_WHISPER_COMPUTE_TYPE = os.environ.get('FASTER_WHISPER_COMPUTE_TYPE', _default_compute)
    print(f"Configuration: FasterWhisper Model='{FASTER_WHISPER_MODEL}', ComputeType='{FASTER_WHISPER_COMPUTE_TYPE}'")

    # --- Media Utilities (FFmpeg/FFprobe) Settings ---
    FFMPEG_PATH = os.environ.get('FFMPEG_PATH', 'ffmpeg')
    # Optional: Explicit path for ffprobe if it's not relative to ffmpeg
    FFPROBE_PATH = os.environ.get('FFPROBE_PATH', None) # Default to None, media_utils will guess if not set
    print(f"Configuration: FFmpeg Path='{FFMPEG_PATH}'")
    if FFPROBE_PATH:
        print(f"Configuration: Explicit FFprobe Path='{FFPROBE_PATH}'")
    else:
        print(f"Configuration: FFprobe Path=Not Set (will guess based on FFmpeg path)")


    # --- Celery/Background Worker Settings ---
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
    print(f"Configuration: Celery Broker URL='{CELERY_BROKER_URL}', Result Backend='{CELERY_RESULT_BACKEND}'")

    # --- Clipping & Editing Defaults ---
    CLIP_MIN_DURATION_SECONDS = float(os.environ.get('CLIP_MIN_DURATION_SECONDS', 1.5))
    CLIP_MANUAL_MAX_DURATION_SECONDS = float(os.environ.get('CLIP_MANUAL_MAX_DURATION_SECONDS', 120.0))
    # New Moviepy settings
    MOVIEPY_SHORT_CLIP_ASPECT_RATIO = float(os.environ.get('MOVIEPY_SHORT_CLIP_ASPECT_RATIO', 9/16))
    MOVIEPY_EDIT_METHOD = os.environ.get('MOVIEPY_EDIT_METHOD', 'crop') # 'crop' or 'resize' (resize not fully implemented yet)
    print(f"Configuration: Clip Duration Range Min={CLIP_MIN_DURATION_SECONDS}s, ManualMax={CLIP_MANUAL_MAX_DURATION_SECONDS}s")
    print(f"Configuration: Moviepy Short Clip Target Aspect Ratio={MOVIEPY_SHORT_CLIP_ASPECT_RATIO:.2f}, Method='{MOVIEPY_EDIT_METHOD}'")


    # --- Google Gemini Settings ---
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    GEMINI_MODEL_NAME = os.environ.get('GEMINI_MODEL_NAME', 'gemini-1.5-flash-latest')
    if GEMINI_API_KEY:
        print(f"Configuration: Gemini API Key=Loaded, Model='{GEMINI_MODEL_NAME}'")
    else:
        print("Configuration: Gemini API Key=NOT SET (Gemini features disabled)")


    # --- Static Method for Directory Creation (Call during app init) ---
    @staticmethod
    def check_and_create_dirs():
        """Checks/Creates essential application directories."""
        dirs_to_create = [
            Config.INSTANCE_FOLDER_PATH,
            Config.DOWNLOAD_DIR,
            Config.PROCESSED_CLIPS_DIR,
            os.path.dirname(Config.LOG_FILE_PATH) if Config.LOG_FILE_PATH else None
        ]
        print("\nChecking/Creating necessary directories...")
        for dir_path in dirs_to_create:
            if dir_path and not os.path.exists(dir_path):
                try:
                    os.makedirs(dir_path, exist_ok=True)
                    print(f" -> Created directory: {dir_path}")
                except OSError as e:
                    # Log error instead of just printing if logger is available
                    logging.getLogger(__name__).error(f"ERROR: Failed to create directory {dir_path}: {e}. Check permissions.")
            elif dir_path:
                 pass # Directory exists
        print("Directory check complete.")

# REMOVED: Automatic call to check_and_create_dirs() on import
# REMOVED: get_config() helper function

# --- END OF FILE config.py ---