"""Focused tests for Task 3.1's BM25Index.

Scope: unit, boundary, and error-path tests for the standalone BM25
component only. Does NOT test HybridRetriever, RRF, or search-mode
routing (Task 3.2), and does NOT implement Property 4-7 (Task 3.3).
"""

from __future__ import annotations

from app.services.bm25_index import BM25Document, BM25Index, default_tokenizer


class TestDefaultTokenizer:
    def test_lowercases_and_splits_on_whitespace(self):
        assert default_tokenizer("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self):
        assert default_tokenizer("hybrid-search, RAG!") == ["hybrid", "search", "rag"]

    def test_empty_string_yields_no_tokens(self):
        assert default_tokenizer("") == []

    def test_numbers_are_tokens(self):
        assert default_tokenizer("Property 5 uses k=60") == ["property", "5", "uses", "k", "60"]

    # -- MVP M6 Phase 1: Devanagari/Hindi multilingual lexical support --

    def test_devanagari_text_is_tokenized_into_words(self):
        assert default_tokenizer("प्रोसेस शेड्यूलिंग क्या है") == [
            "प्रोसेस",
            "शेड्यूलिंग",
            "क्या",
            "है",
        ]

    def test_romanized_hindi_hinglish_is_tokenized_like_ordinary_ascii(self):
        # Hinglish (Hindi written in Latin/Roman script) needs no special
        # handling: it is already ordinary ASCII text and matches the
        # pre-existing [A-Za-z0-9]+ alternative unchanged.
        assert default_tokenizer("FCFS scheduling kya hai?") == ["fcfs", "scheduling", "kya", "hai"]

    def test_mixed_english_and_devanagari_text_is_tokenized_into_separate_words(self):
        assert default_tokenizer("Process Scheduling क्या है") == [
            "process",
            "scheduling",
            "क्या",
            "है",
        ]

    def test_english_query_sentence_still_tokenizes_as_before(self):
        assert default_tokenizer("What is process scheduling?") == ["what", "is", "process", "scheduling"]

    def test_devanagari_danda_is_a_separator_not_a_token_and_does_not_merge_words(self):
        # Danda (।, U+0964) and double danda (॥, U+0965) are Hindi
        # sentence-ending punctuation, analogous to ASCII '.'/'!' --
        # they must act as separators, never become tokens themselves,
        # and never fuse the words on either side of them into one
        # token. Built with \u escapes (rather than pasting the glyphs)
        # so the exact codepoint under test is unambiguous.
        danda = "।"
        double_danda = "॥"
        assert default_tokenizer("प्रोसेस शेड्यूलिंग" + danda + "क्या है") == [
            "प्रोसेस",
            "शेड्यूलिंग",
            "क्या",
            "है",
        ]
        assert default_tokenizer("है" + double_danda + "क्या") == ["है", "क्या"]

    def test_devanagari_only_punctuation_yields_no_tokens(self):
        danda = "।"
        double_danda = "॥"
        assert default_tokenizer(f"{danda} {double_danda} {danda}{danda}") == []

    def test_devanagari_digits_are_tokens(self):
        # १-३ are the Devanagari digits १२३ (1, 2, 3) -- written
        # with escapes, not pasted glyphs, so the exact codepoints under
        # test are unambiguous.
        assert default_tokenizer("१२३") == ["१२३"]


class TestBM25IndexBasics:
    def test_empty_index_has_zero_size(self):
        index = BM25Index()
        assert index.size == 0

    def test_search_on_empty_index_returns_empty_list(self):
        index = BM25Index()
        assert index.search("anything", workspace_id="ws-1") == []

    def test_add_documents_increases_size(self):
        index = BM25Index()
        index.add_documents(
            [BM25Document(chunk_id="c1", text="hybrid search", workspace_id="ws-1"), BM25Document(chunk_id="c2", text="vector database", workspace_id="ws-1")]
        )
        assert index.size == 2

    def test_rebuild_replaces_entire_corpus(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="old content", workspace_id="ws-1")])
        index.rebuild([BM25Document(chunk_id="c2", text="new content", workspace_id="ws-1")])

        assert index.size == 1
        results = index.search("new", workspace_id="ws-1")
        assert [chunk_id for chunk_id, _ in results] == ["c2"]

    def test_add_documents_with_existing_chunk_id_replaces_text(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="original text about cats", workspace_id="ws-1")])
        index.add_documents([BM25Document(chunk_id="c1", text="updated text about dogs", workspace_id="ws-1")])

        assert index.size == 1  # replaced, not duplicated
        results = index.search("dogs", workspace_id="ws-1")
        assert results[0][0] == "c1"
        results_for_old_term = index.search("cats", workspace_id="ws-1")
        assert results_for_old_term == [] or results_for_old_term[0][1] == 0.0

    def test_remove_documents_decreases_size(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="a", workspace_id="ws-1"), BM25Document(chunk_id="c2", text="b", workspace_id="ws-1")])
        index.remove_documents(["c1"])
        assert index.size == 1

    def test_remove_nonexistent_chunk_id_is_a_noop(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="a", workspace_id="ws-1")])
        index.remove_documents(["does-not-exist"])
        assert index.size == 1

    def test_removing_all_documents_returns_index_to_empty_state(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="a", workspace_id="ws-1")])
        index.remove_documents(["c1"])
        assert index.size == 0
        assert index.search("a", workspace_id="ws-1") == []


