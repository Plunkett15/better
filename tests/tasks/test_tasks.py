# --- START OF FILE tests/tasks/test_tasks.py ---

import pytest
from unittest.mock import patch, MagicMock, call # Import call for checking multiple calls
import os
import time

# Import tasks to test
from tasks import (
    process_video_orchestrator_task, run_agent_task,
    batch_cut_dispatcher_task, process_clip_task, create_single_clip_task
)
# Import things tasks might call, for mocking
from tools import ToolError
from agents import AgentError
import database as db # To mock db functions

# Use pytest-mock 'mocker' fixture for easier mocking

# === process_video_orchestrator_task Tests ===

@patch('tasks.run_agent_task.delay') # Mock the .delay() method
@patch('database.get_video_by_id')
@patch('database.update_video_status')
def test_orchestrator_dispatches_downloader(mock_update_status, mock_get_video, mock_run_agent_delay, mocker):
    """Test orchestrator dispatches downloader for a new video."""
    mock_get_video.return_value = {"id": 1, "file_path": "/dl/video_1/video.mp4"} # Simulate video exists
    mocker.patch('os.path.exists', return_value=False) # Simulate file doesn't exist

    result = process_video_orchestrator_task.run(video_id=1, skip_download=False)

    mock_get_video.assert_called_with(1)
    mock_run_agent_delay.assert_called_once_with(1, 'downloader')
    # Check status updates
    assert mock_update_status.call_count >= 2
    assert call(1, processing_status="Dispatched downloader agent") in mock_update_status.call_args_list
    assert result['dispatched_agent'] == 'downloader'

@patch('tasks.run_agent_task.delay')
@patch('database.get_video_by_id')
@patch('database.update_video_status')
def test_orchestrator_skip_download_file_exists(mock_update_status, mock_get_video, mock_run_agent_delay, mocker):
    """Test orchestrator skips dispatch if skip_download=True and file exists."""
    mock_get_video.return_value = {"id": 2, "file_path": "/dl/video_2/video.mp4"}
    mocker.patch('os.path.exists', return_value=True) # Simulate file *does* exist
    mocker.patch('os.path.getsize', return_value=1024)

    result = process_video_orchestrator_task.run(video_id=2, skip_download=True)

    mock_get_video.assert_called_with(2)
    mock_run_agent_delay.assert_not_called() # Crucial check
    assert result['dispatched_agent'] is None
    # Check status is set to Ready
    assert call(2, status='Processed', processing_status='Ready for Clipping (Download Skipped)') in mock_update_status.call_args_list

@patch('tasks.run_agent_task.delay')
@patch('database.get_video_by_id')
@patch('database.update_video_status')
def test_orchestrator_skip_download_file_missing(mock_update_status, mock_get_video, mock_run_agent_delay, mocker):
    """Test orchestrator falls back to downloader if skip_download=True but file missing."""
    mock_get_video.return_value = {"id": 3, "file_path": "/dl/video_3/video.mp4"}
    mocker.patch('os.path.exists', return_value=False) # Simulate file missing

    result = process_video_orchestrator_task.run(video_id=3, skip_download=True)

    mock_get_video.assert_called_with(3)
    mock_run_agent_delay.assert_called_once_with(3, 'downloader') # Should dispatch downloader
    assert result['dispatched_agent'] == 'downloader'

# === run_agent_task Tests ===
# Needs more complex mocking of agent instantiation and run methods

@patch('tasks.AGENT_REGISTRY')
@patch('database.add_agent_run')
@patch('database.update_agent_run_status')
@patch('database.get_video_by_id', return_value={"id": 1}) # Assume video exists
def test_run_agent_task_success(mock_get_video, mock_update_run, mock_add_run, mock_registry, mocker):
    """Test successful execution of an agent via run_agent_task."""
    mock_add_run.return_value = 101 # Mock run_id
    # Mock the agent class and its instance
    mock_agent_instance = mocker.MagicMock()
    mock_agent_instance.run.return_value = "Download OK"
    mock_agent_class = mocker.MagicMock(return_value=mock_agent_instance)
    mock_registry.get.return_value = mock_agent_class

    result = run_agent_task.run(video_id=1, agent_type='downloader')

    mock_add_run.assert_called_once_with(1, 'downloader', None, status='Pending')
    # Check status was updated to Running then Success
    assert call(101, status='Running') in mock_update_run.call_args_list
    assert call(101, status='Success', result_preview="Download OK") in mock_update_run.call_args_list
    mock_registry.get.assert_called_once_with('downloader')
    mock_agent_class.assert_called_once_with(video_id=1, agent_run_id=101, target_id=None)
    mock_agent_instance.run.assert_called_once()
    assert result['status'] == 'Success'
    assert result['run_id'] == 101

