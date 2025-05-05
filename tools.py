# --- Start of File: tools.py ---
import logging
import os
import json
import time

# --- Required for new Tools ---
# Moviepy imports (will be used inside EditingTool)
# import moviepy.editor as mp # Example import
# Google Gemini imports (will be used inside GeminiTool)
try:
    import google.generativeai as genai
except ImportError:
    genai = None # Allow code to load even if not installed yet
    logging.warning("Google Generative AI SDK not installed. GeminiTool will not function.")

# --- Existing Imports ---
from config import Config
import database as db # Direct access for DB operations
from utils import download as download_util
from utils import media_utils
from utils import error_utils
from analysis import transcription

logger = logging.getLogger(__name__)
config = Config()

# ================================================
# === Tool Definitions ===
# ================================================

class ToolError(Exception):
    """Custom exception for tool-specific errors (potentially retryable)."""
    pass

# --- File/Download Tools ---

class DownloadTool:
    """Wraps video download operations."""
    @staticmethod
    def download_video(url, output_dir, filename_base, resolution):
        """Calls the download utility."""
        logger.debug(f"DownloadTool: Downloading {url} to {output_dir}/{filename_base} at {resolution}")
        try:
            success, error_msg, final_path = download_util.download_video(url, output_dir, filename_base, resolution)
            if not success:
                # Treat download failures as potentially retryable ToolErrors
                raise ToolError(f"Download failed: {error_msg}")
            if not final_path or not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
                 raise ToolError("Download tool succeeded but final file is missing or empty.")
            logger.debug(f"DownloadTool: Success. File at {final_path}")
            return final_path
        except ToolError:
            raise # Re-raise ToolError directly
        except Exception as e:
            # Wrap unexpected errors during download in ToolError
            logger.error(f"Unexpected error in DownloadTool: {e}", exc_info=True)
            raise ToolError(f"Unexpected download error: {e}") from e


# --- Media Processing Tools ---

class MediaProcessingTool:
    """Wraps FFmpeg-based media operations."""
    @staticmethod
    def extract_audio(video_path, audio_output_path, sample_rate=16000, channels=1):
        """Calls the audio extraction utility."""
        logger.debug(f"MediaProcessingTool: Extracting audio from {video_path} to {audio_output_path}")
        if not media_utils.FFMPEG_AVAILABLE:
             # This is a configuration issue, not typically retryable
             raise ValueError("FFmpeg is not available, cannot extract audio.")
        try:
            success, error_msg = media_utils.extract_audio(video_path, audio_output_path, sample_rate, channels)
            if not success:
                # Treat ffmpeg execution errors as potentially retryable ToolErrors
                raise ToolError(f"Audio extraction failed: {error_msg}")
            if not os.path.exists(audio_output_path) or os.path.getsize(audio_output_path) == 0:
                 raise ToolError("Audio extraction tool succeeded but output file is missing or empty.")
            logger.debug(f"MediaProcessingTool: Audio extracted successfully to {audio_output_path}")
            return audio_output_path
        except ToolError:
             raise # Re-raise ToolError directly
        except Exception as e:
            # Wrap unexpected errors in ToolError
            logger.error(f"Unexpected error in MediaProcessingTool.extract_audio: {e}", exc_info=True)
            raise ToolError(f"Unexpected audio extraction error: {e}") from e


    @staticmethod
    def create_clip(input_video_path, output_clip_path, start_time, end_time, re_encode=True):
        """Calls the clip creation utility."""
        logger.debug(f"MediaProcessingTool: Creating clip {output_clip_path} ({start_time}-{end_time})")
        if not media_utils.FFMPEG_AVAILABLE:
             raise ValueError("FFmpeg is not available, cannot create clip.")
        try:
            success, result = media_utils.create_clip(input_video_path, output_clip_path, start_time, end_time, re_encode)
            if not success:
                # Result is error message on failure
                raise ToolError(f"Clip creation failed: {result}")
            # Result is path on success
            logger.debug(f"MediaProcessingTool: Clip created successfully at {result}")
            return result
        except ToolError:
            raise # Re-raise ToolError directly
        except Exception as e:
            logger.error(f"Unexpected error in MediaProcessingTool.create_clip: {e}", exc_info=True)
            raise ToolError(f"Unexpected clip creation error: {e}") from e

