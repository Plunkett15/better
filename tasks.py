# --- Start of File: tasks.py ---
import logging
import time
import os
from celery import Task, group, chain, chord
from celery.exceptions import Ignore, MaxRetriesExceededError

from celery_app import celery_app # Import the Celery app instance
import database as db
from utils import error_utils
# Import specific media utils (create_clip, extract_audio, get_video_duration, sanitize_filename)
from utils import media_utils
from analysis import transcription # For process_clip_task
from tools import MediaProcessingTool # Only used by run_agent_task currently
# Import agents and registry (AGENT_REGISTRY is now smaller)
from agents import AGENT_REGISTRY, BaseAgent, AgentError
from config import Config
from tools import ToolError # Still used by DownloaderAgent

# TODO: Uncomment these when implemented
# from tools import GeminiTool # For metadata generation
# from tools import EditingTool # Or import moviepy wrappers from media_utils

logger = logging.getLogger(__name__)
config = Config()

# ============================================
# === Main Video Processing Orchestrator Task ===
# ============================================
@celery_app.task(bind=True, name='tasks.process_video_orchestrator')
def process_video_orchestrator_task(self: Task, video_id: int, skip_download: bool = False):
    """
    Initiates the video processing pipeline.
    Now simplified: only dispatches the DownloaderAgent if needed.
    """
    pipeline_start_time = time.time()
    logger.info(f"--- Starting Video Processing Orchestrator for Video ID: {video_id} (Task ID: {self.request.id}, SkipDownload: {skip_download}) ---")
    try:
        video_data = db.get_video_by_id(video_id)
        if not video_data:
            logger.warning(f"Orchestrator: Video ID {video_id} not found at start. Aborting.")
            return {"status": "Aborted", "message": f"Video ID {video_id} not found."}

        db.update_video_status(video_id, status='Queued', processing_status='Orchestrator Started')

        # --- Simplified Agent Dispatch ---
        agent_to_dispatch = None
        if not skip_download:
            agent_to_dispatch = 'downloader'
        else:
            # If skipping download, check if file exists. If not, still need downloader.
            video_path = video_data.get('file_path')
            if not video_path or not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
                logger.warning(f"SkipDownload=True but video file missing/empty ({video_path}). Falling back to Downloader.")
                agent_to_dispatch = 'downloader'
            else:
                logger.info(f"SkipDownload=True and video file exists. No initial agent dispatched by orchestrator.")
                # The core automated pipeline effectively ends after download verification if skipped.
                # Manual actions (clipping) can proceed.
                # Update status to reflect download is done/skipped.
                db.update_video_status(video_id, status='Processed', processing_status='Ready for Clipping (Download Skipped)')

        if agent_to_dispatch:
            # Verify video still exists before dispatching
            if not db.get_video_by_id(video_id):
                 logger.warning(f"Orchestrator: Video ID {video_id} not found before dispatching '{agent_to_dispatch}'. Aborting.")
                 return {"status": "Aborted", "message": f"Video ID {video_id} not found."}

            logger.info(f"Orchestrator dispatching agent: '{agent_to_dispatch}' for video {video_id}")
            run_agent_task.delay(video_id, agent_to_dispatch)
            db.update_video_status(video_id, processing_status=f"Dispatched {agent_to_dispatch} agent")
        else:
            # If no agent dispatched (skip_download=True and file exists)
            logger.info(f"Orchestrator: No initial agent dispatched for video {video_id}.")


        duration = time.time() - pipeline_start_time
        logger.info(f"--- Orchestrator finished for Video ID: {video_id} in {duration:.2f}s (Task ID: {self.request.id}) ---")
        return {"status": "Success", "dispatched_agent": agent_to_dispatch}

    except Exception as e:
        error_msg = f"Orchestrator task failed critically for video {video_id}: {e}"
        logger.critical(error_msg, exc_info=True)
        # Attempt to update video status to Error
        if db.get_video_by_id(video_id):
             db.update_video_error(video_id, error_utils.format_error(e), "Orchestration Error")
        # Raise ignore to prevent celery retries for critical orchestrator errors
        raise Ignore()


