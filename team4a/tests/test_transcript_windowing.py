from app.pipeline.transcript_windowing import TranscriptWindow, group_segments_into_windows


class TestBasicGrouping:
    """Category A: multiple short segments combined into coherent windows."""

    def test_multiple_short_segments_are_combined_into_one_window(self):
        segments = [
            ("Operating system acts", 0.27, 0.32),
            ("as an interface", 0.32, 0.38),
            ("between user and hardware.", 0.38, 0.45),
        ]

        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=5)

        assert len(windows) == 1
        assert windows[0].text == "Operating system acts as an interface between user and hardware."

    def test_a_large_transcript_produces_multiple_reasonably_sized_windows(self):
        segments = [(f"word{i}", float(i), float(i + 1)) for i in range(300)]

        windows = group_segments_into_windows(segments, target_window_words=50, min_window_words=5)

        assert len(windows) > 1
        for window in windows[:-1]:
            assert len(window.text.split()) <= 50


class TestTimestampMapping:
    """Category B: correct start/end timestamps, multiple windows, no fabrication."""

    def test_window_start_is_the_first_segments_start(self):
        segments = [("a", 10.0, 11.0), ("b", 11.0, 12.0), ("c", 12.0, 13.0)]
        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)
        assert windows[0].start == 10.0

    def test_window_end_is_the_last_segments_end(self):
        segments = [("a", 10.0, 11.0), ("b", 11.0, 12.0), ("c", 12.0, 13.5)]
        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)
        assert windows[0].end == 13.5

    def test_multiple_windows_each_get_their_own_correct_range(self):
        # target_window_words=2 forces a new window every 2 words.
        segments = [("one two", 0.0, 1.0), ("three four", 1.0, 2.0), ("five six", 2.0, 3.0)]
        windows = group_segments_into_windows(segments, target_window_words=2, min_window_words=1)

        assert len(windows) == 3
        assert (windows[0].start, windows[0].end) == (0.0, 1.0)
        assert (windows[1].start, windows[1].end) == (1.0, 2.0)
        assert (windows[2].start, windows[2].end) == (2.0, 3.0)

    def test_no_timestamp_is_ever_outside_the_original_segment_range(self):
        segments = [("a", 5.0, 6.0), ("b", 6.0, 7.0), ("c", 7.0, 8.0)]
        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)
        for window in windows:
            assert window.start >= 5.0
            assert window.end <= 8.0


class TestFragmentNoiseHandling:
    """Category C: a standalone filler segment must not become its own
    independent chunk merely because it was one raw timing entry."""

    def test_standalone_filler_word_is_absorbed_into_the_surrounding_window(self):
        segments = [
            ("Operating system acts as an interface", 0.0, 2.0),
            ("okay", 2.0, 2.3),
            ("between the user and the hardware devices", 2.3, 4.5),
        ]

        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)

        assert len(windows) == 1
        assert "okay" in windows[0].text
        # Critically: "okay" is one word AMONG the real content, not the
        # entire window's text on its own.
        assert windows[0].text != "okay"

    def test_trailing_short_fragment_merges_into_previous_window_not_left_standalone(self):
        segments = [(f"word{i}", float(i), float(i + 1)) for i in range(50)] + [("okay", 50.0, 50.3)]

        windows = group_segments_into_windows(segments, target_window_words=50, min_window_words=5)

        # The trailing "okay" must not be its own window.
        assert all(window.text != "okay" for window in windows)
        assert windows[-1].text.endswith("okay")

    def test_filler_words_are_never_deleted_when_they_occur_naturally(self):
        segments = [("Yes okay so the operating system works this way", 0.0, 3.0)]
        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)
        assert windows[0].text == "Yes okay so the operating system works this way"


class TestTextFidelity:
    """Category D: resulting window text is derived verbatim from
    original segments -- no summarization, no invented content."""

    def test_window_text_is_exact_concatenation_of_segment_text(self):
        segments = [("The quick brown fox", 0.0, 1.0), ("jumps over the lazy dog", 1.0, 2.0)]
        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)
        assert windows[0].text == "The quick brown fox jumps over the lazy dog"

    def test_empty_or_whitespace_only_segments_contribute_nothing(self):
        segments = [("Real content here", 0.0, 1.0), ("   ", 1.0, 1.5), ("", 1.5, 1.6), ("More content", 1.6, 2.0)]
        windows = group_segments_into_windows(segments, target_window_words=100, min_window_words=1)
        assert len(windows) == 1
        assert windows[0].text == "Real content here More content"
        assert windows[0].end == 2.0  # the empty segments' timestamps are simply skipped, not fabricated

    def test_all_empty_segments_produce_no_windows(self):
        segments = [("", 0.0, 1.0), ("   ", 1.0, 2.0)]
        assert group_segments_into_windows(segments, target_window_words=100, min_window_words=1) == []

    def test_empty_input_produces_no_windows(self):
        assert group_segments_into_windows([], target_window_words=100, min_window_words=1) == []


class TestSingleOverlongSegment:
    def test_a_single_segment_longer_than_target_still_becomes_its_own_window_never_truncated(self):
        long_text = " ".join(f"word{i}" for i in range(200))
        segments = [(long_text, 0.0, 60.0)]
        windows = group_segments_into_windows(segments, target_window_words=50, min_window_words=1)
        assert len(windows) == 1
        assert windows[0].text == long_text  # never truncated/dropped


class TestReturnType:
    def test_returns_transcript_window_instances(self):
        windows = group_segments_into_windows([("a b c", 0.0, 1.0)], target_window_words=100, min_window_words=1)
        assert isinstance(windows[0], TranscriptWindow)