class TestBM25IndexSearchRelevance:
    def test_more_relevant_document_ranks_higher(self):
        # BM25's IDF term is degenerate on very small corpora (a query
        # term appearing in most/all documents can get a zero or negative
        # IDF -- a well-known BM25 property, not a bug in this class).
        # A handful of filler documents keeps document frequency
        # meaningful, matching how BM25 is actually used in practice.
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="high", text="reciprocal rank fusion reciprocal rank fusion algorithm", workspace_id="ws-1"),
                BM25Document(chunk_id="low", text="an unrelated document about cooking pasta", workspace_id="ws-1"),
                BM25Document(chunk_id="filler1", text="the weather today is sunny and warm", workspace_id="ws-1"),
                BM25Document(chunk_id="filler2", text="stock prices rose sharply this quarter", workspace_id="ws-1"),
                BM25Document(chunk_id="filler3", text="the museum exhibit opens next month", workspace_id="ws-1"),
            ]
        )

        results = index.search("reciprocal rank fusion", workspace_id="ws-1")

        assert results[0][0] == "high"
        assert results[0][1] > dict(results)["low"]

    def test_document_with_no_matching_terms_scores_at_or_below_matching_ones(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="match", text="hybrid retrieval combines bm25 and vectors", workspace_id="ws-1"),
                BM25Document(chunk_id="no_match", text="completely different subject matter entirely", workspace_id="ws-1"),
                BM25Document(chunk_id="filler1", text="the weather today is sunny and warm", workspace_id="ws-1"),
                BM25Document(chunk_id="filler2", text="stock prices rose sharply this quarter", workspace_id="ws-1"),
                BM25Document(chunk_id="filler3", text="the museum exhibit opens next month", workspace_id="ws-1"),
            ]
        )

        results = dict(index.search("hybrid retrieval", workspace_id="ws-1"))

        assert results["match"] > results["no_match"]

    def test_top_k_limits_results(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id=f"c{i}", text="shared keyword term", workspace_id="ws-1") for i in range(10)])

        results = index.search("keyword", top_k=3, workspace_id="ws-1")

        assert len(results) == 3

    def test_top_k_none_returns_every_indexed_document(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id=f"c{i}", text="shared keyword term", workspace_id="ws-1") for i in range(7)])

        results = index.search("keyword", workspace_id="ws-1")

        assert len(results) == 7

    def test_case_insensitive_matching(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="c1", text="Reciprocal Rank Fusion", workspace_id="ws-1"),
                BM25Document(chunk_id="filler1", text="the weather today is sunny and warm", workspace_id="ws-1"),
                BM25Document(chunk_id="filler2", text="stock prices rose sharply this quarter", workspace_id="ws-1"),
            ]
        )

        results = dict(index.search("reciprocal RANK fusion", workspace_id="ws-1"))

        assert results["c1"] > results["filler1"]
        assert results["c1"] > results["filler2"]

    def test_small_corpus_idf_can_legitimately_be_zero_or_negative(self):
        """Documents this as expected BM25 behavior, not a defect: with a
        tiny corpus, a term appearing in most/all documents can get a
        zero or negative IDF, which is a property of the classic BM25
        formula itself (log((N-df+0.5)/(df+0.5))), independent of
        anything this class does. Callers combining BM25 with vector
        search (Task 3.2) need to be aware small/skewed corpora can
        produce non-positive BM25 scores even for an exact match.
        """

        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="only_doc", text="reciprocal rank fusion", workspace_id="ws-1")])

        results = index.search("reciprocal rank fusion", workspace_id="ws-1")

        # A single-document corpus where the query matches everything
        # present produces a non-positive score under classic BM25 --
        # asserting this explicitly so it's a known, tested behavior
        # rather than a surprise discovered later in Task 3.2.
        assert results[0][0] == "only_doc"
        assert results[0][1] <= 0.0


