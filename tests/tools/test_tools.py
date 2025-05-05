# --- START OF FILE tests/tools/test_tools.py ---

import pytest
from unittest.mock import patch, MagicMock # Or use mocker fixture from pytest-mock

# Import the tools to be tested
from tools import (
    DownloadTool, MediaProcessingTool, AnalysisTool, DatabaseTool,
    GeminiTool, EditingTool, ToolError
)
# Import underlying modules that tools call, for mocking verification
from utils import download as download_util
from utils import media_utils
from analysis import transcription
import database as db

# === DatabaseTool Tests ===
# Focus: Verify DatabaseTool methods correctly call underlying db functions
# and handle exceptions by raising ToolError.

@patch('database.get_video_by_id') # Mock the function in the database module
def test_db_tool_get_video_data_success(mock_db_get):
    """Test DatabaseTool.get_video_data calls db.get_video_by_id."""
    mock_db_get.return_value = {"id": 1, "title": "Test"}
    video_data = DatabaseTool.get_video_data(1)
    mock_db_get.assert_called_once_with(1)
    assert video_data == {"id": 1, "title": "Test"}

@patch('database.get_video_by_id', side_effect=db.sqlite3.Error("DB connection failed"))
def test_db_tool_get_video_data_failure(mock_db_get):
    """Test DatabaseTool.get_video_data raises ToolError on DB error."""
    with pytest.raises(ToolError, match="Database error fetching video 1"):
        DatabaseTool.get_video_data(1)
    mock_db_get.assert_called_once_with(1)

@patch('database.update_video_result')
def test_db_tool_update_video_result_success(mock_db_update):
    """Test DatabaseTool.update_video_result calls db.update_video_result."""
    mock_db_update.return_value = True
    success = DatabaseTool.update_video_result(1, 'manual_timestamps', '0:10\n0:20')
    assert success is True
    mock_db_update.assert_called_once_with(1, 'manual_timestamps', '0:10\n0:20')

@patch('database.update_video_result', side_effect=ValueError("Invalid column"))
def test_db_tool_update_video_result_value_error(mock_db_update):
    """Test DatabaseTool.update_video_result re-raises ValueError."""
    with pytest.raises(ValueError, match="Invalid column"):
        DatabaseTool.update_video_result(1, 'invalid_column', 'some data')
    mock_db_update.assert_called_once_with(1, 'invalid_column', 'some data')

# Add similar tests for other DatabaseTool methods (update_status, add_clip, etc.)
# mocking the corresponding 'database.*' functions.

# === DownloadTool Tests ===

@patch('utils.download.download_video')
def test_download_tool_success(mock_download):
    """Test DownloadTool success case."""
    expected_path = "/path/to/video.mp4"
    mock_download.return_value = (True, None, expected_path) # success, error_msg, final_path
    # Mock os.path.exists and os.path.getsize for validation within the tool
    with patch('os.path.exists', return_value=True), \
         patch('os.path.getsize', return_value=1024):
        result_path = DownloadTool.download_video("some_url", "/path/to", "video", "720p")
    assert result_path == expected_path
    mock_download.assert_called_once_with("some_url", "/path/to", "video", "720p")

@patch('utils.download.download_video')
def test_download_tool_failure(mock_download):
    """Test DownloadTool raises ToolError on download failure."""
    mock_download.return_value = (False, "Network Error", None)
    with pytest.raises(ToolError, match="Download failed: Network Error"):
        DownloadTool.download_video("some_url", "/path/to", "video", "720p")
    mock_download.assert_called_once_with("some_url", "/path/to", "video", "720p")

@patch('utils.download.download_video', side_effect=Exception("Unexpected error"))
def test_download_tool_exception(mock_download):
    """Test DownloadTool wraps unexpected exceptions in ToolError."""
    with pytest.raises(ToolError, match="Unexpected download error: Unexpected error"):
        DownloadTool.download_video("some_url", "/path/to", "video", "720p")
    mock_download.assert_called_once_with("some_url", "/path/to", "video", "720p")


# === MediaProcessingTool Tests ===

@patch('utils.media_utils.extract_audio')
@patch('utils.media_utils.FFMPEG_AVAILABLE', True) # Assume ffmpeg is available
def test_media_tool_extract_audio_success(mock_extract):
    """Test MediaProcessingTool audio extraction success."""
    expected_path = "/path/to/audio.wav"
    mock_extract.return_value = (True, None) # success, error_msg
    with patch('os.path.exists', return_value=True), \
         patch('os.path.getsize', return_value=1024):
        result_path = MediaProcessingTool.extract_audio("/path/video.mp4", expected_path)
    assert result_path == expected_path
    mock_extract.assert_called_once_with("/path/video.mp4", expected_path, 16000, 1)

