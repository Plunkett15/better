# --- START OF FILE tests/utils/test_media_utils.py ---

import pytest
from utils import media_utils

# === Tests for sanitize_filename ===

@pytest.mark.parametrize("original, expected", [
    ("My Video Title", "My_Video_Title"),
    ("  Leading/Trailing Spaces ", "Leading_Trailing_Spaces"),
    ("File/With\\Invalid:Chars*?<>|%", "File_With_Invalid_Chars_"),
    ("Control\x01Chars\x1FHere", "Control_Chars_Here"),
    ("Dots.At.End.", "Dots.At.End"),
    ("Repeated___Spaces   And_Underscores", "Repeated_Spaces_And_Underscores"),
    ("Apostrophe's Test", "Apostrophe_s_Test"),
    ("CON", "CON_"), # Reserved name
    ("LPT1.txt", "LPT1_.txt"),
    ("", "sanitized_empty_filename_"), # Empty string (timestamp will vary)
    (None, "sanitized_empty_filename_"), # None input (timestamp will vary)
    ("A" * 250, "A" * 200), # Max length truncation
    ("你好世界", "你好世界"), # Unicode characters
    # Add more edge cases
])
def test_sanitize_filename(original, expected):
    sanitized = media_utils.sanitize_filename(original)
    # Handle timestamp variation for empty/None cases
    if expected == "sanitized_empty_filename_":
        assert sanitized.startswith(expected)
    else:
        assert sanitized == expected

def test_sanitize_filename_max_len():
    long_string = "a" * 300
    sanitized = media_utils.sanitize_filename(long_string, max_len=100)
    assert len(sanitized) <= 100
    assert sanitized == "a" * 100

# === Tests for time_str_to_seconds ===

@pytest.mark.parametrize("time_str, expected_seconds", [
    ("10.5", 10.5),
    ("0.123", 0.123),
    ("65.2", 65.2),
    ("01:05.3", 65.3),
    ("1:05.3", 65.3),
    ("00:01:05.3", 65.3),
    ("10:30", 630.0), # MM:SS
    ("01:10:30.555", 4230.555), # HH:MM:SS.ms
    (" 01:10:30.555 ", 4230.555), # Leading/trailing spaces
    ("0", 0.0),
])
def test_time_str_to_seconds_valid(time_str, expected_seconds):
    assert media_utils.time_str_to_seconds(time_str) == pytest.approx(expected_seconds)

@pytest.mark.parametrize("invalid_str", [
    "abc",
    "1:2:3:4",
    "1:60.0", # Invalid seconds
    "1:",
    ":30",
    None,
    123,
    "",
    " ",
])
def test_time_str_to_seconds_invalid(invalid_str):
    assert media_utils.time_str_to_seconds(invalid_str) is None

# === Tests for FFmpeg/Moviepy Wrappers (Example - Requires Mocking or Dependencies) ===

# To test functions calling subprocess or external libraries like moviepy,
# you'll typically need mocking (unittest.mock or pytest-mock).
# These are placeholder examples showing the structure.

# @pytest.mark.skipif(not media_utils.FFMPEG_AVAILABLE, reason="FFmpeg not available")
# def test_extract_audio_requires_ffmpeg():
#     # This test would run if ffmpeg is available
#     # Need a dummy video file and mock subprocess or check actual output
#     pass

# def test_apply_moviepy_crop_mocked(mocker):
#     """Example using pytest-mock."""
#     if not media_utils.MOVIEPY_AVAILABLE:
#         pytest.skip("Moviepy not installed")

#     mock_clip = mocker.MagicMock()
#     mock_write = mocker.patch.object(mock_clip, 'write_videofile')
#     mock_crop_fx = mocker.patch.object(mock_clip, 'fx')
#     mock_load = mocker.patch('utils.media_utils.mp.VideoFileClip', return_value=mock_clip)
#     mocker.patch('os.path.exists', return_value=True) # Mock input exists

#     crop_rect = {'x1': 0, 'y1': 0, 'width': 100, 'height': 100}
#     success, result = media_utils.apply_moviepy_crop("dummy_input.mp4", "dummy_output.mp4", crop_rect)

#     assert success is True
#     assert result == "dummy_output.mp4"
#     mock_load.assert_called_once_with("dummy_input.mp4")
#     mock_crop_fx.assert_called_once() # Check that the fx method was called
#     mock_write.assert_called_once_with("dummy_output.mp4", codec='libx264', audio_codec='aac', preset='medium', logger='bar')
#     mock_clip.close.assert_called() # Ensure cleanup is called


# --- END OF FILE tests/utils/test_media_utils.py ---