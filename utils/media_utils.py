# --- Start of File: utils/media_utils.py ---

import subprocess
import os
import logging
import datetime
import json
import re
import time
# --- NEW: Import moviepy ---
try:
    import moviepy.editor as mp
    import moviepy.video.fx.all as vfx
    MOVIEPY_AVAILABLE = True
except ImportError:
    mp = None
    vfx = None
    MOVIEPY_AVAILABLE = False
    logging.getLogger(__name__).warning("Moviepy library not found. Install moviepy (`pip install moviepy`) for editing features.")

from config import Config

logger = logging.getLogger(__name__)
config = Config()

# --- FFmpeg/FFprobe Path Configuration & Check ---
FFMPEG_PATH = config.FFMPEG_PATH
# Check for explicit FFPROBE_PATH in config first
FFPROBE_PATH_EXPLICIT = getattr(config, 'FFPROBE_PATH', None) # Use getattr for safe access

_FFMPEG_CHECKED = False
_FFPROBE_CHECKED = False
FFMPEG_AVAILABLE = False
FFPROBE_AVAILABLE = False
FFPROBE_PATH_USED = None # Store the actual path being used

# Derive ffprobe path guess only if explicit path is not provided
FFPROBE_PATH_GUESS = None
if not FFPROBE_PATH_EXPLICIT:
    try:
        if FFMPEG_PATH and isinstance(FFMPEG_PATH, str):
            ffmpeg_lower = FFMPEG_PATH.lower()
            if ffmpeg_lower == 'ffmpeg':
                FFPROBE_PATH_GUESS = 'ffprobe'
            elif 'ffmpeg' in ffmpeg_lower:
                base_path = os.path.dirname(FFMPEG_PATH)
                probe_exe = "ffprobe.exe" if ffmpeg_lower.endswith(".exe") else "ffprobe"
                FFPROBE_PATH_GUESS = os.path.join(base_path, probe_exe)
            else:
                logger.warning(f"Could not confidently determine ffprobe path from non-standard ffmpeg path: '{FFMPEG_PATH}'. Guessing 'ffprobe'.")
                FFPROBE_PATH_GUESS = 'ffprobe' # Fallback guess
        else:
            logger.warning(f"FFMPEG_PATH '{FFMPEG_PATH}' is not a valid string. Guessing 'ffprobe'.")
            FFPROBE_PATH_GUESS = 'ffprobe'
    except Exception as path_err:
         logger.error(f"Error constructing ffprobe path guess from '{FFMPEG_PATH}': {path_err}")
         FFPROBE_PATH_GUESS = 'ffprobe' # Fallback guess on error
else:
     logger.info(f"Using explicitly configured FFPROBE_PATH: {FFPROBE_PATH_EXPLICIT}")


