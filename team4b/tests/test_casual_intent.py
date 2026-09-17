from app.services.casual_intent import is_casual_message


class TestIsCasualMessage:
    def test_recognizes_common_greetings_and_pleasantries(self):
        for message in ["Hi", "Hello", "Hey", "Good morning", "Thanks", "Thank you", "Bye", "How are you?"]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"

    def test_case_insensitive_and_tolerant_of_trailing_punctuation(self):
        assert is_casual_message("HI!") is True
        assert is_casual_message("  hello.  ") is True
        assert is_casual_message("Hey,") is True

    def test_a_short_course_question_is_never_classified_as_casual(self):
        assert is_casual_message("OS?") is False
        assert is_casual_message("What is an operating system?") is False

    def test_a_substantive_question_containing_a_greeting_word_is_not_misclassified(self):
        # Whole-string match only -- "hi" appearing inside a longer,
        # genuine question must never trigger the casual gate.
        assert is_casual_message("Hi, what is a process in an operating system?") is False

    def test_empty_string_is_not_casual(self):
        assert is_casual_message("") is False

    def test_unrelated_academic_terms_are_not_casual(self):
        assert is_casual_message("revision notes") is False
        assert is_casual_message("give me 5 MCQs") is False


class TestExpandedCasualCoverage:
    """MVP M6 round-2 correction -- expanded, curated deterministic
    coverage. Every message here is one of the task's own explicitly
    required examples."""

    def test_expanded_greetings_are_casual(self):
        for message in [
            "hi there",
            "hello there",
            "how are you doing",
            "how's it going",
            "hows it going",
            "hi how are you",
            "hello how are you",
            "hey how are you",
            "hi how are you?",
            "Hey, how are you?",
        ]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"

    def test_expanded_thanks_are_casual(self):
        for message in ["thanks a lot", "thank you so much", "much appreciated"]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"

    def test_expanded_acknowledgements_are_casual(self):
        for message in ["got it", "understood", "I understand", "makes sense", "that makes sense", "all clear"]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"

    def test_expanded_positive_reactions_are_casual(self):
        for message in ["nice", "awesome", "perfect", "excellent", "cool", "sounds good", "that's great", "that's interesting"]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"

    def test_expanded_farewells_are_casual(self):
        for message in ["see you", "see you later", "take care", "good night", "goodnight"]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"

    def test_the_original_live_regression_is_fixed(self):
        # The exact live-reproduced failure this correction exists for.
        assert is_casual_message("Hi how are you?") is True


class TestAmbiguousMessagesRemainNonCasual:
    """MVP M6 explicit requirement: these can be meaningful tutor/quiz
    answers and must NOT be swallowed by the casual gate in M6."""

    def test_ambiguous_short_words_are_not_casual(self):
        for message in [
            "yes", "yeah", "yep", "yup", "no", "nope", "ok", "okay",
            "done", "good", "great", "sure", "right", "correct", "exactly",
        ]:
            assert is_casual_message(message) is False, f"{message!r} must NOT be classified as casual"

    def test_bare_option_letters_are_not_casual(self):
        for message in ["A", "B", "C", "D", "a", "b", "c", "d"]:
            assert is_casual_message(message) is False, f"{message!r} must NOT be classified as casual"


class TestAcademicBoundaryRemainsIntact:
    """A greeting combined with a substantive academic request must
    still reach RAG -- this is the exact distinction the live E2E test
    proved was already correct, and this correction must not regress it."""

    def test_greeting_plus_academic_request_is_not_casual(self):
        for message in [
            "what is an operating system?",
            "explain process in operating system",
            "hi, what is a process in an operating system?",
            "hello, explain memory management",
            "hey, what is deadlock?",
            "thanks, now explain process scheduling",
        ]:
            assert is_casual_message(message) is False, f"{message!r} must reach RAG, not the casual gate"


class TestHinglishCasualPhrases:
    """MVP M6 correction -- a curated set of clearly casual Hindi/
    Hinglish phrases, matching the exact same whole-phrase discipline
    as every other entry in _CASUAL_MESSAGES. NOT a "Hindi -> casual"
    language rule -- see the module's own comment at the insertion
    point for why that distinction matters and is preserved."""

    def test_required_casual_hinglish_examples(self):
        for message in [
            "Hi, kaise ho?",
            "Hello, kaise ho?",
            "Kya haal hai?",
            "Kaise ho?",
            "Kaise chal raha hai?",
            "Dhanyavaad!",
            "Shukriya!",
            "Thank you!",
            "Thanks!",
        ]:
            assert is_casual_message(message) is True, f"{message!r} should be classified as casual"


class TestTechnicalHinglishRemainsNonCasual:
    """MVP M6 explicit requirement: technical Hindi/Hinglish queries
    must reach RAG, never the casual gate, regardless of containing
    Hindi/Hinglish words."""

    def test_required_technical_hinglish_examples(self):
        for message in [
            "Process scheduling kya hota hai?",
            "FCFS scheduling kya hai?",
            "FCFS scheduling ka main disadvantage kya hai?",
            "Video ke according process scheduling kaise kaam karta hai?",
            "CPU ko multiple processes ke beech kaise schedule kiya jata hai?",
            "Isko simple language mein samjhao.",
            "Explain process scheduling in Hindi.",
        ]:
            assert is_casual_message(message) is False, f"{message!r} must reach RAG, not the casual gate"

    def test_a_technical_query_containing_kaise_is_not_swept_up_by_the_new_casual_phrases(self):
        """Directly proves the new 'kaise ho'/'kaise chal raha hai'
        entries don't leak into unrelated longer sentences containing
        the word 'kaise' -- whole-phrase matching, not a keyword rule."""

        assert is_casual_message("Video ke according process scheduling kaise kaam karta hai?") is False


class TestAmbiguousShortInputsStillPreservedAfterHinglishAddition:
    """Explicit regression: the existing exact/whole-phrase safety
    behavior for ambiguous short inputs must be completely unaffected
    by this Hinglish addition."""

    def test_ambiguous_short_words_remain_non_casual(self):
        for message in ["yes", "no", "ok", "okay"]:
            assert is_casual_message(message) is False, f"{message!r} must NOT be classified as casual"