# --- Analysis Tools ---

class AnalysisTool:
    """Wraps analysis operations like transcription."""
    @staticmethod
    def transcribe_audio(audio_path, language=None, vad_filter=True, beam_size=5):
        """Calls the transcription utility."""
        logger.debug(f"AnalysisTool: Transcribing {audio_path}")
        try:
            success, segments_list_raw, error_msg = transcription.transcribe_audio(audio_path, language, vad_filter, beam_size)
            if not success:
                # Transcription failures (model load, OOM, etc.) could be ToolErrors
                raise ToolError(f"Transcription failed: {error_msg}")
            # Convert to simple dicts immediately
            segments_list_dict = [{'start': seg.start, 'end': seg.end, 'text': seg.text} for seg in segments_list_raw]
            logger.debug(f"AnalysisTool: Transcription successful ({len(segments_list_dict)} segments)")
            return segments_list_dict
        except ToolError:
            raise # Re-raise ToolError directly
        except Exception as e:
             logger.error(f"Unexpected error in AnalysisTool.transcribe_audio: {e}", exc_info=True)
             raise ToolError(f"Unexpected transcription error: {e}") from e

# --- Database Tool ---

class DatabaseTool:
    """
    Provides convenient access to database operations needed by agents and tasks.
    Primarily acts as a wrapper around functions in the database.py module.
    """

    @staticmethod
    def get_video_data(video_id: int) -> dict | None:
        """Fetches video data by ID."""
        try:
            return db.get_video_by_id(video_id)
        except db.sqlite3.Error as e:
            logger.error(f"DatabaseTool: Error fetching video {video_id}: {e}", exc_info=True)
            # Treat DB errors as potentially retryable
            raise ToolError(f"Database error fetching video {video_id}: {e}") from e

    @staticmethod
    def update_video_status(video_id: int, status: str | None = None, processing_status: str | None = None) -> bool:
        """Updates video status fields."""
        try:
            return db.update_video_status(video_id, status, processing_status)
        except db.sqlite3.Error as e:
            logger.error(f"DatabaseTool: Error updating status for video {video_id}: {e}", exc_info=True)
            raise ToolError(f"Database error updating status for video {video_id}: {e}") from e

    @staticmethod
    def update_video_error(video_id: int, error: Exception | str, processing_status: str = "Agent Error", status: str = "Error") -> bool:
        """Updates video error status and message."""
        error_msg_str = error_utils.format_error(error) if isinstance(error, Exception) else str(error)
        try:
            return db.update_video_error(video_id, error_msg_str, processing_status, status)
        except db.sqlite3.Error as e:
            logger.error(f"DatabaseTool: Error updating error status for video {video_id}: {e}", exc_info=True)
            raise ToolError(f"Database error updating error status for video {video_id}: {e}") from e

    @staticmethod
    def update_video_result(video_id: int, column_name: str, data: any) -> bool:
        """
        Updates a specific result column in the videos table.
        Delegates directly to the database module function.
        """
        try:
            # <<< REFACTORED: Directly call the database module function >>>
            return db.update_video_result(video_id, column_name, data)
        except db.sqlite3.Error as e:
            logger.error(f"DatabaseTool: Error updating result column '{column_name}' for video {video_id}: {e}", exc_info=True)
            raise ToolError(f"Database error updating result column '{column_name}' for video {video_id}: {e}") from e
        except ValueError as ve: # Catch validation errors from db function if any
             logger.error(f"DatabaseTool: Value error updating result column '{column_name}' for video {video_id}: {ve}")
             # ValueErrors are typically not retryable
             raise ve

    @staticmethod
    def update_video_path(video_id: int, file_path: str) -> bool:
        """Updates the main video file path."""
        try:
            return db.update_video_path(video_id, file_path)
        except db.sqlite3.Error as e:
             logger.error(f"DatabaseTool: Error updating file path for video {video_id}: {e}", exc_info=True)
             raise ToolError(f"Database error updating file path for video {video_id}: {e}") from e

    @staticmethod
    def update_video_audio_path(video_id: int, audio_path: str | None) -> bool:
        """Updates the temporary audio file path."""
        try:
             return db.update_video_audio_path(video_id, audio_path)
        except db.sqlite3.Error as e:
             logger.error(f"DatabaseTool: Error updating audio path for video {video_id}: {e}", exc_info=True)
             raise ToolError(f"Database error updating audio path for video {video_id}: {e}") from e

    # --- Agent Run Tracking ---
    @staticmethod
    def add_agent_run(video_id: int, agent_type: str, target_id: str | None = None, status: str = 'Pending') -> int | None:
        """Adds a new agent run record."""
        try:
            return db.add_agent_run(video_id, agent_type, target_id, status)
        except db.sqlite3.Error as e:
             logger.error(f"DatabaseTool: Error adding agent run for video {video_id}, agent {agent_type}: {e}", exc_info=True)
             raise ToolError(f"Database error adding agent run for video {video_id}: {e}") from e

    @staticmethod
    def update_agent_run_status(run_id: int, status: str, error_message: str | None = None, result_preview: str | None = None) -> bool:
        """Updates an agent run record's status."""
        try:
            return db.update_agent_run_status(run_id, status, error_message, result_preview)
        except db.sqlite3.Error as e:
            logger.error(f"DatabaseTool: Error updating agent run {run_id} status: {e}", exc_info=True)
            raise ToolError(f"Database error updating agent run {run_id} status: {e}") from e

    # --- Clip Management (Wrappers for new DB functions - Placeholders) ---
    @staticmethod
    def add_clip_record(video_id: int, clip_path: str, start_time: float, end_time: float, status: str = 'Pending', clip_type: str = 'batch') -> int | None:
        """Adds a new record to the 'clips' table."""
        logger.debug(f"DatabaseTool: Adding clip record for video {video_id}, path {clip_path}")
        # TODO: Implement db.add_clip in database.py
        # try:
        #     return db.add_clip(video_id, clip_path, start_time, end_time, status, clip_type)
        # except db.sqlite3.Error as e:
        #     logger.error(f"DatabaseTool: Error adding clip record for video {video_id}: {e}", exc_info=True)
        #     raise ToolError(f"Database error adding clip record: {e}") from e
        return int(time.time() * 1000) # Placeholder ID

    @staticmethod
    def update_clip_status(clip_id: int, status: str, error_message: str | None = None) -> bool:
        """Updates the status and optionally error message for a specific clip record."""
        logger.debug(f"DatabaseTool: Updating status for clip {clip_id} to '{status}'")
        # TODO: Implement db.update_clip_status in database.py
        # try:
        #     return db.update_clip_status(clip_id, status, error_message)
        # except db.sqlite3.Error as e:
        #     logger.error(f"DatabaseTool: Error updating status for clip {clip_id}: {e}", exc_info=True)
        #     raise ToolError(f"Database error updating clip status: {e}") from e
        return True # Placeholder

    @staticmethod
    def add_clip_transcript(clip_id: int, transcript_data: list) -> bool:
        """Adds transcript data to the 'clip_transcripts' table."""
        logger.debug(f"DatabaseTool: Adding transcript for clip {clip_id} ({len(transcript_data)} segments)")
        # TODO: Implement db.add_clip_transcript in database.py
        # try:
        #     return db.add_clip_transcript(clip_id, transcript_data)
        # except db.sqlite3.Error as e:
        #     logger.error(f"DatabaseTool: Error adding transcript for clip {clip_id}: {e}", exc_info=True)
        #     raise ToolError(f"Database error adding clip transcript: {e}") from e
        return True # Placeholder

    @staticmethod
    def add_clip_metadata(clip_id: int, metadata: dict) -> bool:
        """Adds metadata to the 'clip_metadata' table."""
        logger.debug(f"DatabaseTool: Adding metadata for clip {clip_id}")
        # TODO: Implement db.add_clip_metadata in database.py
        # try:
        #     return db.add_clip_metadata(clip_id, metadata)
        # except db.sqlite3.Error as e:
        #     logger.error(f"DatabaseTool: Error adding metadata for clip {clip_id}: {e}", exc_info=True)
        #     raise ToolError(f"Database error adding clip metadata: {e}") from e
        return True # Placeholder

    @staticmethod
    def safe_load_json(json_string: str | None, default_value: any = None, context: str = "") -> any:
        """Safely parses JSON, delegating to the database module function."""
        # No change needed here, just delegates
        return db.safe_json_load(json_string, default_value=default_value, context_msg=context)


