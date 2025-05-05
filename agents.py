# --- Start of File: agents.py ---
import logging
import abc
import os
import time
from config import Config
from tools import (DatabaseTool, DownloadTool, MediaProcessingTool, # MediaProcessingTool might be unused by agents now
                   AnalysisTool, ToolError) # AnalysisTool might be unused by agents now
from celery_app import celery_app

logger = logging.getLogger(__name__)
config = Config()

# ================================================
# === Agent Framework ===
# ================================================

class AgentError(Exception):
    """Custom exception for agent-specific errors during run()."""
    pass

class BaseAgent(abc.ABC):
    """Abstract Base Class for all processing agents."""
    agent_type = "base_agent" # Must be overridden by subclasses

    def __init__(self, video_id: int, agent_run_id: int, target_id: str | None = None):
        self.video_id = video_id
        self.agent_run_id = agent_run_id # The ID from the agent_runs table
        self.target_id = target_id # Optional specific target (e.g., exchange_id)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.db_tool = DatabaseTool() # Instantiate DB tool for easy access
        self.video_data = self._load_video_data() # Load initial video data

    def _load_video_data(self):
        """Loads the main video record data using the DatabaseTool."""
        video_data = self.db_tool.get_video_data(self.video_id)
        if not video_data:
            self.logger.warning(f"Agent initialization: Video record {self.video_id} not found (possibly deleted).")
            raise AgentError(f"Agent initialization failed: Video record {self.video_id} not found.")
        return video_data

    def _update_status(self, processing_status: str):
        """Helper to update the video's processing status."""
        self.video_data = self.db_tool.get_video_data(self.video_id)
        if not self.video_data:
             self.logger.warning(f"Cannot update status to '{processing_status}': Video {self.video_id} not found.")
             return
        self.db_tool.update_video_status(self.video_id, processing_status=processing_status)
        self.logger.info(f"Updated processing status to: '{processing_status}'")

    def _load_required_data(self, column_name: str, context: str = "") -> any:
        """Helper to load and parse required JSON data using DatabaseTool."""
        # Refresh video data to get latest state
        self.video_data = self.db_tool.get_video_data(self.video_id)
        if not self.video_data:
            raise AgentError(f"Cannot load required data '{column_name}': Video record {self.video_id} disappeared.")

        json_string = self.video_data.get(column_name)
        # Default to None if column doesn't exist or parsing fails
        parsed_data = self.db_tool.safe_load_json(json_string, default_value=None, context=f"{column_name} {context}")

        # Example check: If a specific column MUST exist and be valid JSON for this agent
        # if parsed_data is None and column_name == 'some_critical_column':
        #     raise AgentError(f"Required data column '{column_name}' is missing or NULL for Video ID {self.video_id}.")
        # if isinstance(parsed_data, dict) and 'error' in parsed_data:
        #      raise AgentError(f"Failed to parse required JSON data from column '{column_name}' for Video ID {self.video_id}: {parsed_data['error']}")

        return parsed_data

    def _dispatch_next_agent(self, agent_type: str, target_id: str | None = None, delay_sec: int = 0):
        """Dispatches the next agent task via Celery."""
        # Import locally to avoid circular dependency at module level
        from tasks import run_agent_task

        if not self.db_tool.get_video_data(self.video_id):
            self.logger.warning(f"Skipping dispatch of agent '{agent_type}': Video ID {self.video_id} no longer exists.")
            return

        self.logger.info(f"Dispatching next agent '{agent_type}'"
                         f"{f' for target {target_id}' if target_id else ''}"
                         f"{f' with delay {delay_sec}s' if delay_sec > 0 else ''}...")
        try:
            # Ensure run_agent_task still exists and is imported if used
            if delay_sec > 0:
                run_agent_task.apply_async(args=[self.video_id, agent_type, target_id], countdown=delay_sec)
            else:
                run_agent_task.delay(self.video_id, agent_type, target_id)
            self.logger.info(f"Agent '{agent_type}' successfully dispatched.")
        except Exception as e:
            self.logger.error(f"Failed to dispatch agent task '{agent_type}': {e}", exc_info=True)
            # Depending on workflow, failure to dispatch might be critical
            # raise AgentError(f"Failed to dispatch next agent '{agent_type}': {e}")

    @abc.abstractmethod
    def run(self) -> str | dict | None:
        """
        Main execution logic for the agent.
        Must be implemented by subclasses.
        Should perform Perceive-Plan-Act cycle.
        Returns a preview string/dict or None for the agent_runs table.
        Should raise AgentError for recoverable/expected errors, or let other exceptions propagate.
        """
        pass