def check_ffmpeg_tools():
    """Checks if ffmpeg and ffprobe commands are available and updates global flags."""
    global _FFMPEG_CHECKED, _FFPROBE_CHECKED, FFMPEG_AVAILABLE, FFPROBE_AVAILABLE, FFPROBE_PATH_USED

    # Check ffmpeg (remains the same)
    if not _FFMPEG_CHECKED:
        logger.info(f"Checking for FFmpeg executable at: {FFMPEG_PATH}")
        try:
            result = subprocess.run(
                [FFMPEG_PATH, "-version"], check=True, capture_output=True, text=True,
                encoding='utf-8', timeout=10
            )
            if "ffmpeg version" in result.stdout.lower():
                logger.info(f"FFmpeg check successful. Version info detected:\n{result.stdout.splitlines()[0]}")
                FFMPEG_AVAILABLE = True
            else:
                 logger.warning(f"FFmpeg command ran but version string not found in output.")
                 FFMPEG_AVAILABLE = False
        except FileNotFoundError:
            logger.error(f"FFmpeg command '{FFMPEG_PATH}' not found. Ensure FFmpeg is installed and in PATH or set FFMPEG_PATH.")
            FFMPEG_AVAILABLE = False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, PermissionError) as e:
            logger.error(f"Error executing FFmpeg version check ('{FFMPEG_PATH} -version'): {e}")
            FFMPEG_AVAILABLE = False
        except Exception as e:
            logger.error(f"Unexpected error during FFmpeg check: {e}", exc_info=True)
            FFMPEG_AVAILABLE = False
        finally:
             _FFMPEG_CHECKED = True

    # Check ffprobe (prioritize explicit path)
    if not _FFPROBE_CHECKED:
        path_to_check = FFPROBE_PATH_EXPLICIT if FFPROBE_PATH_EXPLICIT else FFPROBE_PATH_GUESS
        source = "explicit config" if FFPROBE_PATH_EXPLICIT else "guessed path"

        if not path_to_check: # Should not happen if guess has fallback, but safety
            logger.error("FFprobe check skipped: No path could be determined.")
            FFPROBE_AVAILABLE = False
            _FFPROBE_CHECKED = True
            return FFMPEG_AVAILABLE # Return ffmpeg status

        logger.info(f"Checking for FFprobe executable at ({source}): {path_to_check}")
        try:
            result = subprocess.run(
                [path_to_check, "-version"], check=True, capture_output=True,
                text=True, encoding='utf-8', timeout=10
            )
            if "ffprobe version" in result.stdout.lower():
                 logger.info(f"FFprobe check successful. Version info detected:\n{result.stdout.splitlines()[0]}")
                 FFPROBE_AVAILABLE = True
                 FFPROBE_PATH_USED = path_to_check # Store the successful path
            else:
                  logger.warning(f"FFprobe command ran but version string not found in output.")
                  FFPROBE_AVAILABLE = False
        except FileNotFoundError:
            logger.error(f"FFprobe command '{path_to_check}' not found ({source}). Check installation/config.")
            FFPROBE_AVAILABLE = False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, PermissionError) as e:
            logger.error(f"Error executing FFprobe version check ('{path_to_check} -version'): {e}")
            FFPROBE_AVAILABLE = False
        except Exception as e:
             logger.error(f"Unexpected error during FFprobe check: {e}", exc_info=True)
             FFPROBE_AVAILABLE = False
        finally:
            _FFPROBE_CHECKED = True

    return FFMPEG_AVAILABLE # Return primary tool status

# Run check automatically when module is loaded
check_ffmpeg_tools()


def _run_ffmpeg_command(command, description="ffmpeg operation"):
    """Helper to run an FFmpeg command list, check availability, handle errors, log output."""
    if not FFMPEG_AVAILABLE:
        err_msg = f"FFmpeg is not available or configured correctly (checked path: {FFMPEG_PATH}). Cannot run '{description}'."
        logger.error(err_msg)
        return False, err_msg

    logger.info(f"Running FFmpeg for '{description}': {' '.join(command)}")
    start_time = time.time()

    output_path = None
    if command and not command[-1].startswith('-'):
         output_path = command[-1]

    try:
        if output_path:
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    logger.info(f"Created directory for FFmpeg output: {output_dir}")
                except OSError as e:
                     err = f"Failed to create output directory '{output_dir}' for FFmpeg '{description}': {e}"
                     logger.error(err)
                     return False, err

        process = subprocess.run(
            command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', timeout=7200
        )
        elapsed = time.time() - start_time

        # --- Verify Output Post-Success ---
        output_ok = True
        validation_error_msg = None
        if output_path:
            if not os.path.exists(output_path):
                 validation_error_msg = f"FFmpeg command '{description}' reported success, but output file '{output_path}' does NOT exist."
                 logger.error(validation_error_msg) # Log as error now
                 output_ok = False
            elif os.path.getsize(output_path) == 0:
                 validation_error_msg = f"FFmpeg command '{description}' reported success, but output file '{output_path}' is EMPTY (0 bytes)."
                 logger.error(validation_error_msg) # Log as error
                 output_ok = False

        if output_ok:
             logger.info(f"FFmpeg '{description}' completed successfully in {elapsed:.2f}s. Output path: {output_path or '(N/A)'}")
        if process.stderr:
            stderr_lines = process.stderr.strip().splitlines()
            log_limit = 20
            log_stderr = "\n".join(stderr_lines[:log_limit]) + ("\n...\n" + "\n".join(stderr_lines[-log_limit:]) if len(stderr_lines) > log_limit * 2 else "")
            logger.debug(f"FFmpeg stderr output for '{description}' ({len(stderr_lines)} lines total):\n{log_stderr}")

        if not output_ok:
            # Return success=False if output validation failed, include validation error
            return False, validation_error_msg or "Output validation failed (unknown reason)."

        return True, None # Success

    except FileNotFoundError:
        err = f"FFmpeg command '{FFMPEG_PATH}' was not found during execution attempt. Check installation and PATH."
        logger.error(err)
        return False, err
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        err = f"FFmpeg command '{description}' timed out after {elapsed:.0f} seconds. Process was killed."
        logger.error(err)
        # Cleanup attempt
        if output_path and os.path.exists(output_path):
            try: os.remove(output_path); logger.info(f"Removed potentially incomplete output file: {output_path}")
            except OSError as rm_err: logger.warning(f"Failed to remove incomplete output file '{output_path}' after timeout: {rm_err}")
        return False, err
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        stderr_content = e.stderr.strip() if e.stderr else "No stderr captured."
        error_lines = [line for line in stderr_content.splitlines() if 'error' in line.lower() or 'failed' in line.lower()]
        error_hint = f"Error hint: ...{error_lines[-1][-180:]}" if error_lines else f"Last stderr: ...{stderr_content[-180:]}" if stderr_content else "No informative error message in stderr."
        err = f"FFmpeg command '{description}' failed after {elapsed:.1f}s with exit code {e.returncode}. {error_hint}"
        logger.error(err)
        logger.debug(f"Failed FFmpeg command was: {' '.join(e.cmd)}")
        if e.stderr: logger.debug(f"Full FFmpeg stderr:\n{e.stderr.strip()}")
        # Cleanup attempt
        if output_path and os.path.exists(output_path):
            try: os.remove(output_path); logger.info(f"Removed potentially corrupted output file: {output_path}")
            except OSError as rm_err: logger.warning(f"Failed to remove failed output file '{output_path}': {rm_err}")
        return False, err
    except Exception as e:
        elapsed = time.time() - start_time
        err = f"Unexpected Python error during FFmpeg '{description}' execution after {elapsed:.1f}s: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True)
        # Cleanup attempt
        if output_path and os.path.exists(output_path):
             try: os.remove(output_path); logger.info(f"Removed potentially affected output file: {output_path}")
             except OSError as rm_err: logger.warning(f"Failed to remove output file '{output_path}' after Python error: {rm_err}")
        return False, err