@patch('utils.media_utils.extract_audio', return_value=(False, "FFmpeg error during extract"))
@patch('utils.media_utils.FFMPEG_AVAILABLE', True)
def test_media_tool_extract_audio_failure(mock_extract):
    """Test MediaProcessingTool audio extraction failure raises ToolError."""
    with pytest.raises(ToolError, match="Audio extraction failed: FFmpeg error during extract"):
        MediaProcessingTool.extract_audio("/path/video.mp4", "/path/audio.wav")
    mock_extract.assert_called_once()

# Add similar tests for MediaProcessingTool.create_clip

# === AnalysisTool Tests ===

@patch('analysis.transcription.transcribe_audio')
def test_analysis_tool_transcribe_success(mock_transcribe):
    """Test AnalysisTool transcription success."""
    # Mock the Segment object structure returned by faster-whisper
    mock_segment = MagicMock()
    mock_segment.start = 0.5
    mock_segment.end = 2.5
    mock_segment.text = "Hello world"
    mock_transcribe.return_value = (True, [mock_segment], None) # success, segments_list, error_msg

    result = AnalysisTool.transcribe_audio("/path/audio.wav")
    expected = [{"start": 0.5, "end": 2.5, "text": "Hello world"}]
    assert result == expected
    mock_transcribe.assert_called_once_with("/path/audio.wav", None, True, 5)

@patch('analysis.transcription.transcribe_audio', return_value=(False, None, "Model load failed"))
def test_analysis_tool_transcribe_failure(mock_transcribe):
    """Test AnalysisTool transcription failure raises ToolError."""
    with pytest.raises(ToolError, match="Transcription failed: Model load failed"):
        AnalysisTool.transcribe_audio("/path/audio.wav")
    mock_transcribe.assert_called_once()


# === GeminiTool Tests (Placeholder - Requires Mocking API) ===

# @patch('tools.genai.GenerativeModel') # Mock the Gemini model class
# def test_gemini_tool_metadata_success(MockGenerativeModel, app): # Use app fixture for config
#     if not tools.genai: pytest.skip("Gemini SDK not installed")

#     # Configure mock response
#     mock_model_instance = MockGenerativeModel.return_value
#     mock_response = MagicMock()
#     mock_response.text = '```json\n{"title": "Mock Title", "description": "Mock Desc", "keywords": ["mock", "test"]}\n```'
#     mock_model_instance.generate_content.return_value = mock_response

#     # Set a dummy API key in config for the test
#     app.config['GEMINI_API_KEY'] = 'fake-key'

#     gemini_tool = GeminiTool() # Tool init reads from config
#     assert gemini_tool.model is not None # Check model loaded

#     metadata = gemini_tool.generate_metadata_for_clip(transcript="Test transcript text")
#     expected = {"title": "Mock Title", "description": "Mock Desc", "keywords": ["mock", "test"]}
#     assert metadata == expected
#     mock_model_instance.generate_content.assert_called_once()


# === EditingTool Tests (Placeholder - Requires Mocking Moviepy) ===

# @patch('tools.mp.VideoFileClip') # Mock moviepy's VideoFileClip
# def test_editing_tool_crop_success(MockVideoFileClip, mocker):
#     if not tools.MOVIEPY_AVAILABLE: pytest.skip("Moviepy not installed")

#     # Setup mocks
#     mock_clip_instance = mocker.MagicMock()
#     mock_fx = mocker.MagicMock()
#     mock_clip_instance.fx.return_value = mock_fx # Mock the result of clip.fx()
#     MockVideoFileClip.return_value = mock_clip_instance
#     mocker.patch('os.path.exists', return_value=True) # Mock input file exists

#     editing_tool = EditingTool()
#     crop_rect = {'x1': 0, 'y1': 0, 'width': 100, 'height': 100}
#     success, result = editing_tool.apply_crop("in.mp4", "out.mp4", crop_rect)

#     assert success is True
#     assert result == "out.mp4"
#     MockVideoFileClip.assert_called_once_with("in.mp4")
#     mock_clip_instance.fx.assert_called_once() # Check fx was called
#     # Check write_videofile was called on the result of fx
#     mock_fx.write_videofile.assert_called_once_with("out.mp4", codec='libx264', audio_codec='aac', preset='medium', logger='bar')
#     mock_clip_instance.close.assert_called_once()
#     mock_fx.close.assert_called_once()


# --- END OF FILE tests/tools/test_tools.py ---