# ============================================
# === Generic Agent Runner Task ===
# ============================================
# Note: Currently only used by DownloaderAgent. Keep for potential future agents.
@celery_app.task(
    bind=True,
    name='tasks.run_agent_task',
    autoretry_for=(ToolError,), # Retry on network/disk issues from DownloaderTool
    retry_kwargs={'max_retries': 2, 'countdown': 30}
)
def run_agent_task(self: Task, video_id: int, agent_type: str, target_id: str | None = None):
    """Executes a specific agent's run() method."""
    task_id = self.request.id
    logger.info(f"--- Starting Agent Task: Video={video_id}, Agent='{agent_type}', Target='{target_id}' (Task ID: {task_id}, Attempt: {self.request.retries + 1}) ---")
    run_id = None
    agent_instance: BaseAgent | None = None
    start_time = time.time()

    if not db.get_video_by_id(video_id):
        logger.warning(f"Agent Task {task_id} (Agent: {agent_type}): Video ID {video_id} not found. Aborting task.")
        return {"status": "Aborted", "message": f"Video ID {video_id} not found."}

    try:
        # --- Record/Find Agent Run ---
        run_id = db.add_agent_run(video_id, agent_type, target_id, status='Pending')
        if not run_id:
            raise ToolError(f"Failed to create agent run record in DB for Video {video_id}, Agent '{agent_type}'. Retrying...")

        db.update_agent_run_status(run_id, status='Running')

        # --- Instantiate Agent ---
        agent_class = AGENT_REGISTRY.get(agent_type)
        if not agent_class:
            raise ValueError(f"Unknown agent type specified: '{agent_type}'.")

        agent_instance = agent_class(video_id=video_id, agent_run_id=run_id, target_id=target_id)

        # --- Execute Agent Logic ---
        logger.info(f"Executing run() method for {agent_type} (Run ID: {run_id})...")
        # Check video exists before updating status
        if db.get_video_by_id(video_id):
             db.update_video_status(video_id, processing_status=f"Running Agent: {agent_type}")

        result_preview = agent_instance.run() # Agent logic executed here
        duration = time.time() - start_time
        logger.info(f"Agent {agent_type} (Run ID: {run_id}) finished execution in {duration:.2f}s.")

        # --- Record Agent Run Success ---
        db.update_agent_run_status(run_id, status='Success', result_preview=str(result_preview) if result_preview else None)
        logger.info(f"--- Agent Task SUCCEEDED: Video={video_id}, Agent='{agent_type}' (Run ID: {run_id}, Task ID: {task_id}) ---")
        return {"run_id": run_id, "status": "Success", "result_preview": str(result_preview) if result_preview else None}

    # --- Error Handling ---
    except ValueError as e: # Config/data errors (non-retryable)
        error_msg = f"Configuration or data error in agent {agent_type}: {e}"
        logger.error(f"--- Agent Task NON-RETRYABLE FAIL: Video={video_id}, Agent='{agent_type}' (Run ID: {run_id}, Task ID: {task_id}) --- Error: {error_msg}", exc_info=False)
        if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=error_utils.format_error(e, include_traceback=False))
        if db.get_video_by_id(video_id):
            db.update_video_error(video_id, error_utils.format_error(e), f"Agent Error: {agent_type}")
        raise Ignore()

    except (AgentError, ToolError) as e: # Expected errors, only ToolError is retryable via autoretry_for
        is_retryable = isinstance(e, ToolError)
        retry_type = "Retryable" if is_retryable else "NON-RETRYABLE"
        log_level = logging.WARNING if is_retryable else logging.ERROR
        error_msg_formatted = error_utils.format_error(e, include_traceback=False) # Less verbose for expected errors

        logger.log(log_level, f"--- Agent Task FAILED ({retry_type}): Video={video_id}, Agent='{agent_type}' (Run ID: {run_id}, Task ID: {task_id}, Attempt: {self.request.retries + 1}) --- Error: {e}", exc_info=False) # Log concise error
        if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=error_msg_formatted)
        if db.get_video_by_id(video_id):
             error_prefix = f"[Attempt {self.request.retries + 1}] " if is_retryable else ""
             db.update_video_error(video_id, f"{error_prefix}{error_msg_formatted}", f"Agent Error: {agent_type}")

        if is_retryable:
            try:
                raise self.retry(exc=e) # Use Celery's autoretry mechanism
            except MaxRetriesExceededError:
                logger.error(f"Agent task {task_id} (Agent: {agent_type}, Video: {video_id}) failed after max retries.")
                return {"run_id": run_id, "status": "Failed after retries", "error": str(e)}
            except Ignore:
                 logger.error(f"Agent task {task_id} retry explicitly ignored for ToolError.")
                 raise
        else: # AgentError is not retryable
             raise Ignore()

    except Exception as e: # Catch truly unexpected errors
        # Log with full traceback for unexpected issues
        formatted_error = error_utils.format_error(e, include_traceback=True)
        logger.critical(f"--- Agent Task CRITICAL FAILURE: Video={video_id}, Agent='{agent_type}' (Run ID: {run_id}, Task ID: {task_id}) --- Error: {formatted_error}", exc_info=False) # Already formatted with traceback
        if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=formatted_error)
        if db.get_video_by_id(video_id):
            db.update_video_error(video_id, formatted_error, f"Critical Agent Error: {agent_type}")
        # Keep Ignore() for unexpected errors to prevent potential infinite loops,
        # but rely on critical logging and DB status for visibility.
        raise Ignore()

    finally:
        duration = time.time() - start_time
        logger.info(f"--- Agent Task finished processing: Video={video_id}, Agent='{agent_type}' (Task ID: {task_id}, Run ID: {run_id}, Duration: {duration:.2f}s) ---")