# ================================================
# === Concrete Agent Implementations ===
# ================================================

class DownloaderAgent(BaseAgent):
    agent_type = "downloader"

    def run(self):
        self._update_status("Downloading")
        # --- Perceive ---
        video_path = self.video_data.get('file_path')
        youtube_url = self.video_data.get('youtube_url')
        resolution = self.video_data.get('resolution')

        if not video_path: raise AgentError("Initial file_path is missing in DB record.")
        if not youtube_url: raise AgentError("YouTube URL is missing in DB record.")
        # Use default resolution if not found in DB
        if not resolution:
            resolution = config.DEFAULT_RESOLUTION if hasattr(config, 'DEFAULT_RESOLUTION') else '480p'
            self.logger.warning(f"Resolution missing in DB, using default: {resolution}")


        output_dir = os.path.dirname(video_path)
        filename_base = os.path.splitext(os.path.basename(video_path))[0]

        needs_download = False
        if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
            self.logger.info(f"Video file missing or empty at '{video_path}'. Needs download.")
            needs_download = True
        else:
            self.logger.info(f"Video file already exists at: {video_path}. Verifying...")
            # Optional: Add verification step here if needed (e.g., check duration against expected)
            needs_download = False # Assume existing file is okay for now

        # --- Plan & Act ---
        actual_path = video_path # Assume existing path initially
        if needs_download:
            try:
                download_tool = DownloadTool()
                actual_path = download_tool.download_video(youtube_url, output_dir, filename_base, resolution)

                # Update path in DB if it changed (e.g., different extension like .mkv)
                if actual_path != video_path:
                    self.logger.info(f"Download path differs. Updating DB path from '{video_path}' to '{actual_path}'.")
                    if not self.db_tool.update_video_path(self.video_id, actual_path):
                         # Raise AgentError for critical DB update failure (non-retryable)
                         raise AgentError(f"Failed to update DB with actual download path: {actual_path}")
                    self.video_data['file_path'] = actual_path # Update internal state
                else:
                     self.logger.info(f"Download path matches existing DB path: {actual_path}")

            except ToolError as e:
                # ToolError from download_tool is potentially retryable (network, etc.)
                raise ToolError(f"DownloadTool failed: {e}") from e
            except AgentError as e: # Catch specific AgentError from DB update
                 raise e # Re-raise AgentError
            except Exception as e:
                 # Treat other unexpected errors during download as potentially retryable ToolErrors
                 raise ToolError(f"Unexpected error during download process: {e}") from e
        else:
            self.logger.info(f"Download skipped/verified for existing file: {actual_path}")


        # --- Dispatch Next (Removed) ---
        # No agent follows the downloader in the simplified main pipeline.
        # The orchestrator or agent itself should mark the video status appropriately.
        self.logger.info("DownloaderAgent finished. No next agent in main pipeline.")

        # Update overall status to indicate processing (downloading) is complete
        # and it's ready for manual actions (clipping).
        self.db_tool.update_video_status(self.video_id, status='Processed', processing_status='Ready for Clipping')

        return f"Download complete/verified. Path: {actual_path}"


# --- REMOVED AGENT CLASS ---
# class AudioExtractorAgent(BaseAgent): ... (Deleted)


# --- REMOVED AGENT CLASS ---
# class TranscriberAgent(BaseAgent): ... (Deleted)


# --- REMOVED OTHER AGENT CLASSES from previous version ---
# DiarizerAgent
# TranscriptPolisherAgent
# QnAPairerAgent
# ExchangeSummarizerAgent
# ClipMetaGeneratorAgent
# ShortClipGeneratorAgent


# --- Agent Registry ---
# Updated registry containing only the remaining agent(s)
AGENT_REGISTRY = {
    DownloaderAgent.agent_type: DownloaderAgent,
    # Removed: AudioExtractorAgent.agent_type, TranscriberAgent.agent_type, etc.
}

# --- END OF FILE agents.py ---