# --- Core Media Functions ---

def extract_audio(video_path, audio_output_path, sample_rate=16000, channels=1):
    """Extracts audio from a video file using FFmpeg."""
    if not os.path.exists(video_path):
        return False, f"Input video file not found: {video_path}"
    if not FFMPEG_AVAILABLE: # Add check here too
        return False, "FFmpeg is not available."

    command = [
        FFMPEG_PATH, '-hide_banner', '-loglevel', 'warning', '-y',
        '-i', video_path, '-vn', '-acodec', 'pcm_s16le',
        '-ac', str(channels), '-ar', str(sample_rate), audio_output_path
    ]
    return _run_ffmpeg_command(command, f"audio extraction ({sample_rate}Hz, {channels}-ch)")

def create_clip(input_video_path, output_clip_path, start_time, end_time, re_encode=True):
    """Creates a video clip using FFmpeg."""
    if not os.path.exists(input_video_path):
        return False, f"Input video file not found for clipping: {input_video_path}"
    if not FFMPEG_AVAILABLE:
        return False, "FFmpeg is not available."

    duration = round(end_time - start_time, 3)
    if duration <= 0:
        return False, f"Invalid clip duration: start={start_time:.3f}s, end={end_time:.3f}s"

    # --- Boundary Check ---
    source_duration = get_video_duration(input_video_path) # Uses updated ffprobe path logic
    if source_duration is not None:
         if start_time < 0: start_time = 0.0
         if end_time > source_duration + 0.5: end_time = source_duration
         duration = round(end_time - start_time, 3)
         if duration <= 0:
             return False, f"Invalid clip duration after clamping ({start_time:.3f}s - {end_time:.3f}s)."

    # Build FFmpeg command (remains the same)
    description = f"clip creation ({start_time:.3f}s to {end_time:.3f}s, duration {duration:.3f}s)"
    command = [
        FFMPEG_PATH, '-hide_banner', '-loglevel', 'warning',
        '-i', input_video_path, '-ss', f"{start_time:.3f}", '-to', f"{end_time:.3f}",
        '-y', '-map_metadata', '-1', '-map_chapters', '-1',
    ]
    if re_encode:
        description += " [Re-encode]"
        command.extend([
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
            '-movflags', '+faststart'
        ])
    else:
        description += " [Stream Copy]"
        command.extend(['-c', 'copy', '-avoid_negative_ts', 'make_zero'])
    command.append(output_clip_path)

    success, result = _run_ffmpeg_command(command, description)
    if success:
        return True, output_clip_path # Return path on success
    else:
        return False, result # Return error message on failure


