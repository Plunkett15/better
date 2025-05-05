# --- START OF FILE tests/routes/test_app.py ---

import pytest
from unittest.mock import patch
import json
import time

# Use the 'client' fixture from conftest.py

def test_index_get(client):
    """Test GET request to the index page."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Video Processor" in response.data # Check for title or key text
    assert b"Submit New Videos" in response.data

@patch('app.process_video_orchestrator_task.delay') # Mock the Celery task's delay method
@patch('utils.download.get_video_info') # Mock the util function
@patch('database.add_video_job') # Mock DB function
@patch('database.update_video_path')
@patch('os.makedirs')
def test_index_post_add_video(mock_makedirs, mock_update_path, mock_add_job, mock_get_info, mock_orchestrator_delay, client):
    """Test POST request to add a new video."""
    mock_get_info.return_value = ("Test Video Title", None) # title, error
    mock_add_job.return_value = 10 # Simulate new video_id
    mock_update_path.return_value = True
    mock_orchestrator_delay.return_value = MagicMock(id="test-task-id") # Mock task result object

    url = f"https://www.youtube.com/watch?v=test_{int(time.time())}"
    response = client.post('/', data={
        'urls': url,
        'resolution': '720p'
        # processing_mode removed
    }, follow_redirects=True) # Follow redirect back to index

    assert response.status_code == 200
    mock_get_info.assert_called_once_with(url)
    mock_add_job.assert_called_once_with(url, "Test Video Title", '720p', 'auto')
    mock_update_path.assert_called_once() # Check path update was called
    mock_orchestrator_delay.assert_called_once_with(10) # Check orchestrator called with video_id
    assert b"video(s) successfully added" in response.data # Check flash message

def test_video_details_get_not_found(client):
    """Test GET request for a non-existent video ID."""
    response = client.get('/video/99999')
    assert response.status_code == 404

@patch('database.get_video_by_id')
@patch('database.get_clips_with_details') # Mock the new function
@patch('database.get_agent_runs')
def test_video_details_get_success(mock_get_runs, mock_get_clips, mock_get_video, client):
    """Test GET request for the video details page."""
    video_id = 1
    mock_get_video.return_value = { # Simulate DB video data (new schema)
        "id": video_id, "youtube_url": "http://...", "title": "Details Test",
        "resolution": "480p", "status": "Processed", "processing_status": "Ready for Clipping",
        "file_path": "/dl/video.mp4", "error_message": None, "processing_mode": "auto",
        "manual_timestamps": None, "created_at": "2023-01-01T10:00:00", "updated_at": "2023-01-01T11:00:00"
    }
    mock_get_clips.return_value = [ # Simulate detailed clip data
        {"clip_id": 10, "clip_path": "/clips/clip1.mp4", "start_time": 0.0, "end_time": 10.0, "clip_status": "Completed", "transcript": [{"text": "t1"}], "title": "Clip 1 Title"}
    ]
    mock_get_runs.return_value = [{"id": 1, "agent_type": "downloader", "status": "Success"}]

    response = client.get(f'/video/{video_id}')
    assert response.status_code == 200
    assert b"Details Test" in response.data
    assert b"Generated Clips" in response.data
    assert b"clip1.mp4" in response.data # Check clip path is rendered
    assert b"Clip 1 Title" in response.data # Check metadata is rendered
    assert b"Transcript" in response.data # Check clip transcript section rendered
    assert b"Agent Run History" in response.data
    assert b"downloader" in response.data # Check agent run is rendered
    # Ensure old elements are NOT present
    assert b"Raw Transcript" not in response.data # Check old full transcript section removed

@patch('app.create_single_clip_task.delay') # Mock the NEW task
def test_trigger_clip_creation_post(mock_clip_task, client):
    """Test POST request to trigger single clip creation task."""
    video_id = 1
    mock_clip_task.return_value = MagicMock(id="clip-task-id")

    response = client.post(f'/clip/{video_id}', data={
        'start_time': '5.5',
        'end_time': '12.0',
        'text': 'some context',
    })

    assert response.status_code == 202 # Check for Accepted status
    assert response.mimetype == 'application/json'
    data = json.loads(response.data)
    assert data['success'] is True
    assert "Single clip generation task queued" in data['message']
    assert data['task_id'] == "clip-task-id"
    # Check task was called with correct args
    mock_clip_task.assert_called_once_with(video_id, 5.5, 12.0) # Ignoring kwargs for simplicity here

@patch('app.batch_cut_dispatcher_task.delay') # Mock the NEW dispatcher task
def test_trigger_batch_cut_post(mock_batch_task, client):
    """Test POST request to trigger batch clip creation."""
    video_id = 2
    mock_batch_task.return_value = MagicMock(id="batch-task-id")
    timestamps = ["1:00", "2:30.5"]
    payload = {"timestamps": timestamps, "clip_type": "short"}

    response = client.post(f'/video/{video_id}/batch_cut', json=payload) # Send JSON data

    assert response.status_code == 202
    assert response.mimetype == 'application/json'
    data = json.loads(response.data)
    assert data['success'] is True
    assert "Batch clip generation task queued" in data['message']
    assert data['task_id'] == "batch-task-id"
    # Check task called with correct args (timestamps parsed to seconds, clip_type)
    # Note: Actual parsing happens in the route before calling task
    expected_seconds = [60.0, 150.5]
    mock_batch_task.assert_called_once_with(video_id, expected_seconds, "short")

# Add tests for /delete-videos, /errors, /status_updates, /reprocess_full

# --- END OF FILE tests/routes/test_app.py ---