# ============================================
# === Batch Cutting Dispatcher Task ===
# ============================================
# MODIFIED: Now dispatches process_clip_task for each segment
@celery_app.task(bind=True, name='tasks.batch_cut_dispatcher_task') # Renamed for clarity
def batch_cut_dispatcher_task(self: Task, video_id: int, timestamps_seconds: list[float], clip_type: str = 'long'):
    """
    Receives timestamps and dispatches individual process_clip_task instances
    in parallel for each segment using Celery group.
    """
    task_id = self.request.id
    logger.info(f"--- Starting Batch Cut Dispatcher Task: Video={video_id}, Type='{clip_type}' (Task ID: {task_id}) ---")
    logger.info(f"Timestamps (seconds): {timestamps_seconds}")
    # Create an agent_run record for this dispatcher task
    run_id = db.add_agent_run(video_id, agent_type='batch_cut_dispatcher', status='Running')
    start_time = time.time()
    dispatched_tasks = 0
    final_status = "Failed" # Assume failure initially
    final_message = "Batch cut dispatch task encountered an error."

    try:
        # --- Perceive ---
        video_data = db.get_video_by_id(video_id)
        if not video_data:
            raise ValueError(f"Video record {video_id} not found.")

        source_video_path = video_data.get('file_path')
        if not source_video_path or not os.path.exists(source_video_path):
            raise ValueError(f"Source video file missing or path invalid for video {video_id}.")

        video_duration = media_utils.get_video_duration(source_video_path)
        if video_duration is None:
            # Attempt to get duration again with a small delay? Or fail. Let's fail for now.
            time.sleep(1) # Small delay in case file wasn't fully ready
            video_duration = media_utils.get_video_duration(source_video_path)
            if video_duration is None:
                raise ValueError(f"Could not determine duration for video {video_id}.")

        # --- Plan Segments ---
        # (Segment planning logic remains similar to old batch_cut_task)
        cut_points = sorted([ts for ts in timestamps_seconds if 0 <= ts < video_duration])
        unique_cut_points = []
        if cut_points:
            unique_cut_points.append(cut_points[0])
            for i in range(1, len(cut_points)):
                if cut_points[i] > cut_points[i-1] + 0.1: # Avoid tiny segments
                    unique_cut_points.append(cut_points[i])

        segments_to_cut = []
        last_cut = 0.0
        if unique_cut_points and unique_cut_points[0] > 0.01:
            segments_to_cut.append({'start': 0.0, 'end': unique_cut_points[0], 'index': 0})
            last_cut = unique_cut_points[0]
        for i, ts in enumerate(unique_cut_points):
            if ts > last_cut + 0.1:
                segments_to_cut.append({'start': last_cut, 'end': ts, 'index': len(segments_to_cut)})
            last_cut = ts
        if last_cut < video_duration - 0.1:
            segments_to_cut.append({'start': last_cut, 'end': video_duration, 'index': len(segments_to_cut)})

        if not segments_to_cut:
             logger.warning(f"No segments defined after processing timestamps for video {video_id}. No clip tasks dispatched.")
             final_status = "Success"
             final_message = "No valid segments to cut based on provided timestamps."
             if run_id: db.update_agent_run_status(run_id, status=final_status, result_preview=final_message)
             # Update main video status to indicate completion (no clips)
             db.update_video_status(video_id, processing_status="Batch Cut Complete (No Segments)")
             return {"status": final_status, "message": final_message, "dispatched_count": 0}

        logger.info(f"Defined {len(segments_to_cut)} segments to dispatch for video {video_id}.")

        # --- Act (Dispatch Tasks) ---
        db.update_video_status(video_id, status='Processing', processing_status=f"Batch Clipping Queued ({len(segments_to_cut)} clips)")

        clip_output_dir = config.PROCESSED_CLIPS_DIR
        os.makedirs(clip_output_dir, exist_ok=True)
        task_signatures = []

        for segment in segments_to_cut:
            start = segment['start']
            end = segment['end']
            index = segment['index']

            # Define output path for the clip task
            start_str = f"{start:.1f}".replace('.', 's')
            end_str = f"{end:.1f}".replace('.', 's')
            # Include clip_type in filename for clarity
            clip_filename = f"batch_{clip_type}_{video_id}_seg{index:03d}_{start_str}-{end_str}.mp4"
            output_clip_path = os.path.join(clip_output_dir, clip_filename)

            # Create signature for the process_clip_task
            task_sig = process_clip_task.s(video_id, start, end, output_clip_path, clip_type)
            task_signatures.append(task_sig)

        # Create a group to run tasks in parallel
        task_group = group(task_signatures)
        logger.info(f"Dispatching group of {len(task_signatures)} process_clip_task instances for video {video_id}.")

        # Execute the group
        group_result = task_group.apply_async()
        # Optional: Save group_id for later status checking if needed
        # db.update_video_result(video_id, 'batch_clip_group_id', group_result.id)

        dispatched_tasks = len(task_signatures)
        final_status = "Success" # Dispatcher succeeded if it reached here
        final_message = f"Successfully dispatched {dispatched_tasks} clip processing tasks."
        logger.info(final_message)
        if run_id: db.update_agent_run_status(run_id, status=final_status, result_preview=final_message)
        # Main video status remains 'Processing', individual clip tasks update their own status

        # Note: We don't wait for the group here. The dispatcher's job is done.
        # Monitoring overall completion would require callbacks (chord) or polling group results.

        return {"status": final_status, "message": final_message, "dispatched_count": dispatched_tasks}

    except ValueError as e: # Catch setup errors
         error_msg = f"Batch cut dispatcher task setup failed for video {video_id}: {e}"
         logger.error(error_msg)
         if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=error_msg)
         if db.get_video_by_id(video_id):
             db.update_video_error(video_id, error_utils.format_error(e), "Batch Cut Dispatch Error")
         raise Ignore()
    except Exception as e: # Catch unexpected errors during dispatch setup
        error_msg = f"Batch cut dispatcher task failed critically for video {video_id}: {e}"
        logger.critical(error_msg, exc_info=True)
        if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=error_utils.format_error(e, include_traceback=True))
        if db.get_video_by_id(video_id):
             db.update_video_error(video_id, error_utils.format_error(e), "Batch Cut Dispatch Error")
        raise Ignore()
    finally:
        duration = time.time() - start_time
        logger.info(f"--- Batch Cut Dispatcher Task finished: Video={video_id} (Task ID: {task_id}, Duration: {duration:.2f}s) ---")