def time_str_to_seconds(time_str: str) -> float | None:
    """Converts HH:MM:SS.ms, MM:SS.ms, or SS.ms string to seconds."""
    # --- Logic remains the same ---
    if not time_str or not isinstance(time_str, str): return None
    time_str = time_str.strip()
    parts = time_str.split(':')
    try:
        if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1: return float(parts[0])
        else: return None
    except (ValueError, TypeError): return None

# MODIFIED: Use FFPROBE_PATH_USED determined by check_ffmpeg_tools
def get_video_duration(video_path):
    """Gets the duration of a video file in seconds using ffprobe. Returns None on failure."""
    if not FFPROBE_AVAILABLE or not FFPROBE_PATH_USED:
        logger.warning(f"Cannot get video duration: ffprobe is not available or path not determined (Used Path: {FFPROBE_PATH_USED}).")
        return None
    if not os.path.exists(video_path):
         logger.warning(f"Cannot get video duration: File not found at '{video_path}'")
         return None

    # Use the path confirmed during the check
    ffprobe_cmd_path = FFPROBE_PATH_USED

    command = [
        ffprobe_cmd_path, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', video_path
    ]
    description = f"duration query for {os.path.basename(video_path)}"
    logger.debug(f"Running ffprobe for {description}: {' '.join(command)}")

    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True,
            encoding='utf-8', timeout=60
        )
        duration_str = result.stdout.strip().split('\n')[0] # Use first line

        if not duration_str or duration_str.lower() == 'n/a':
             logger.warning(f"ffprobe did not return a valid duration value for '{video_path}'. Output: '{duration_str}'.")
             return None # Avoid fallback loop for simplicity now

        duration_sec = float(duration_str)
        if duration_sec < 0:
             logger.warning(f"ffprobe returned negative duration ({duration_sec:.3f}s) for '{video_path}'.")
             return None

        logger.info(f"Duration of '{os.path.basename(video_path)}': {duration_sec:.3f} seconds.")
        return duration_sec
    except FileNotFoundError:
        logger.error(f"ffprobe command '{ffprobe_cmd_path}' not found during execution attempt.")
        # Mark as unavailable if it fails here after passing check initially
        global FFPROBE_AVAILABLE
        FFPROBE_AVAILABLE = False
        return None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError) as e:
        stderr_msg = getattr(e, 'stderr', '(no stderr captured)').strip()
        logger.error(f"ffprobe failed for '{video_path}': {type(e).__name__}: {e}. Stderr: {stderr_msg}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting video duration for '{video_path}': {e}", exc_info=True)
        return None


def sanitize_filename(filename, max_len=200, replacement_char='_'):
    """Removes or replaces characters problematic for filenames, limiting length."""
    # --- Logic remains the same ---
    if not isinstance(filename, str) or not filename:
        return f"sanitized_empty_filename_{int(time.time())}"
    filename = filename.strip().strip('.' + replacement_char)
    bad_chars_pattern = r'[<>:"/\\|?*\x00-\x1F%\']'
    filename = re.sub(bad_chars_pattern, replacement_char, filename)
    pattern = r'[\s' + re.escape(replacement_char) + r']+'
    filename = re.sub(pattern, replacement_char, filename)
    try:
        filename_bytes = filename.encode('utf-8')
        if len(filename_bytes) > max_len:
            cut_pos = max_len
            while cut_pos > 0 and (filename_bytes[cut_pos] & 0xC0) == 0x80: cut_pos -= 1
            if cut_pos == 0 and max_len > 0: cut_pos = max_len
            filename_bytes = filename_bytes[:cut_pos]
            filename = filename_bytes.decode('utf-8', errors='ignore').rstrip(replacement_char)
    except Exception as e:
        logger.warning(f"Error during filename length sanitization: {e}. Using basic slice.")
        filename = filename[:max_len]
    name_part, dot, ext_part = filename.rpartition('.')
    base_name_to_check = name_part if dot else filename
    reserved_names = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}
    if base_name_to_check.upper() in reserved_names:
        filename = filename + replacement_char
    if not filename or filename == replacement_char:
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"sanitized_file_{timestamp}"
    return filename

# ======================================
# === NEW: Moviepy Wrapper Functions ===
# ======================================