# --- NEW: External API Tools ---

class GeminiTool:
    """
    Tool for interacting with the Google Gemini API.
    (Placeholder Implementation)
    """
    def __init__(self):
        self.client = None
        self.model = None
        if not genai:
            logger.error("GeminiTool: Google Generative AI SDK not imported.")
            return
        try:
            api_key = config.GEMINI_API_KEY
            if not api_key:
                logger.error("GeminiTool: GEMINI_API_KEY not found in configuration.")
                return

            genai.configure(api_key=api_key)
            # TODO: Choose appropriate model from config
            model_name = config.GEMINI_MODEL_NAME if hasattr(config, 'GEMINI_MODEL_NAME') else 'gemini-1.5-flash-latest'
            self.model = genai.GenerativeModel(model_name)
            logger.info(f"GeminiTool initialized with model: {model_name}")
            # Add safety settings configuration if needed
            # self.safety_settings = [...]
        except Exception as e:
            logger.error(f"GeminiTool: Failed to configure Gemini client: {e}", exc_info=True)
            self.model = None # Ensure model is None on failure

    def generate_metadata_for_clip(self, transcript: str | None = None, clip_path: str | None = None) -> dict | None:
        """
        Generates metadata (title, description, keywords) for a clip.
        Uses transcript text as primary input if available.
        (Requires actual implementation)
        """
        if not self.model:
            logger.error("GeminiTool.generate_metadata_for_clip: Tool not initialized.")
            # Raise ValueError for configuration issue (non-retryable)
            raise ValueError("GeminiTool is not configured correctly (API key or model issue).")

        # --- Input Validation ---
        if not transcript and not clip_path:
            raise ValueError("GeminiTool requires either transcript text or a clip path.")

        # --- Prepare Prompt ---
        # TODO: Develop a robust prompt engineering strategy
        prompt = f"""Analyze the following video clip transcript and generate relevant metadata.

Transcript:
---
{transcript if transcript else "Transcript not provided."}
---

Based ONLY on the transcript provided, generate the following metadata in JSON format:
{{
  "title": "A concise, engaging title for this clip (max 10 words)",
  "description": "A brief summary of the clip's content (1-2 sentences)",
  "keywords": ["list", "of", "relevant", "keywords", "or", "tags"]
}}

JSON Output:"""

        # --- API Call ---
        logger.debug(f"GeminiTool: Generating metadata for clip (input length approx {len(prompt)} chars)...")
        try:
            # TODO: Add safety_settings, generation_config if needed
            response = self.model.generate_content(prompt)

            # --- Response Parsing ---
            # TODO: Implement robust parsing of Gemini response, handle potential variations/errors in output format
            raw_json_text = response.text.strip().lstrip('```json').rstrip('```').strip()
            metadata = json.loads(raw_json_text)

            # Basic validation
            if not all(k in metadata for k in ["title", "description", "keywords"]):
                raise ToolError(f"Gemini response missing required metadata keys. Raw: {raw_json_text}")
            if not isinstance(metadata["keywords"], list):
                 raise ToolError(f"Gemini response 'keywords' is not a list. Raw: {raw_json_text}")

            logger.info(f"GeminiTool: Successfully generated metadata: {metadata.get('title')}")
            return metadata

        except json.JSONDecodeError as e:
             logger.error(f"GeminiTool: Failed to parse JSON response from API: {e}. Response text: {response.text[:500]}...")
             # Treat parsing failure as potentially retryable? Or permanent? Let's say ToolError for now.
             raise ToolError(f"Failed to parse Gemini JSON response: {e}") from e
        except Exception as e:
            # Handle various API errors (rate limits, connection, safety blocks etc.)
            logger.error(f"GeminiTool: API call failed: {e}", exc_info=True)
            # TODO: Check specific exception types from the SDK if available
            # Treat most API errors as potentially transient ToolErrors
            raise ToolError(f"Gemini API call failed: {e}") from e