# ============================================
# === New Task: Process Single Clip ===
# ============================================
@celery_app.task(bind=True, name='tasks.process_clip_task',
                 autoretry_for=(ToolError,), # Retry on ToolErrors (e.g., ffmpeg issues, transcription model load, Gemini API flakes)
                 retry_kwargs={'max_retries': 1, 'countdown': 60}) # Allow 1 retry with delay
def process_clip_task(self: Task, video_id: int, start_time: float, end_time: float, output_path: str, clip_type: str):
    """
    Processes a single clip: Cut, Edit (moviepy), Extract Audio, Transcribe, Generate Metadata (Gemini).
    Updates status in the 'clips' database table.
    """
    task_id = self.request.id
    logger.info(f"--- Starting Process Clip Task: Video={video_id}, Clip='{os.path.basename(output_path)}', Type='{clip_type}' (Task ID: {task_id}, Attempt: {self.request.retries + 1}) ---")
    start_process_time = time.time()

    clip_id = None
    clip_audio_path = None
    source_video_path = None
    step_error = None
    final_clip_status = 'Failed' # Default to Failed

    try:
        # --- Initial DB Setup ---
        # TODO: Implement db.add_clip function in database.py
        # clip_id = db.add_clip(video_id, output_path, start_time, end_time, status='Processing', clip_type=clip_type)
        clip_id = int(time.time() * 1000) # Placeholder ID
        logger.info(f"Placeholder: Created clip record with ID {clip_id} for {os.path.basename(output_path)}")

        if not clip_id:
            raise AgentError(f"Failed to create database record for clip: {output_path}") # Use AgentError for non-retryable DB logic failure

        # Get source video path needed for cutting
        video_data = db.get_video_by_id(video_id)
        if not video_data or not video_data.get('file_path'):
            raise AgentError(f"Source video path not found for video_id {video_id}")
        source_video_path = video_data['file_path']
        if not os.path.exists(source_video_path):
             raise AgentError(f"Source video file does not exist: {source_video_path}")


        # --- Step 1: Cut Clip (FFmpeg) ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 1/7 - Cutting clip ({start_time:.2f}s - {end_time:.2f}s)...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Cutting Clip')
        try:
            media_utils.create_clip(source_video_path, output_path, start_time, end_time, re_encode=True)
            logger.info(f"Clip {clip_id}: Step 1 - Cut successful ({time.time() - step_start_time:.2f}s).")
        except Exception as e:
            step_error = f"Cut failed: {e}"
            raise ToolError(step_error) from e # Raise ToolError for FFmpeg issues


        # --- Step 2: Edit Clip (Moviepy - Placeholder) ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 2/7 - Editing clip (Type: {clip_type})...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Editing Clip')
        if clip_type == 'short': # Example condition
            try:
                # TODO: Implement moviepy wrapper in media_utils or EditingTool
                # edited_path = media_utils.apply_short_format_edits(output_path) # Example call
                # if edited_path != output_path: # If editing creates a new file/overwrites
                #     output_path = edited_path
                #     db.update_clip_path(clip_id, edited_path) # Update DB if path changes
                logger.info(f"Clip {clip_id}: Step 2 - Placeholder Edit successful ({time.time() - step_start_time:.2f}s).")
                pass # Placeholder
            except Exception as e:
                step_error = f"Edit failed: {e}"
                # Decide if editing failure is critical - maybe just log warning? For now, fail task.
                raise ToolError(step_error) from e
        else:
            logger.info(f"Clip {clip_id}: Step 2 - Skipped (Type: {clip_type}).")


        # --- Step 3: Extract Audio (FFmpeg) ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 3/7 - Extracting audio...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Extracting Audio')
        # Define audio path (e.g., same dir as clip, specific name)
        clip_audio_path = output_path + ".wav"
        try:
            if os.path.exists(clip_audio_path): os.remove(clip_audio_path) # Clean up previous attempt
            media_utils.extract_audio(output_path, clip_audio_path)
            logger.info(f"Clip {clip_id}: Step 3 - Audio extraction successful ({time.time() - step_start_time:.2f}s).")
        except Exception as e:
            step_error = f"Audio extraction failed: {e}"
            raise ToolError(step_error) from e


        # --- Step 4: Transcribe Audio (FasterWhisper) ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 4/7 - Transcribing audio...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Transcribing')
        transcript_segments = None
        try:
            # Using AnalysisTool directly requires instantiation, or make static? Let's assume static for now.
            # Alternatively, call transcription.transcribe_audio directly
            success, segments_list_raw, error_msg = transcription.transcribe_audio(clip_audio_path)
            if not success:
                raise ToolError(f"Transcription failed: {error_msg}")
            transcript_segments = [{'start': seg.start, 'end': seg.end, 'text': seg.text} for seg in segments_list_raw]
            logger.info(f"Clip {clip_id}: Step 4 - Transcription successful ({len(transcript_segments)} segments) ({time.time() - step_start_time:.2f}s).")
        except Exception as e:
             step_error = f"Transcription failed: {e}"
             raise ToolError(step_error) from e


        # --- Step 5: Store Transcript ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 5/7 - Storing transcript...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Saving Transcript')
        try:
            # TODO: Implement db.add_clip_transcript(clip_id, transcript_segments)
            logger.info(f"Clip {clip_id}: Step 5 - Placeholder Store transcript successful ({time.time() - step_start_time:.2f}s).")
            pass # Placeholder
        except Exception as e:
            # Non-retryable failure if DB store fails critically
            step_error = f"Failed to store transcript in DB: {e}"
            raise AgentError(step_error) from e


        # --- Step 6: Generate Metadata (Gemini - Placeholder) ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 6/7 - Generating metadata...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Generating Metadata')
        clip_metadata = None
        try:
            # TODO: Instantiate GeminiTool
            # gemini_tool = GeminiTool()
            # TODO: Prepare input for Gemini (e.g., transcript text, or clip path for multimodal)
            # transcript_text = " ".join([seg['text'] for seg in transcript_segments]) if transcript_segments else ""
            # clip_metadata = gemini_tool.generate_metadata_for_clip(transcript=transcript_text) # Or pass clip_path
            clip_metadata = {"title": "Placeholder Title", "description": "Placeholder description.", "keywords": ["placeholder", "clip"]} # Placeholder
            logger.info(f"Clip {clip_id}: Step 6 - Placeholder Metadata generation successful ({time.time() - step_start_time:.2f}s).")
            pass # Placeholder
        except Exception as e:
             # Metadata generation failure might be non-critical? Log warning and continue.
             logger.warning(f"Clip {clip_id}: Step 6 - Metadata generation failed: {e}. Continuing process.", exc_info=True)
             # TODO: db.update_clip_status(clip_id, 'Metadata Failed') ?


        # --- Step 7: Store Metadata ---
        step_start_time = time.time()
        logger.info(f"Clip {clip_id}: Step 7/7 - Storing metadata...")
        # TODO: Update DB clip status: db.update_clip_status(clip_id, 'Saving Metadata')
        if clip_metadata:
             try:
                 # TODO: Implement db.add_clip_metadata(clip_id, clip_metadata)
                 logger.info(f"Clip {clip_id}: Step 7 - Placeholder Store metadata successful ({time.time() - step_start_time:.2f}s).")
                 pass # Placeholder
             except Exception as e:
                  # Failure to store metadata might be non-critical? Log warning.
                  logger.warning(f"Clip {clip_id}: Step 7 - Failed to store metadata in DB: {e}. Clip processing otherwise complete.", exc_info=True)
        else:
             logger.info(f"Clip {clip_id}: Step 7 - Skipped (No metadata generated).")


        # --- Mark Clip as Completed ---
        final_clip_status = 'Completed'
        # TODO: db.update_clip_status(clip_id, 'Completed')
        logger.info(f"Clip {clip_id}: Successfully processed.")

        return {"clip_id": clip_id, "status": final_clip_status, "output_path": output_path}

    except (AgentError, ToolError) as e: # Catch expected errors from steps
        error_msg = f"Clip processing failed for {os.path.basename(output_path)}: {e}"
        is_retryable = isinstance(e, ToolError)
        log_level = logging.WARNING if is_retryable else logging.ERROR
        logger.log(log_level, f"--- Process Clip Task FAILED ({'Retryable' if is_retryable else 'NON-RETRYABLE'}): Video={video_id}, Clip='{os.path.basename(output_path)}' (Task ID: {task_id}, Attempt: {self.request.retries + 1}) --- Error: {e}", exc_info=False)

        # Update clip status in DB to Failed
        if clip_id:
            # TODO: db.update_clip_status(clip_id, 'Failed', error_message=str(e))
            pass # Placeholder

        # Handle retries only for ToolError
        if is_retryable:
            try:
                raise self.retry(exc=e)
            except MaxRetriesExceededError:
                logger.error(f"Process clip task {task_id} (Clip: {os.path.basename(output_path)}) failed after max retries.")
                return {"clip_id": clip_id, "status": "Failed after retries", "error": str(e)}
            except Ignore:
                 logger.error(f"Process clip task {task_id} retry explicitly ignored for ToolError.")
                 raise
        else: # AgentError (e.g., DB setup failure) is not retryable
             raise Ignore()

    except Exception as e: # Catch unexpected errors
        formatted_error = error_utils.format_error(e, include_traceback=True)
        logger.critical(f"--- Process Clip Task CRITICAL FAILURE: Video={video_id}, Clip='{os.path.basename(output_path)}' (Task ID: {task_id}) --- Error: {formatted_error}", exc_info=False)
        if clip_id:
             # TODO: db.update_clip_status(clip_id, 'Failed', error_message=formatted_error)
             pass # Placeholder
        raise Ignore() # Don't retry critical errors

    finally:
        # --- Cleanup ---
        if clip_audio_path and os.path.exists(clip_audio_path):
            try:
                os.remove(clip_audio_path)
                logger.debug(f"Clip {clip_id}: Cleaned up temporary audio file: {clip_audio_path}")
            except OSError as rm_err:
                logger.warning(f"Clip {clip_id}: Failed to remove temporary audio file '{clip_audio_path}': {rm_err}")

        duration = time.time() - start_process_time
        logger.info(f"--- Process Clip Task finished: Video={video_id}, Clip='{os.path.basename(output_path)}', Status='{final_clip_status}' (Task ID: {task_id}, Duration: {duration:.2f}s) ---")


