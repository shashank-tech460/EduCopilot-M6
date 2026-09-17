from app.services.followup_context import (
    build_enriched_retrieval_query,
    is_elliptical_query,
    references_earlier_topic,
)


class TestPronouns:
    def test_it_this_that_them_these_those_its_their_are_elliptical(self):
        for pronoun in ["it", "this", "that", "them", "these", "those", "its", "their"]:
            assert is_elliptical_query(f"Explain {pronoun}") is True, f"{pronoun!r} should trigger enrichment"

    def test_domain_agnostic_pronoun_examples(self):
        for message in [
            "Explain it simply.",
            "Explain its second normal form.",
            "Why is it useful?",
            "How does it establish a connection?",
            "Why is it used?",
        ]:
            assert is_elliptical_query(message) is True, f"{message!r} should be elliptical"


class TestDemonstratives:
    def test_this_and_that_variants(self):
        assert is_elliptical_query("Explain this in simple language.") is True
        assert is_elliptical_query("What does that mean?") is True


class TestOmittedSubject:
    def test_short_pronoun_only_queries(self):
        assert is_elliptical_query("What are its advantages?") is True
        assert is_elliptical_query("How is it created?") is True


class TestWhyHowFollowUps:
    def test_bare_why_and_how_are_elliptical(self):
        assert is_elliptical_query("why") is True
        assert is_elliptical_query("Why?") is True
        assert is_elliptical_query("how") is True

    def test_why_how_with_their_own_subject_are_not_elliptical(self):
        assert is_elliptical_query("How does inheritance work in Java?") is False
        assert is_elliptical_query("Why does deadlock occur in an operating system?") is False


class TestExamples:
    def test_give_example_phrases(self):
        assert is_elliptical_query("Give me an example.") is True
        assert is_elliptical_query("Give another example.") is True


class TestDeeperExplanation:
    def test_explain_it_variants(self):
        for message in ["Explain it.", "Explain it simply.", "Explain it in detail.", "Explain it with an example."]:
            assert is_elliptical_query(message) is True

    def test_make_it_shorter_or_simpler(self):
        assert is_elliptical_query("Make it shorter.") is True
        assert is_elliptical_query("Make it simpler.") is True

    def test_elaborate_and_tell_me_more(self):
        assert is_elliptical_query("Elaborate.") is True
        assert is_elliptical_query("Tell me more.") is True
        assert is_elliptical_query("Go deeper.") is True
        assert is_elliptical_query("Explain further.") is True
        assert is_elliptical_query("Continue.") is True


class TestComparisons:
    def test_compare_them_and_difference_phrases(self):
        assert is_elliptical_query("Compare them.") is True
        assert is_elliptical_query("What's the difference?") is True
        # Exact whole-phrase match by design (see module docstring) --
        # "which one" alone triggers enrichment, but a longer sentence
        # built around it does not, since that's a substantially
        # different string, not merely "which one" with extra words.
        # This is intentional: avoiding substring matching is exactly
        # what prevents false positives on self-contained questions.
        assert is_elliptical_query("which one") is True
        assert is_elliptical_query("Which one is better?") is False


class TestOrdinalReferences:
    def test_ordinal_phrases_are_elliptical_but_not_claimed_resolved(self):
        """These trigger enrichment (best-effort topical help) -- this
        test does NOT and cannot assert exact referent resolution,
        which this module explicitly never claims."""

        for message in ["the first one", "the second one", "the third one", "the last one", "the previous one"]:
            assert is_elliptical_query(message) is True


class TestRelativeBackwardTopicReferences:
    """MVP M6 design-validation correction: these must NEVER be enriched
    with the most recent turn -- confirmed excluded."""

    def test_backward_topic_phrases_are_not_elliptical(self):
        for message in [
            "go back to the previous topic",
            "what about the previous topic",
            "let's return to the previous concept",
            "what about before that",
            "as I mentioned above",
            "the above",
            "earlier topic",
        ]:
            assert is_elliptical_query(message) is False, f"{message!r} must not trigger enrichment"

    def test_references_earlier_topic_helper_directly(self):
        assert references_earlier_topic("go back to the previous topic") is True
        assert references_earlier_topic("what is a process?") is False


class TestSelfContainedAcademicQuestionsAreNeverElliptical:
    """Domain-agnostic verification across multiple subjects -- no
    subject-specific logic exists anywhere in the classifier."""

    def test_multiple_subject_domains(self):
        for message in [
            "What is process scheduling?",
            "What is normalization?",
            "What is random forest?",
            "What is TCP?",
            "What is inheritance?",
            "What is MQTT?",
            "Explain deadlock in operating systems.",
            "What are FCFS and Round Robin?",
        ]:
            assert is_elliptical_query(message) is False, f"{message!r} must NOT trigger enrichment"


class TestBuildEnrichedRetrievalQuery:
    def test_prepends_previous_user_turn(self):
        result = build_enriched_retrieval_query("Explain it simply.", "What is process scheduling?")
        assert result == "What is process scheduling? Explain it simply."

    def test_domain_agnostic_examples(self):
        assert build_enriched_retrieval_query(
            "Explain its second normal form.", "What is normalization?"
        ) == "What is normalization? Explain its second normal form."
        assert build_enriched_retrieval_query(
            "Why is it useful?", "What is random forest?"
        ) == "What is random forest? Why is it useful?"

    def test_returns_original_query_unchanged_when_no_previous_turn(self):
        result = build_enriched_retrieval_query("Explain it.", None)
        assert result == "Explain it."