# --- NEW: Video Editing Tool ---

class EditingTool:
    """
    Tool for performing video edits using Moviepy.
    (Placeholder Implementation)
    """
    def __init__(self):
        # Check if moviepy is available (optional, could do in methods)
        try:
            import moviepy.editor as mp
            self._mp = mp
            logger.info("EditingTool: Moviepy library loaded.")
        except ImportError:
            self._mp = None
            logger.error("EditingTool: Moviepy library not found. Install it (`pip install moviepy`).")

    def _check_init(self):
        """Checks if moviepy was imported correctly."""
        if not self._mp:
            raise ValueError("EditingTool cannot operate: Moviepy library not installed or loaded.")

    def apply_crop(self, input_path: str, output_path: str, crop_rect: dict) -> str:
        """
        Applies a crop to the video.
        crop_rect example: {'x1': 10, 'y1': 10, 'width': 640, 'height': 360} or {'x_center': 320, 'y_center': 180, ...}
        (Requires actual implementation)
        """
        self._check_init()
        logger.debug(f"EditingTool: Applying crop {crop_rect} to {input_path} -> {output_path}")
        if not os.path.exists(input_path):
             raise ValueError(f"Input file not found for cropping: {input_path}")

        try:
            # TODO: Implement moviepy cropping logic
            # clip = self._mp.VideoFileClip(input_path)
            # cropped_clip = clip.fx(self._mp.vfx.crop, **crop_rect) # Pass rect elements as kwargs
            # cropped_clip.write_videofile(output_path, codec='libx264', audio_codec='aac') # Specify codecs
            # clip.close()
            # cropped_clip.close()
            logger.info(f"EditingTool: Placeholder - Cropped video saved to {output_path}")
            # Simulate success by ensuring output file exists (copy input for placeholder)
            if not os.path.exists(output_path):
                import shutil
                shutil.copy(input_path, output_path)
            return output_path
        except Exception as e:
            logger.error(f"EditingTool: Failed to apply crop to {input_path}: {e}", exc_info=True)
            # Treat moviepy/ffmpeg errors during processing as potentially retryable ToolErrors
            raise ToolError(f"Moviepy crop failed: {e}") from e

    def change_aspect_ratio(self, input_path: str, output_path: str, new_aspect: float = 9/16, method: str = 'crop') -> str:
        """
        Changes the aspect ratio, typically for vertical video (9/16).
        Methods: 'crop' (center crop), 'resize' (letterbox/pillarbox - less common).
        (Requires actual implementation)
        """
        self._check_init()
        logger.debug(f"EditingTool: Changing aspect ratio of {input_path} to {new_aspect} using {method} -> {output_path}")
        if not os.path.exists(input_path):
             raise ValueError(f"Input file not found for aspect ratio change: {input_path}")

        try:
            # TODO: Implement moviepy resize/crop logic for aspect ratio
            # clip = self._mp.VideoFileClip(input_path)
            # original_w, original_h = clip.size
            # original_aspect = original_w / original_h
            # target_w, target_h = ... # Calculate target dimensions based on new_aspect and original size
            # if method == 'crop':
            #    # Calculate crop parameters (likely center crop)
            #    crop_w, crop_h = ...
            #    crop_x = (original_w - crop_w) / 2
            #    crop_y = (original_h - crop_h) / 2
            #    edited_clip = clip.fx(self._mp.vfx.crop, x1=crop_x, y1=crop_y, width=crop_w, height=crop_h)
            # elif method == 'resize':
            #    # Resize preserving aspect, may need padding later (more complex)
            #    edited_clip = clip.fx(self._mp.vfx.resize, width=target_w) # Or height=target_h
            # else:
            #    raise ValueError(f"Unsupported aspect ratio change method: {method}")
            # edited_clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
            # clip.close()
            # edited_clip.close()
            logger.info(f"EditingTool: Placeholder - Changed aspect ratio, video saved to {output_path}")
            # Simulate success
            if not os.path.exists(output_path):
                import shutil
                shutil.copy(input_path, output_path)
            return output_path
        except Exception as e:
            logger.error(f"EditingTool: Failed to change aspect ratio for {input_path}: {e}", exc_info=True)
            raise ToolError(f"Moviepy aspect ratio change failed: {e}") from e

# --- Tool Registry (Optional, for dynamic lookup) ---
# TOOL_REGISTRY = {
#     "download": DownloadTool,
#     "media": MediaProcessingTool,
#     "analysis": AnalysisTool,
#     "db": DatabaseTool,
#     "gemini": GeminiTool,
#     "editing": EditingTool,
# }
# --- END OF FILE tools.py ---