@patch('tasks.AGENT_REGISTRY')
@patch('database.add_agent_run')
@patch('database.update_agent_run_status')
@patch('database.update_video_error')
@patch('database.get_video_by_id', return_value={"id": 1})
def test_run_agent_task_agent_error(mock_get_video, mock_update_video_err, mock_update_run, mock_add_run, mock_registry, mocker):
    """Test non-retryable AgentError handling."""
    mock_add_run.return_value = 102
    mock_agent_instance = mocker.MagicMock()
    mock_agent_instance.run.side_effect = AgentError("Config missing")
    mock_agent_class = mocker.MagicMock(return_value=mock_agent_instance)
    mock_registry.get.return_value = mock_agent_class

    # AgentError should cause Ignore exception from Celery task
    with pytest.raises(Ignore):
        run_agent_task.run(video_id=1, agent_type='downloader')

    # Verify DB statuses were updated to Failed
    mock_update_run.assert_any_call(102, status='Failed', error_message='AgentError: Config missing')
    mock_update_video_err.assert_called_once() # Check that video error was also updated

# Add tests for ToolError (which should trigger retry logic - harder to test directly without Celery runner)
# Add tests for unexpected Exception (should raise Ignore)

# === batch_cut_dispatcher_task Tests ===

@patch('tasks.process_clip_task.s') # Mock the signature creation
@patch('tasks.group')
@patch('database.get_video_by_id')
@patch('utils.media_utils.get_video_duration')
@patch('database.add_agent_run')
@patch('database.update_agent_run_status')
def test_batch_dispatcher_success(mock_update_run, mock_add_run, mock_get_duration, mock_get_video, mock_group, mock_clip_sig, mocker):
    """Test batch dispatcher correctly calculates segments and dispatches group."""
    mock_add_run.return_value = 201
    mock_get_video.return_value = {"id": 5, "file_path": "/path/video_5.mp4"}
    mock_get_duration.return_value = 60.0 # 60 second video
    # Mock the group and its apply_async method
    mock_group_instance = mocker.MagicMock()
    mock_group_result = mocker.MagicMock()
    mock_group_instance.apply_async.return_value = mock_group_result
    mock_group.return_value = mock_group_instance

    timestamps = [10.0, 25.5, 50.0]
    clip_type = 'short'
    result = batch_cut_dispatcher_task.run(video_id=5, timestamps_seconds=timestamps, clip_type=clip_type)

    mock_get_duration.assert_called_once_with("/path/video_5.mp4")
    # Expected segments: 0-10, 10-25.5, 25.5-50, 50-60
    assert mock_clip_sig.call_count == 4
    # Check args of one signature call (e.g., the first one)
    expected_path_0 = os.path.join(process_clip_task.app.conf.PROCESSED_CLIPS_DIR, "batch_short_5_seg000_0s0-10s0.mp4")
    mock_clip_sig.assert_any_call(5, 0.0, 10.0, expected_path_0, clip_type)
    # Check group was created with the 4 signatures
    assert mock_group.call_args[0][0] == mock_clip_sig.call_args_list # Check the list of signatures
    mock_group_instance.apply_async.assert_called_once() # Check group was executed
    assert result['dispatched_count'] == 4
    assert result['status'] == 'Success'
    mock_update_run.assert_called_with(201, status='Success', result_preview='Successfully dispatched 4 clip processing tasks.')


# === process_clip_task Tests (Example - requires extensive mocking) ===