class TestBM25IndexEdgeCases:
    def test_empty_query_string_returns_empty_results(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="some content", workspace_id="ws-1")])

        assert index.search("", workspace_id="ws-1") == []

    def test_whitespace_only_query_returns_empty_results(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="some content", workspace_id="ws-1")])

        assert index.search("   ", workspace_id="ws-1") == []

    def test_query_with_only_punctuation_returns_empty_results(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="some content", workspace_id="ws-1")])

        assert index.search("!!!---???", workspace_id="ws-1") == []

    def test_query_term_not_in_corpus_returns_all_documents_scored(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="apples and oranges", workspace_id="ws-1")])

        # rank_bm25 still returns a score (typically 0.0) for every
        # indexed document even when the query term never appears --
        # this component does not filter by a relevance threshold
        # (that's Property 6 / HybridRetriever's job in Task 3.2).
        results = index.search("nonexistentterm", workspace_id="ws-1")

        assert len(results) == 1
        assert results[0][0] == "c1"

    def test_empty_text_document_can_be_indexed_without_error(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="c1", text="", workspace_id="ws-1")])

        assert index.size == 1
        # An entirely-empty corpus (every document tokenizes to zero
        # terms) cannot be scored by rank_bm25 at all -- it divides by
        # zero internally (a genuine rank_bm25 limitation, not a Team 4B
        # requirement). Documented Task 3.1 behavior: treated as nothing
        # searchable, rather than raising ZeroDivisionError up through
        # this class's own public API.
        assert index.search("anything", workspace_id="ws-1") == []

    def test_custom_tokenizer_is_used(self):
        calls: list[str] = []

        def tracking_tokenizer(text: str) -> list[str]:
            calls.append(text)
            return text.split()

        index = BM25Index(tokenizer=tracking_tokenizer)
        index.add_documents([BM25Document(chunk_id="c1", text="hello world", workspace_id="ws-1")])
        index.search("hello", workspace_id="ws-1")

        assert "hello world" in calls
        assert "hello" in calls

    def test_scores_are_not_normalized_to_unit_interval(self):
        # Explicit regression guard: normalization to [0.0, 1.0] is
        # Property 7 / HybridRetriever's job (Task 3.2), not this
        # component's. A rare query term repeated many times in one
        # document, against a corpus large enough for a healthy positive
        # IDF, should be able to score above 1.0 under raw BM25.
        index = BM25Index()
        index.add_documents(
            [BM25Document(chunk_id="c1", text=" ".join(["distinctiveterm"] * 20), workspace_id="ws-1")]
            + [BM25Document(chunk_id=f"filler{i}", text="ordinary unrelated filler content here", workspace_id="ws-1") for i in range(5)]
        )

        results = index.search("distinctiveterm", workspace_id="ws-1")

        assert dict(results)["c1"] > 1.0


