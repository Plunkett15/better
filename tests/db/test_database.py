# --- START OF FILE tests/db/test_database.py ---

import pytest
import os
import time
from database import (
    add_video_job, get_video_by_id, update_video_status, delete_video_records,
    add_clip, get_clips_for_video, add_clip_transcript, get_clip_transcript,
    add_clip_metadata, get_clip_metadata, get_clips_with_details,
    add_mpp, get_all_mpps, get_mpp_by_name, update_mpp,
    reset_video_analysis_results, get_agent_runs, add_agent_run,
    DATABASE_PATH # Import to verify test path is used
)

# Use the 'app' fixture to ensure the DB is initialized in the test context
# Use 'db_conn' fixture for direct execution if needed, though functions handle connections

def test_db_path_is_test_path(app):
    """Verify the tests are using the test database path."""
    assert "test_videos.db" in DATABASE_PATH
    assert app.config["DATABASE_PATH"] == DATABASE_PATH

def test_add_and_get_video(app):
    """Test adding and retrieving a video job."""
    url = f"http://youtube.com/watch?v=test{int(time.time())}"
    video_id = add_video_job(url, "Test Title", "720p", "auto")
    assert video_id is not None
    assert isinstance(video_id, int)

    retrieved_video = get_video_by_id(video_id)
    assert retrieved_video is not None
    assert retrieved_video['id'] == video_id
    assert retrieved_video['youtube_url'] == url
    assert retrieved_video['title'] == "Test Title"
    assert retrieved_video['resolution'] == "720p"
    assert retrieved_video['status'] == "Pending"
    assert retrieved_video['processing_status'] == "Added"
    assert retrieved_video['processing_mode'] == "auto"

def test_add_duplicate_video_url(app):
    """Test adding a duplicate URL returns existing ID."""
    url = f"http://youtube.com/watch?v=duplicate{int(time.time())}"
    video_id1 = add_video_job(url, "First Add", "480p", "auto")
    assert video_id1 is not None

    video_id2 = add_video_job(url, "Second Add Attempt", "1080p", "manual")
    # Should return the ID of the first added video
    assert video_id2 == video_id1

    # Verify original data wasn't overwritten by the second attempt
    retrieved_video = get_video_by_id(video_id1)
    assert retrieved_video['title'] == "First Add"
    assert retrieved_video['resolution'] == "480p"

def test_update_video_status(app):
    """Test updating video status fields."""
    url = f"http://youtube.com/watch?v=status{int(time.time())}"
    video_id = add_video_job(url, "Status Test", "480p", "auto")
    assert video_id is not None

    success = update_video_status(video_id, status="Processing", processing_status="Downloading")
    assert success is True

    video = get_video_by_id(video_id)
    assert video['status'] == "Processing"
    assert video['processing_status'] == "Downloading"

    # Test updating only one field
    success = update_video_status(video_id, status="Processed")
    assert success is True
    video = get_video_by_id(video_id)
    assert video['status'] == "Processed"
    assert video['processing_status'] == "Downloading" # Should remain unchanged

def test_delete_video(app):
    """Test deleting video records."""
    url1 = f"http://youtube.com/watch?v=del1_{int(time.time())}"
    url2 = f"http://youtube.com/watch?v=del2_{int(time.time())}"
    video_id1 = add_video_job(url1, "Delete Me 1", "480p", "auto")
    video_id2 = add_video_job(url2, "Delete Me 2", "480p", "auto")
    assert video_id1 is not None
    assert video_id2 is not None

    deleted_count = delete_video_records([video_id1, 99999]) # Test with non-existent ID
    assert deleted_count == 1

    assert get_video_by_id(video_id1) is None
    assert get_video_by_id(video_id2) is not None # Verify only specified ID was deleted

    deleted_count = delete_video_records([video_id2])
    assert deleted_count == 1
    assert get_video_by_id(video_id2) is None

# === Tests for New Clip/Transcript/Metadata Tables ===