def apply_moviepy_crop(input_path: str, output_path: str, crop_rect: dict) -> tuple[bool, str]:
    """
    Applies a crop using Moviepy.
    crop_rect example: {'x1': 10, 'y1': 10, 'width': 640, 'height': 360}
                     or {'x_center': 320, 'y_center': 180, 'width': 640, 'height': 360}
    Returns: (success: bool, result: str) - result is output_path or error message.
    """
    if not MOVIEPY_AVAILABLE:
        return False, "Moviepy library not installed or loaded."
    if not os.path.exists(input_path):
        return False, f"Input file not found for cropping: {input_path}"
    if not crop_rect or not isinstance(crop_rect, dict):
        return False, "Invalid crop_rect dictionary provided."

    logger.info(f"Applying moviepy crop {crop_rect} to '{os.path.basename(input_path)}' -> '{os.path.basename(output_path)}'")
    clip = None
    cropped_clip = None
    try:
        # Load clip
        clip = mp.VideoFileClip(input_path)
        # Apply crop effect
        cropped_clip = clip.fx(vfx.crop, **crop_rect)
        # Write output - specify codecs for compatibility
        # TODO: Make codecs/preset configurable?
        cropped_clip.write_videofile(output_path, codec='libx264', audio_codec='aac', preset='medium', logger='bar') # Use preset='medium'
        logger.info(f"Moviepy crop successful: {output_path}")
        return True, output_path
    except Exception as e:
        err_msg = f"Moviepy crop failed: {e}"
        logger.error(f"{err_msg} for input {input_path}", exc_info=True)
        # Cleanup potentially partially written file
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except OSError: pass
        return False, err_msg
    finally:
        # Ensure clips are closed to release file handles
        if cropped_clip:
            try: cropped_clip.close()
            except Exception: pass
        if clip:
            try: clip.close()
            except Exception: pass

def apply_moviepy_aspect_change(input_path: str, output_path: str, target_aspect: float = (9/16), method: str = 'crop') -> tuple[bool, str]:
    """
    Changes aspect ratio using Moviepy (default: center crop to 9:16).
    Returns: (success: bool, result: str) - result is output_path or error message.
    """
    if not MOVIEPY_AVAILABLE:
        return False, "Moviepy library not installed or loaded."
    if not os.path.exists(input_path):
        return False, f"Input file not found for aspect change: {input_path}"

    logger.info(f"Applying moviepy aspect change ({target_aspect:.2f}, method={method}) to '{os.path.basename(input_path)}' -> '{os.path.basename(output_path)}'")
    clip = None
    edited_clip = None
    try:
        clip = mp.VideoFileClip(input_path)
        original_w, original_h = clip.size

        if method == 'crop':
            # Calculate center crop dimensions
            target_w, target_h = original_w, original_h
            current_aspect = original_w / original_h

            if abs(current_aspect - target_aspect) < 0.01: # Already correct aspect ratio
                 logger.info("Skipping aspect change crop: Input already has target aspect ratio.")
                 # Copy file if output path is different, otherwise do nothing
                 if input_path != output_path:
                      import shutil
                      shutil.copy(input_path, output_path)
                 return True, output_path

            if current_aspect > target_aspect: # Wider than target (e.g., 16:9 -> 9:16) - Crop width
                target_w = int(original_h * target_aspect)
                crop_x = (original_w - target_w) / 2
                crop_y = 0
            else: # Taller than target (e.g., 4:3 -> 16:9) - Crop height
                target_h = int(original_w / target_aspect)
                crop_x = 0
                crop_y = (original_h - target_h) / 2

            logger.debug(f"Calculated crop params: x={crop_x:.1f}, y={crop_y:.1f}, w={target_w}, h={target_h}")
            edited_clip = clip.fx(vfx.crop, x1=crop_x, y1=crop_y, width=target_w, height=target_h)

        # elif method == 'resize': # Resize with potential letter/pillar boxing (more complex to implement well)
        #     logger.warning("Resize method for aspect change not fully implemented, may result in distortion or require padding.")
        #     edited_clip = clip.fx(vfx.resize, width=...) # Requires calculating target size and potentially adding padding
        #     return False, "Resize method not fully implemented"
        else:
            return False, f"Unsupported aspect ratio change method: {method}"

        # Write output
        edited_clip.write_videofile(output_path, codec='libx264', audio_codec='aac', preset='medium', logger='bar')
        logger.info(f"Moviepy aspect change successful: {output_path}")
        return True, output_path

    except Exception as e:
        err_msg = f"Moviepy aspect change failed: {e}"
        logger.error(f"{err_msg} for input {input_path}", exc_info=True)
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except OSError: pass
        return False, err_msg
    finally:
        if edited_clip:
            try: edited_clip.close()
            except Exception: pass
        if clip:
            try: clip.close()
            except Exception: pass

# --- END OF FILE utils/media_utils.py ---