class TestBM25IndexWorkspaceIsolation:
    """MVP M3: BM25Index.search() must never score or return a document
    belonging to a different workspace than the one requested, even when
    that document would rank highly against the query."""

    def test_search_only_returns_documents_from_the_requested_workspace(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="a1", text="reciprocal rank fusion algorithm details", workspace_id="workspace-A"),
                BM25Document(chunk_id="b1", text="reciprocal rank fusion algorithm details", workspace_id="workspace-B"),
            ]
        )

        results_a = index.search("reciprocal rank fusion", workspace_id="workspace-A")
        results_b = index.search("reciprocal rank fusion", workspace_id="workspace-B")

        assert [chunk_id for chunk_id, _ in results_a] == ["a1"]
        assert [chunk_id for chunk_id, _ in results_b] == ["b1"]

    def test_a_highly_relevant_cross_workspace_document_never_appears(self):
        """The exact scenario named in the governing task: a highly
        relevant document in workspace B must never enter workspace A's
        BM25 candidate list, even though it would clearly outrank
        workspace A's own, less-relevant content."""

        index = BM25Index()
        index.add_documents(
            [
                BM25Document(
                    chunk_id="b-highly-relevant",
                    text="reciprocal rank fusion reciprocal rank fusion reciprocal rank fusion",
                    workspace_id="workspace-B",
                ),
                BM25Document(chunk_id="a-filler", text="an unrelated document about cooking pasta", workspace_id="workspace-A"),
            ]
        )

        results_a = index.search("reciprocal rank fusion", workspace_id="workspace-A")

        assert "b-highly-relevant" not in [chunk_id for chunk_id, _ in results_a]

    def test_identical_content_in_both_workspaces_still_isolated(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="a1", text="identical shared content about databases", workspace_id="workspace-A"),
                BM25Document(chunk_id="b1", text="identical shared content about databases", workspace_id="workspace-B"),
            ]
        )

        results_a = index.search("databases", workspace_id="workspace-A")
        assert [chunk_id for chunk_id, _ in results_a] == ["a1"]

    def test_document_indexed_with_no_workspace_id_is_never_returned_by_any_real_search(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="orphan", text="some searchable content here")])  # workspace_id defaults to None

        results = index.search("searchable content", workspace_id="workspace-A")

        assert results == []

    def test_workspace_with_no_documents_returns_empty_not_an_error(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="a1", text="some content", workspace_id="workspace-A")])

        results = index.search("some content", workspace_id="workspace-nonexistent")

        assert results == []

    def test_search_requires_workspace_id_no_default(self):
        import inspect

        signature = inspect.signature(BM25Index.search)
        assert signature.parameters["workspace_id"].default is inspect.Parameter.empty

    def test_concurrent_workspace_searches_do_not_interfere(self):
        """No mutable global workspace state -- two searches for
        different workspaces, interleaved, must each see only their own
        workspace's documents. `BM25Index` itself has no shared/global
        'current workspace' attribute at all (verified structurally: the
        class has no such instance attribute to begin with), and this
        test additionally proves it behaviorally under real interleaved
        calls."""

        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="a1", text="database systems and normalization", workspace_id="workspace-A"),
                BM25Document(chunk_id="b1", text="database systems and normalization", workspace_id="workspace-B"),
            ]
        )

        results = []
        for _ in range(5):
            results.append(("A", index.search("database systems", workspace_id="workspace-A")))
            results.append(("B", index.search("database systems", workspace_id="workspace-B")))

        for label, result in results:
            expected_chunk = "a1" if label == "A" else "b1"
            assert [chunk_id for chunk_id, _ in result] == [expected_chunk]


class TestM6DocumentIdsScope:
    """MVP M6 document-level retrieval scope -- BM25Index enforcement."""

    def test_document_ids_narrows_to_only_the_selected_documents_within_the_workspace(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="a1", text="normalization theory", workspace_id="ws-1", document_id="doc-A"),
                BM25Document(chunk_id="b1", text="normalization theory", workspace_id="ws-1", document_id="doc-B"),
            ]
        )

        results = index.search("normalization", workspace_id="ws-1", document_ids=["doc-A"])

        assert [chunk_id for chunk_id, _ in results] == ["a1"]

    def test_empty_document_ids_returns_nothing_never_widens(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="a1", text="content", workspace_id="ws-1", document_id="doc-A")])

        results = index.search("content", workspace_id="ws-1", document_ids=[])

        assert results == []

    def test_document_ids_none_preserves_full_workspace_scope(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="a1", text="content", workspace_id="ws-1", document_id="doc-A"),
                BM25Document(chunk_id="b1", text="content", workspace_id="ws-1", document_id="doc-B"),
            ]
        )

        results = index.search("content", workspace_id="ws-1", document_ids=None)

        assert {chunk_id for chunk_id, _ in results} == {"a1", "b1"}

    def test_a_highly_relevant_document_outside_the_scope_is_never_returned(self):
        """Mirrors TEST 20/21's actual-filter-enforcement requirement at
        the BM25 level specifically."""

        index = BM25Index()
        index.add_documents(
            [
                BM25Document(
                    chunk_id="unselected-highly-relevant",
                    text="reciprocal rank fusion reciprocal rank fusion reciprocal rank fusion",
                    workspace_id="ws-1",
                    document_id="doc-unselected",
                ),
                BM25Document(chunk_id="selected-weak", text="reciprocal", workspace_id="ws-1", document_id="doc-selected"),
            ]
        )

        results = index.search("reciprocal rank fusion", workspace_id="ws-1", document_ids=["doc-selected"])

        assert "unselected-highly-relevant" not in [chunk_id for chunk_id, _ in results]

    def test_document_id_cannot_bypass_workspace_scope(self):
        """A document_id belonging to a DIFFERENT workspace than the one
        authenticated must never be returned, even if explicitly requested."""

        index = BM25Index()
        index.add_documents(
            [BM25Document(chunk_id="b1", text="secret content", workspace_id="workspace-B", document_id="doc-B1")]
        )

        results = index.search("secret content", workspace_id="workspace-A", document_ids=["doc-B1"])

        assert results == []

    def test_document_indexed_with_no_document_id_never_matches_a_real_document_ids_search(self):
        index = BM25Index()
        index.add_documents([BM25Document(chunk_id="orphan", text="content", workspace_id="ws-1")])  # document_id defaults to None

        results = index.search("content", workspace_id="ws-1", document_ids=["some-real-doc-id"])

        assert results == []