def test_add_and_get_clip(app):
    """Test adding and retrieving clip records."""
    url = f"http://youtube.com/watch?v=clipvideo{int(time.time())}"
    video_id = add_video_job(url, "Clip Test Video", "480p", "auto")
    assert video_id is not None

    clip_path = f"/path/to/clips/clip_{video_id}_1.mp4"
    clip_id = add_clip(video_id, clip_path, 10.0, 20.0, status='Pending', clip_type='manual')
    assert clip_id is not None

    clips = get_clips_for_video(video_id)
    assert len(clips) == 1
    clip = clips[0]
    assert clip['id'] == clip_id
    assert clip['video_id'] == video_id
    assert clip['clip_path'] == clip_path
    assert clip['start_time'] == 10.0
    assert clip['end_time'] == 20.0
    assert clip['status'] == 'Pending'
    assert clip['clip_type'] == 'manual'

def test_add_and_get_clip_transcript(app):
    """Test adding transcript data for a clip."""
    url = f"http://youtube.com/watch?v=transcriptvideo{int(time.time())}"
    video_id = add_video_job(url, "Transcript Test Video", "480p", "auto")
    clip_path = f"/path/to/clips/clip_transcript_{video_id}_1.mp4"
    clip_id = add_clip(video_id, clip_path, 0.0, 5.0)
    assert clip_id is not None

    transcript_data = [{"start": 0.5, "end": 2.5, "text": "Hello clip world"}, {"start": 3.0, "end": 4.8, "text": "Testing one two."}]
    success = add_clip_transcript(clip_id, transcript_data, status='Completed')
    assert success is True

    retrieved_transcript = get_clip_transcript(clip_id)
    assert retrieved_transcript is not None
    assert retrieved_transcript['clip_id'] == clip_id
    assert retrieved_transcript['status'] == 'Completed'
    assert isinstance(retrieved_transcript['transcript_json'], str) # Should be stored as JSON string
    loaded_json = json.loads(retrieved_transcript['transcript_json'])
    assert loaded_json == transcript_data

def test_add_and_get_clip_metadata(app):
    """Test adding metadata for a clip."""
    url = f"http://youtube.com/watch?v=metadatavideo{int(time.time())}"
    video_id = add_video_job(url, "Metadata Test Video", "480p", "auto")
    clip_path = f"/path/to/clips/clip_metadata_{video_id}_1.mp4"
    clip_id = add_clip(video_id, clip_path, 5.0, 15.0)
    assert clip_id is not None

    metadata = {"title": "Clip Title", "description": "A test clip.", "keywords": ["test", "metadata"]}
    success = add_clip_metadata(clip_id, metadata, status='Completed')
    assert success is True

    retrieved_metadata = get_clip_metadata(clip_id)
    assert retrieved_metadata is not None
    assert retrieved_metadata['clip_id'] == clip_id
    assert retrieved_metadata['status'] == 'Completed'
    assert retrieved_metadata['title'] == "Clip Title"
    assert retrieved_metadata['description'] == "A test clip."
    assert isinstance(retrieved_metadata['keywords_json'], str)
    loaded_keywords = json.loads(retrieved_metadata['keywords_json'])
    assert loaded_keywords == ["test", "metadata"]