@patch('tasks.media_utils.create_clip')
@patch('tasks.media_utils.extract_audio')
@patch('tasks.transcription.transcribe_audio')
@patch('tasks.db.add_clip') # Mock the placeholder function
@patch('tasks.db.add_clip_transcript')
# @patch('tasks.GeminiTool') # Mock the tool class if used
# @patch('tasks.EditingTool') # Mock the tool class if used
# ... other mocks for DB calls, os.path.exists etc. ...
def test_process_clip_task_success_flow(mock_add_transcript, mock_add_clip, mock_transcribe, mock_extract_audio, mock_create_clip, mocker):
    """Test the successful execution flow of process_clip_task (simplified)."""
    # --- Mocks Setup ---
    mock_add_clip.return_value = 501 # Mock clip_id
    mock_create_clip.return_value = True # Assume ffmpeg cut succeeds
    mock_extract_audio.return_value = True # Assume ffmpeg extract succeeds
    # Mock transcription result
    mock_segment = MagicMock(start=1.0, end=2.0, text="Clip text")
    mock_transcribe.return_value = (True, [mock_segment], None)
    # Mock other dependencies
    mocker.patch('database.get_video_by_id', return_value={"file_path": "/path/source.mp4"})
    mocker.patch('os.path.exists', return_value=True)
    # Mock placeholder tools (assuming they are classes)
    mock_gemini_tool_instance = mocker.MagicMock()
    mock_gemini_tool_instance.generate_metadata_for_clip.return_value = {"title": "G Title"}
    mocker.patch('tasks.GeminiTool', return_value=mock_gemini_tool_instance) # Mock instantiation
    mock_editing_tool_instance = mocker.MagicMock()
    mock_editing_tool_instance.apply_crop.return_value = "output_path.mp4" # Assume editing succeeds
    mocker.patch('tasks.EditingTool', return_value=mock_editing_tool_instance)
    mock_add_meta = mocker.patch('tasks.db.add_clip_metadata')

    # --- Execute Task ---
    video_id = 1
    start = 5.0
    end = 15.0
    output = "output_path.mp4"
    clip_type = "short"
    result = process_clip_task.run(video_id, start, end, output, clip_type)

    # --- Assertions ---
    mock_add_clip.assert_called_once() # Check clip record created
    mock_create_clip.assert_called_once() # Check ffmpeg cut called
    # TODO: Add assertions for moviepy editing calls based on clip_type
    mock_extract_audio.assert_called_once() # Check ffmpeg extract called
    mock_transcribe.assert_called_once() # Check transcription called
    mock_add_transcript.assert_called_once() # Check transcript saved
    # TODO: Check gemini tool called
    # TODO: Check metadata saved
    assert result['status'] == 'Completed'
    assert result['clip_id'] == 501


# Add tests for error handling within process_clip_task (e.g., cut fails, transcribe fails)

# === create_single_clip_task Tests (Example) ===

@patch('tasks.process_clip_task.run') # Mock the function run directly if calling inline
@patch('database.add_agent_run')
@patch('utils.media_utils.sanitize_filename', return_value='safe_text') # Mock util
def test_create_single_clip_task_success(mock_sanitize, mock_add_run, mock_process_clip, mocker):
    """Test create_single_clip_task delegates and handles success."""
    mock_add_run.return_value = 301
    mock_process_clip.return_value = {"clip_id": 601, "status": "Completed", "output_path": "/path/to/manual_clip.mp4"}

    result = create_single_clip_task.run(video_id=2, start_time=1.0, end_time=11.0, context_text="Manual clip test")

    mock_add_run.assert_called_once_with(2, agent_type='manual_single_clip_creator', status='Running')
    # Check that process_clip_task logic was invoked (via the mock)
    mock_process_clip.assert_called_once()
    # Verify args passed to process_clip_task
    args, kwargs = mock_process_clip.call_args
    assert args[0] == 2 # video_id
    assert args[1] == 1.0 # start_time
    assert args[2] == 11.0 # end_time
    assert args[4] == 'manual' # clip_type
    assert "manual_2_1s0-11s0_safe_text_" in args[3] # output_path contains expected parts
    assert result['status'] == 'Success'
    assert result['clip_path'] == "/path/to/manual_clip.mp4"

# Add tests for error handling in create_single_clip_task

# --- END OF FILE tests/tasks/test_tasks.py ---