class TestBM25IndexHindiRetrieval:
    """MVP M6 Phase 1: end-to-end retrieval tests through
    `BM25Index.search()` for Devanagari content -- not just
    `default_tokenizer()` in isolation. These exercise general Hindi
    lexical retrieval, not one hardcoded query: the sentences here are
    ordinary example content (matching this task's own examples), never
    special-cased in the implementation itself.

    `_DEVANAGARI_DIGITS` is used as "unrelated but same-script" filler
    content: it is genuine Devanagari-block text (so it proves BM25
    isn't merely rewarding "is this Hindi-script"), built from \\u
    escapes rather than a hand-typed Hindi sentence, to keep the test
    data itself unambiguous.
    """

    _DEVANAGARI_DIGITS = "१२३४५"  # १२३४५

    def test_devanagari_query_retrieves_the_matching_hindi_document(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="relevant", text="प्रोसेस शेड्यूलिंग क्या है", workspace_id="ws-1"),
                BM25Document(chunk_id="unrelated_same_script", text=self._DEVANAGARI_DIGITS, workspace_id="ws-1"),
                BM25Document(chunk_id="filler1", text="the weather today is sunny and warm", workspace_id="ws-1"),
                BM25Document(chunk_id="filler2", text="stock prices rose sharply this quarter", workspace_id="ws-1"),
            ]
        )

        results = dict(index.search("प्रोसेस शेड्यूलिंग", workspace_id="ws-1"))

        assert results["relevant"] > results["unrelated_same_script"]

    def test_unrelated_devanagari_document_is_not_preferred_merely_for_sharing_a_script(self):
        """A Hindi-script document that shares none of the query's actual
        terms must not outrank -- or even be distinguishable from -- an
        English document that also shares no terms. Proves BM25 is still
        scoring by term overlap, not by script/language identity."""

        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="relevant", text="प्रोसेस शेड्यूलिंग क्या है", workspace_id="ws-1"),
                BM25Document(chunk_id="unrelated_hindi", text=self._DEVANAGARI_DIGITS, workspace_id="ws-1"),
                BM25Document(chunk_id="unrelated_english", text="an unrelated document about cooking pasta", workspace_id="ws-1"),
            ]
        )

        results = dict(index.search("प्रोसेस शेड्यूलिंग क्या है", workspace_id="ws-1"))

        assert results["relevant"] > results["unrelated_hindi"]
        assert results["relevant"] > results["unrelated_english"]
        # Neither unrelated document contains any query term, so BM25
        # gives both the same (zero) score regardless of script.
        assert results["unrelated_hindi"] == results["unrelated_english"]

    def test_mixed_english_and_hindi_query_matches_mixed_content_document(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="mixed", text="Process Scheduling क्या है", workspace_id="ws-1"),
                BM25Document(chunk_id="filler1", text="the weather today is sunny and warm", workspace_id="ws-1"),
                BM25Document(chunk_id="filler2", text=self._DEVANAGARI_DIGITS, workspace_id="ws-1"),
            ]
        )

        results = dict(index.search("Process Scheduling क्या है", workspace_id="ws-1"))

        assert results["mixed"] > results["filler1"]
        assert results["mixed"] > results["filler2"]

    def test_english_query_retrieval_is_unaffected_by_devanagari_support(self):
        index = BM25Index()
        index.add_documents(
            [
                BM25Document(chunk_id="english", text="What is process scheduling?", workspace_id="ws-1"),
                BM25Document(chunk_id="hindi", text="प्रोसेस शेड्यूलिंग क्या है", workspace_id="ws-1"),
                BM25Document(chunk_id="filler", text="an unrelated document about cooking pasta", workspace_id="ws-1"),
            ]
        )

        results = dict(index.search("What is process scheduling", workspace_id="ws-1"))

        assert results["english"] > results["hindi"]
        assert results["english"] > results["filler"]