def test_get_clips_with_details(app):
    """Test retrieving clips joined with transcript and metadata."""
    url = f"http://youtube.com/watch?v=detailsvideo{int(time.time())}"
    video_id = add_video_job(url, "Details Test Video", "480p", "auto")
    clip_id1 = add_clip(video_id, f"/clips/details_{video_id}_1.mp4", 0.0, 10.0)
    clip_id2 = add_clip(video_id, f"/clips/details_{video_id}_2.mp4", 10.0, 20.0)
    assert clip_id1 is not None and clip_id2 is not None

    transcript1 = [{"start": 1.0, "end": 2.0, "text": "Transcript 1"}]
    metadata1 = {"title": "Title 1", "keywords": ["kw1"]}
    metadata2 = {"title": "Title 2", "description": "Desc 2"}

    add_clip_transcript(clip_id1, transcript1)
    add_clip_metadata(clip_id1, metadata1)
    add_clip_metadata(clip_id2, metadata2) # Add metadata for clip 2, no transcript

    details = get_clips_with_details(video_id)
    assert len(details) == 2

    # Clip 1 checks
    assert details[0]['clip_id'] == clip_id1
    assert details[0]['clip_path'] == f"/clips/details_{video_id}_1.mp4"
    assert details[0]['transcript'] == transcript1
    assert details[0]['title'] == "Title 1"
    assert details[0]['description'] is None
    assert details[0]['keywords'] == ["kw1"]

    # Clip 2 checks
    assert details[1]['clip_id'] == clip_id2
    assert details[1]['clip_path'] == f"/clips/details_{video_id}_2.mp4"
    assert details[1]['transcript'] is None # No transcript added
    assert details[1]['title'] == "Title 2"
    assert details[1]['description'] == "Desc 2"
    assert details[1]['keywords'] == [] # Default empty list if not present

def test_delete_video_cascade(app):
    """Test that deleting a video cascades to clips/transcripts/metadata."""
    url = f"http://youtube.com/watch?v=cascadevideo{int(time.time())}"
    video_id = add_video_job(url, "Cascade Test Video", "480p", "auto")
    clip_id = add_clip(video_id, f"/clips/cascade_{video_id}_1.mp4", 0.0, 10.0)
    assert clip_id is not None
    add_clip_transcript(clip_id, [{"text": "test"}])
    add_clip_metadata(clip_id, {"title": "test"})
    add_agent_run(video_id, "downloader") # Add an agent run too

    # Verify records exist
    assert len(get_clips_for_video(video_id)) == 1
    assert get_clip_transcript(clip_id) is not None
    assert get_clip_metadata(clip_id) is not None
    assert len(get_agent_runs(video_id)) == 1

    # Delete the parent video
    deleted_count = delete_video_records([video_id])
    assert deleted_count == 1

    # Verify related records are gone due to CASCADE
    assert len(get_clips_for_video(video_id)) == 0
    assert get_clip_transcript(clip_id) is None
    assert get_clip_metadata(clip_id) is None
    assert len(get_agent_runs(video_id)) == 0


# === Tests for MPP Table ===

def test_get_all_mpps(app):
    """Test retrieving the pre-populated MPP list."""
    mpps = get_all_mpps(active_only=False) # Get all including inactive
    assert len(mpps) >= 5 # Check at least the example ones are there

    active_mpps = get_all_mpps(active_only=True)
    assert len(active_mpps) < len(mpps) # Assuming Andrea Horwath is inactive
    assert all(m['active'] == 1 for m in active_mpps) # SQLite uses 1 for TRUE

def test_get_mpp_by_name(app):
    """Test fetching a specific MPP."""
    ford = get_mpp_by_name("Doug Ford")
    assert ford is not None
    assert ford['name'] == "Doug Ford"
    assert ford['party'] == "PC"

    non_existent = get_mpp_by_name("No Such Person")
    assert non_existent is None

def test_add_update_mpp(app):
    """Test adding and updating an MPP."""
    name = f"Test MPP {int(time.time())}"
    mpp_id = add_mpp(name, "Test Riding", "Test Party", True)
    assert mpp_id is not None

    mpp = get_mpp_by_name(name)
    assert mpp['id'] == mpp_id
    assert mpp['constituency'] == "Test Riding"
    assert mpp['active'] == 1

    # Test update
    success = update_mpp(mpp_id, party="Updated Party", active=False)
    assert success is True
    mpp_updated = get_mpp_by_name(name)
    assert mpp_updated['party'] == "Updated Party"
    assert mpp_updated['active'] == 0 # SQLite uses 0 for FALSE


# --- END OF FILE tests/db/test_database.py ---