# ===========================================================
# === New Task: Create Single Clip (Manual Request) ===
# ===========================================================
@celery_app.task(bind=True, name='tasks.create_single_clip_task')
def create_single_clip_task(self: Task, video_id: int, start_time: float, end_time: float, clip_type: str = 'manual', context_text: str = ""):
    """
    Handles the creation and processing of a single clip requested manually via the UI.
    Generates filename, then calls process_clip_task logic.
    """
    task_id = self.request.id
    logger.info(f"--- Starting Create Single Clip Task: Video={video_id}, Time={start_time:.2f}-{end_time:.2f} (Task ID: {task_id}) ---")
    start_create_time = time.time()
    run_id = None # For optional agent run tracking

    try:
        # Optional: Add an agent run record for traceability
        run_id = db.add_agent_run(video_id, agent_type='manual_single_clip_creator', status='Running')

        # --- Generate Filename ---
        clip_output_dir = config.PROCESSED_CLIPS_DIR
        os.makedirs(clip_output_dir, exist_ok=True)
        safe_text_snippet = media_utils.sanitize_filename(context_text)[:30]
        start_str = f"{start_time:.1f}".replace('.', 's')
        end_str = f"{end_time:.1f}".replace('.', 's')
        timestamp_str = datetime.datetime.now().strftime("%H%M%S")
        clip_filename = f"manual_{video_id}_{start_str}-{end_str}_{safe_text_snippet}_{timestamp_str}.mp4"
        output_clip_path = os.path.join(clip_output_dir, clip_filename)

        # --- Delegate to process_clip_task ---
        # Use .s() to create a signature, then call it directly inline
        # This reuses the logic but runs it within *this* task context.
        # Alternatively, could dispatch process_clip_task.delay() but adds complexity.
        # Let's run inline for simplicity, as it's already a background task.
        logger.info(f"Single Clip Task: Delegating processing to 'process_clip_task' logic for path: {output_clip_path}")

        # NOTE: This directly calls the function body of process_clip_task, not as a separate Celery task.
        # This means retries defined on process_clip_task won't apply here unless re-implemented.
        # Consider if separate dispatch is better for robustness despite complexity.
        # For now, run inline and handle errors here.

        # Replicate the core logic call (or call a shared helper function if refactored)
        # This requires careful error handling mirroring process_clip_task
        # Simplified version for now - just call it. A refactor to a shared function is better.
        # result = _execute_clip_processing_steps(video_id, start_time, end_time, output_clip_path, clip_type) # Ideal refactor
        try:
            # Simulating the call - replace with actual call or shared function
             result = process_clip_task(video_id, start_time, end_time, output_clip_path, clip_type) # Direct call (beware of self/bind=True)
             # A cleaner way without direct call if not refactored:
             # result = process_clip_task.apply(args=[video_id, start_time, end_time, output_clip_path, clip_type]).get() # Runs synchronously

             # For now, assume direct call works conceptually, handle potential errors
             if isinstance(result, dict) and result.get("status") == 'Completed':
                 final_status = "Success"
                 final_message = f"Manual clip created: {os.path.basename(output_clip_path)}"
                 if run_id: db.update_agent_run_status(run_id, status='Success', result_preview=final_message)
             else:
                 error_detail = result.get("error", "Unknown error during clip processing") if isinstance(result, dict) else "Unknown error"
                 raise Exception(f"Clip processing failed: {error_detail}")

             logger.info(f"Single Clip Task: Processing completed successfully for {output_clip_path}")
             return {"status": final_status, "message": final_message, "clip_path": output_clip_path}

        except Exception as proc_err:
             # Handle errors from the inline processing call
             error_msg = f"Failed to process single clip {os.path.basename(output_clip_path)}: {proc_err}"
             logger.error(error_msg, exc_info=True)
             if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=error_utils.format_error(proc_err))
             # Don't update main video status for single clip failure
             raise Ignore(error_msg) from proc_err


    except Exception as e: # Catch errors during setup/dispatch
        error_msg = f"Create single clip task failed critically for video {video_id}: {e}"
        logger.critical(error_msg, exc_info=True)
        if run_id: db.update_agent_run_status(run_id, status='Failed', error_message=error_utils.format_error(e))
        raise Ignore()
    finally:
        duration = time.time() - start_create_time
        logger.info(f"--- Create Single Clip Task finished: Video={video_id} (Task ID: {task_id}, Duration: {duration:.2f}s) ---")


# --- END OF FILE tasks.py ---