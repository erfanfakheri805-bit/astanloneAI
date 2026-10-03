"""
Tests for Prompt 438 - Learned Expression Variation Matching.

`LearnedExpressionVariationMatcher`
(language_intelligence/learned_expression_variation_matcher.py) connects
equivalent learned expressions and known language variations, using ONLY
relationship information already explicitly stored (Prompt 417) and the
learned items themselves (Prompt 416) - never fabricating a synonym or a
meaning, never guessing from spelling similarity.

Run directly:
    python -m unittest tests.test_learned_expression_variation_matcher -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import (
    LanguageLearningStore, ITEM_TYPE_WORD, ITEM_TYPE_PHRASE, ITEM_TYPE_PATTERN,
)
from language_intelligence.language_relationships import (
    LanguageRelationshipStore, RELATION_SYNONYM, RELATION_TRANSLATION,
    RELATION_RELATED_MEANING, RELATION_GRAMMATICAL, RELATION_WORD_TO_PHRASE,
)
from language_intelligence.learned_expression_variation_matcher import (
    LearnedExpressionVariationMatcher, STATUS_MATCHED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND,
    REASON_EXACT_MATCH, REASON_VARIATION_MATCH, REASON_MULTIPLE_EXACT_CANDIDATES,
    REASON_MULTIPLE_VARIATION_CANDIDATES, REASON_NO_RELATIONSHIP, RELATION_TYPE_EXACT,
)
from language_intelligence.meaning_resolution import MeaningResolver, STATUS_RESOLVED
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, STATUS_MATCHED as PATTERN_STATUS_MATCHED,
)
from core.core import Core


class _MatcherTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + the composed stores + the matcher."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(self.db_path)
        self.items = LanguageLearningStore(self.memory)
        self.knowledge = KnowledgeSystem(self.memory)
        self.rels = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.matcher = LearnedExpressionVariationMatcher(self.items, self.rels)

    def tearDown(self):
        self._tmpdir.cleanup()


class TestExactExpressionStillMatches(_MatcherTestCase):
    """1. Exact learned expression still matches."""

    def test_exact_match_returns_matched(self):
        self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"}, confidence=0.9,
            source="taught",
        )
        result = self.matcher.match("hello", language="en")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertTrue(result.matched)
        self.assertEqual(result.candidate["matched_expression"], "hello")
        self.assertEqual(result.candidate["relation_type"], RELATION_TYPE_EXACT)
        self.assertEqual(result.reason, REASON_EXACT_MATCH)

    def test_exact_match_is_case_and_whitespace_insensitive_like_the_store(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "Good Morning")
        result = self.matcher.match("  good   morning ", language="en")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "Good Morning")

    def test_exact_match_does_not_require_relationships(self):
        # No relationship stored at all - exact match alone is enough.
        self.items.learn_item("en", ITEM_TYPE_WORD, "cat")
        result = self.matcher.match("cat", language="en")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(self._count_relationships(), 0)

    def _count_relationships(self):
        return self.memory.query_one(
            "SELECT COUNT(*) AS c FROM language_item_relationships"
        )["c"]


class TestExplicitSynonymRelationshipMatches(_MatcherTestCase):
    """2. Explicit synonym relationship matches."""

    def test_synonym_variation_is_matched(self):
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy", meaning={"gloss": "glad"})
        # "glad" is taught only as a PATTERN here, so an item_type=word
        # request cannot exact-match it directly - forcing the variation
        # lookup below to be what actually connects the two.
        self.items.learn_item("en", ITEM_TYPE_PATTERN, "glad")
        self.rels.relate(happy, self.items.get_item("en", ITEM_TYPE_PATTERN, "glad"), RELATION_SYNONYM)

        result = self.matcher.match("glad", language="en", item_type=ITEM_TYPE_WORD)
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "happy")
        self.assertEqual(result.candidate["relation_type"], RELATION_SYNONYM)
        self.assertEqual(result.candidate["via_expression"], "glad")
        self.assertEqual(result.reason, REASON_VARIATION_MATCH)


class TestExplicitTranslationRelationshipMatches(_MatcherTestCase):
    """3. Explicit translation relationship matches."""

    def test_translation_variation_is_matched_across_languages(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        # Taught as a PATTERN, not a word, so an item_type=word request
        # cannot exact-match "سلام" itself.
        salam = self.items.learn_item("persian", ITEM_TYPE_PATTERN, "سلام")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)

        result = self.matcher.match("سلام", language=None, item_type=ITEM_TYPE_WORD)
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "hello")
        self.assertEqual(result.candidate["language"], "english")
        self.assertEqual(result.candidate["relation_type"], RELATION_TRANSLATION)


class TestExplicitRelatedMeaningRelationshipMatches(_MatcherTestCase):
    """4. Explicit related-meaning relationship matches."""

    def test_related_meaning_variation_is_matched(self):
        greeting = self.items.learn_item("en", "meaning", "greeting", meaning={"intent": "greet"})
        # Taught as a PATTERN so an item_type="meaning" request cannot
        # exact-match "hiya" itself.
        hiya = self.items.learn_item("en", ITEM_TYPE_PATTERN, "hiya")
        self.rels.relate(greeting, hiya, RELATION_RELATED_MEANING)

        result = self.matcher.match("hiya", language="en", item_type="meaning")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "greeting")
        self.assertEqual(result.candidate["relation_type"], RELATION_RELATED_MEANING)


class TestBidirectionalRelationshipHandling(_MatcherTestCase):
    """5. Bidirectional relationship handling."""

    def test_symmetric_relationship_matches_from_either_side(self):
        # "big" a word, "large" a pattern - purely so neither side can
        # exact-match itself once the query below narrows by item_type,
        # forcing both directions to go through the relationship.
        big = self.items.learn_item("en", ITEM_TYPE_WORD, "big")
        large = self.items.learn_item("en", ITEM_TYPE_PATTERN, "large")
        self.rels.relate(big, large, RELATION_SYNONYM, symmetric=True)

        forward = self.matcher.match("large", language="en", item_type=ITEM_TYPE_WORD)
        backward = self.matcher.match("big", language="en", item_type=ITEM_TYPE_PATTERN)
        self.assertEqual(forward.status, STATUS_MATCHED)
        self.assertEqual(forward.candidate["matched_expression"], "big")
        self.assertEqual(backward.status, STATUS_MATCHED)
        self.assertEqual(backward.candidate["matched_expression"], "large")

    def test_directed_relationship_only_matches_forward(self):
        word = self.items.learn_item("en", ITEM_TYPE_WORD, "cat")
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "the cat")
        self.rels.relate(word, phrase, RELATION_WORD_TO_PHRASE, symmetric=False)

        # "cat" -[word_to_phrase]-> "the cat": forward is honored.
        forward = self.matcher.match("cat", language="en", item_type=ITEM_TYPE_PHRASE)
        self.assertEqual(forward.status, STATUS_MATCHED)
        self.assertEqual(forward.candidate["matched_expression"], "the cat")

        # Reversing a directed relationship is never implied.
        backward = self.matcher.match("the cat", language="en", item_type=ITEM_TYPE_WORD)
        self.assertEqual(backward.status, STATUS_NOT_FOUND)


class TestLanguageFiltering(_MatcherTestCase):
    """6. Language filtering."""

    def test_variation_candidate_outside_requested_language_is_excluded(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        salam = self.items.learn_item("persian", ITEM_TYPE_WORD, "سلام")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)

        # "hello" itself was never taught in Klingon, so the exact match
        # fails and only the relationship graph is left; the translation
        # target ("سلام") is Persian, not Klingon, so it is excluded too.
        result = self.matcher.match("hello", language="klingon")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_variation_candidate_within_requested_language_is_included(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        salam = self.items.learn_item("persian", ITEM_TYPE_WORD, "سلام")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)

        result = self.matcher.match("hello", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "سلام")


class TestLocaleHandling(_MatcherTestCase):
    """7. Locale handling."""

    def test_candidate_naming_a_different_locale_is_excluded(self):
        # "howdy" taught only as a PATTERN, so an item_type=word request
        # forces the fallback below rather than a trivial self-match.
        howdy = self.items.learn_item("en", ITEM_TYPE_PATTERN, "howdy")
        formal = self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"locale": "en-GB"},
        )
        self.rels.relate(howdy, formal, RELATION_SYNONYM)

        result = self.matcher.match(
            "howdy", language="en", item_type=ITEM_TYPE_WORD, locale="en-US",
        )
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_candidate_naming_the_requested_locale_is_included(self):
        howdy = self.items.learn_item("en", ITEM_TYPE_PATTERN, "howdy")
        formal = self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"locale": "en-GB"},
        )
        self.rels.relate(howdy, formal, RELATION_SYNONYM)

        result = self.matcher.match(
            "howdy", language="en", item_type=ITEM_TYPE_WORD, locale="en-GB",
        )
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "hello")

    def test_locale_agnostic_candidate_always_matches(self):
        howdy = self.items.learn_item("en", ITEM_TYPE_PATTERN, "howdy")
        hi = self.items.learn_item("en", ITEM_TYPE_WORD, "hi")  # no locale
        self.rels.relate(howdy, hi, RELATION_SYNONYM)

        result = self.matcher.match(
            "howdy", language="en", item_type=ITEM_TYPE_WORD, locale="en-US",
        )
        self.assertEqual(result.status, STATUS_MATCHED)


class TestMultipleValidCandidates(_MatcherTestCase):
    """8. Multiple valid candidates are all preserved."""

    def test_two_synonym_targets_are_both_kept(self):
        joyful = self.items.learn_item("en", ITEM_TYPE_WORD, "joyful")
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        # "glad" taught only as a PATTERN, forcing the item_type=word
        # query below through the relationship graph.
        glad = self.items.learn_item("en", ITEM_TYPE_PATTERN, "glad")
        self.rels.relate(glad, joyful, RELATION_SYNONYM)
        self.rels.relate(glad, happy, RELATION_SYNONYM)

        result = self.matcher.match("glad", language="en", item_type=ITEM_TYPE_WORD)
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(len(result.candidates), 2)
        matched_texts = {c["matched_expression"] for c in result.candidates}
        self.assertEqual(matched_texts, {"joyful", "happy"})


class TestAmbiguousResult(_MatcherTestCase):
    """9. Ambiguous result - nothing arbitrarily chosen."""

    def test_ambiguous_never_reports_matched(self):
        joyful = self.items.learn_item("en", ITEM_TYPE_WORD, "joyful")
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        glad = self.items.learn_item("en", ITEM_TYPE_PATTERN, "glad")
        self.rels.relate(glad, joyful, RELATION_SYNONYM)
        self.rels.relate(glad, happy, RELATION_SYNONYM)

        result = self.matcher.match("glad", language="en", item_type=ITEM_TYPE_WORD)
        self.assertFalse(result.matched)
        self.assertIsNone(result.candidate)
        self.assertEqual(result.reason, REASON_MULTIPLE_VARIATION_CANDIDATES)

    def test_ambiguous_exact_candidates_across_item_types(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "run")
        self.items.learn_item("en", ITEM_TYPE_PHRASE, "run")
        result = self.matcher.match("run", language="en")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, REASON_MULTIPLE_EXACT_CANDIDATES)
        self.assertEqual(len(result.candidates), 2)


class TestNoRelationshipReturnsNotFound(_MatcherTestCase):
    """10. No relationship -> NOT_FOUND."""

    def test_unknown_expression_is_not_found(self):
        result = self.matcher.match("xyzzy", language="en")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NO_RELATIONSHIP)
        self.assertEqual(result.candidates, [])

    def test_learned_item_with_no_relationship_is_not_found_under_a_different_text(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        # "hi" was never taught and never related to "hello".
        result = self.matcher.match("hi", language="en")
        self.assertEqual(result.status, STATUS_NOT_FOUND)


class TestNoGuessingFromSpellingAlone(_MatcherTestCase):
    """11. No guessing from spelling similarity or semantic intuition."""

    def test_similar_spelling_without_a_relationship_is_not_matched(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "color")
        # "colour" is spelling-similar but was never taught, and no
        # relationship connects the two - must not be guessed at.
        result = self.matcher.match("colour", language="en")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_obviously_related_meaning_without_a_stored_relationship_is_not_matched(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "dog", meaning={"gloss": "an animal"})
        self.items.learn_item("en", ITEM_TYPE_WORD, "puppy", meaning={"gloss": "a young dog"})
        # No relationship was ever stored between "dog" and "puppy" -
        # semantic intuition alone must never bridge that gap.
        result = self.matcher.match("puppy", language="en", item_type=ITEM_TYPE_WORD)
        # "puppy" IS itself a learned item, so this is an exact match on
        # itself, never silently redirected to "dog".
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "puppy")
        self.assertEqual(result.candidate["relation_type"], RELATION_TYPE_EXACT)


class TestConfidenceAndSourcePreservation(_MatcherTestCase):
    """12. Confidence/source preservation."""

    def test_exact_candidate_preserves_confidence_and_source(self):
        self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", confidence=0.75, source="user_taught",
        )
        result = self.matcher.match("hello", language="en")
        self.assertEqual(result.candidate["confidence"], 0.75)
        self.assertEqual(result.candidate["source"], "user_taught")

    def test_variation_candidate_preserves_both_item_and_relationship_provenance(self):
        happy = self.items.learn_item(
            "en", ITEM_TYPE_WORD, "happy", confidence=0.8, source="dictionary",
        )
        glad = self.items.learn_item(
            "en", ITEM_TYPE_PATTERN, "glad", confidence=0.6, source="user_taught",
        )
        self.rels.relate(
            happy, glad, RELATION_SYNONYM, confidence=0.95, source="linguist_reviewed",
        )
        result = self.matcher.match("glad", language="en", item_type=ITEM_TYPE_WORD)
        candidate = result.candidate
        self.assertEqual(candidate["confidence"], 0.8)       # the matched item's own
        self.assertEqual(candidate["source"], "dictionary")  # the matched item's own
        self.assertEqual(candidate["relationship_confidence"], 0.95)
        self.assertEqual(candidate["relationship_source"], "linguist_reviewed")


class TestOriginalMessagePreservation(_MatcherTestCase):
    """13. Original user message preservation."""

    def test_original_expression_preserved_exactly_on_every_status(self):
        raw = "  Glad  "
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        self.items.learn_item("en", ITEM_TYPE_WORD, "glad")
        self.rels.relate(happy, self.items.get_item("en", ITEM_TYPE_WORD, "glad"), RELATION_SYNONYM)

        matched = self.matcher.match(raw, language="en")
        self.assertEqual(matched.original_expression, raw)
        self.assertEqual(matched.candidate["original_expression"], raw)

        not_found = self.matcher.match("nonexistent-xyz", language="en")
        self.assertEqual(not_found.original_expression, "nonexistent-xyz")

        joyful = self.items.learn_item("en", ITEM_TYPE_WORD, "joyful")
        self.rels.relate(joyful, self.items.get_item("en", ITEM_TYPE_WORD, "glad"), RELATION_SYNONYM)
        ambiguous = self.matcher.match(raw, language="en")
        self.assertEqual(ambiguous.original_expression, raw)
        for candidate in ambiguous.candidates:
            self.assertEqual(candidate["original_expression"], raw)


class TestDeterministicRepeatedMatching(_MatcherTestCase):
    """14. Deterministic repeated matching."""

    def test_repeated_calls_return_identical_results(self):
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        self.items.learn_item("en", ITEM_TYPE_WORD, "glad")
        self.rels.relate(happy, self.items.get_item("en", ITEM_TYPE_WORD, "glad"), RELATION_SYNONYM)

        first = self.matcher.match("glad", language="en").to_dict()
        second = self.matcher.match("glad", language="en").to_dict()
        third = self.matcher.match("glad", language="en").to_dict()
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_repeated_ambiguous_calls_return_identical_candidate_sets(self):
        joyful = self.items.learn_item("en", ITEM_TYPE_WORD, "joyful")
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        glad = self.items.learn_item("en", ITEM_TYPE_WORD, "glad")
        self.rels.relate(glad, joyful, RELATION_SYNONYM)
        self.rels.relate(glad, happy, RELATION_SYNONYM)

        first = self.matcher.match("glad", language="en").to_dict()
        second = self.matcher.match("glad", language="en").to_dict()
        self.assertEqual(first, second)


class TestGrammaticalRelationshipReuse(_MatcherTestCase):
    """Reuse of grammatical relationships (requirement 2)."""

    def test_grammatical_relationship_can_be_followed(self):
        run = self.items.learn_item("en", ITEM_TYPE_WORD, "run")
        # "ran" taught only as a PATTERN, forcing the item_type=word
        # query below through the relationship graph, and stored as the
        # relationship's "from" end so querying from "ran" follows it in
        # its own stated (outgoing) direction.
        ran = self.items.learn_item("en", ITEM_TYPE_PATTERN, "ran")
        self.rels.relate(ran, run, RELATION_GRAMMATICAL, symmetric=False)
        result = self.matcher.match("ran", language="en", item_type=ITEM_TYPE_WORD)
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "run")
        self.assertEqual(result.candidate["relation_type"], RELATION_GRAMMATICAL)


class TestRelationTypesNarrowing(_MatcherTestCase):
    """relation_types narrows which relationships are followed."""

    def test_relation_types_filters_out_other_relation_types(self):
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        glad = self.items.learn_item("en", ITEM_TYPE_PATTERN, "glad")
        self.rels.relate(happy, glad, RELATION_SYNONYM)

        result = self.matcher.match(
            "glad", language="en", item_type=ITEM_TYPE_WORD, relation_types=[RELATION_TRANSLATION],
        )
        self.assertEqual(result.status, STATUS_NOT_FOUND)

        result = self.matcher.match(
            "glad", language="en", item_type=ITEM_TYPE_WORD, relation_types=[RELATION_SYNONYM],
        )
        self.assertEqual(result.status, STATUS_MATCHED)


class TestCompatibilityWithLearnedMeaningResolution(_MatcherTestCase):
    """15. Compatibility with learned meaning resolution (Prompt 418)."""

    def test_meaning_resolver_resolves_an_unknown_expression_via_variation_matcher(self):
        hello = self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"}, confidence=0.9,
            source="taught",
        )
        # "hiya" taught under a DIFFERENT language than the query below,
        # so `resolve()`'s own direct (item_type-unrestricted) lookup
        # cannot find it either - only the relationship graph can.
        hiya = self.items.learn_item("xx", ITEM_TYPE_WORD, "hiya")
        self.rels.relate(hello, hiya, RELATION_SYNONYM)

        resolver = MeaningResolver(self.items, self.rels, variation_matcher=self.matcher)
        result = resolver.resolve("hiya", language="en")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.meanings[0]["key"], "hello")
        self.assertEqual(result.meanings[0]["meaning"], {"gloss": "a greeting"})
        self.assertTrue(result.meanings[0]["matched_via_variation"])
        self.assertIsNotNone(result.variation_match)
        self.assertEqual(result.variation_match["candidate"]["matched_expression"], "hello")

    def test_meaning_resolver_without_a_matcher_is_unchanged(self):
        hello = self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"},
        )
        hiya = self.items.learn_item("en", ITEM_TYPE_WORD, "hiya")
        self.rels.relate(hello, hiya, RELATION_SYNONYM)

        resolver = MeaningResolver(self.items, self.rels)  # no variation_matcher
        result = resolver.resolve("hiya", language="en")
        # "hiya" itself has no stored meaning of its own and the
        # resolver was not given a variation matcher to consult, so this
        # is exactly the pre-existing (Prompt 418) behaviour.
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.meanings[0]["key"], "hiya")
        self.assertFalse(result.meanings[0]["has_stored_meaning"])
        self.assertIsNone(result.variation_match)

    def test_meaning_resolver_ambiguous_variation_is_not_silently_resolved(self):
        joyful = self.items.learn_item("en", ITEM_TYPE_WORD, "joyful", meaning={"gloss": "x"})
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy", meaning={"gloss": "y"})
        glad = self.items.learn_item("xx", ITEM_TYPE_WORD, "glad")
        self.rels.relate(glad, joyful, RELATION_SYNONYM)
        self.rels.relate(glad, happy, RELATION_SYNONYM)

        resolver = MeaningResolver(self.items, self.rels, variation_matcher=self.matcher)
        result = resolver.resolve("glad", language="en")
        # "glad" has no stored meaning of its own, and the variation
        # matcher cannot deterministically pick between "joyful" and
        # "happy" - nothing here should guess one.
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertIsNotNone(result.variation_match)
        self.assertEqual(result.variation_match["status"], STATUS_AMBIGUOUS)


class TestCompatibilityWithLearnedPatternMatching(_MatcherTestCase):
    """16. Compatibility with learned pattern matching (Prompt 421)."""

    def test_pattern_matcher_matches_a_variation_of_a_fixed_learned_pattern(self):
        greeting = self.items.learn_item(
            "en", ITEM_TYPE_PATTERN, "good morning", meaning={"response_action": "greet"},
        )
        # "mornin" taught as a WORD, not a PATTERN, so the ordinary
        # structural pattern loop (which only ever looks at learned
        # PATTERN items) never sees it - only the variation fallback can
        # connect the two.
        casual = self.items.learn_item("en", ITEM_TYPE_WORD, "mornin")
        self.rels.relate(greeting, casual, RELATION_SYNONYM)

        matcher = LearnedPatternMatcher(self.items, variation_matcher=self.matcher)
        result = matcher.match("mornin", language="en")
        self.assertEqual(result.status, PATTERN_STATUS_MATCHED)
        self.assertEqual(result.matched_pattern_text, "good morning")
        self.assertEqual(result.meaning, {"response_action": "greet"})

    def test_pattern_matcher_without_a_matcher_is_unchanged(self):
        self.items.learn_item("en", ITEM_TYPE_PATTERN, "good morning")
        matcher = LearnedPatternMatcher(self.items)  # no variation_matcher
        result = matcher.match("mornin", language="en")
        from language_intelligence.learned_pattern_matching import STATUS_NOT_FOUND as PATTERN_NOT_FOUND
        self.assertEqual(result.status, PATTERN_NOT_FOUND)

    def test_pattern_matcher_does_not_use_variation_matching_for_templated_patterns(self):
        # A pattern WITH variables is out of scope for variation
        # matching (see the module docstring) - only a literal,
        # variable-free candidate pattern is considered.
        templated = self.items.learn_item("en", ITEM_TYPE_PATTERN, "I love {{thing}}")
        fixed = self.items.learn_item("en", ITEM_TYPE_PATTERN, "I adore it")
        self.rels.relate(templated, fixed, RELATION_SYNONYM)

        matcher = LearnedPatternMatcher(self.items, variation_matcher=self.matcher)
        result = matcher.match("I adore it", language="en")
        # "I adore it" is itself an exact learned pattern - matched
        # directly, never via the templated one.
        self.assertEqual(result.status, PATTERN_STATUS_MATCHED)
        self.assertEqual(result.matched_pattern_text, "I adore it")


class TestCompatibilityWithLearnedResponsePatternSelection(_MatcherTestCase):
    """17. Compatibility with learned response-pattern selection (Prompt 434).

    The variation matcher contributes to response-pattern selection
    indirectly: a meaning resolved through a variation (see
    TestCompatibilityWithLearnedMeaningResolution above) is an ordinary
    RESOLVED `MeaningResolutionResult`, exactly the shape
    `response_planning.py` / `language_guidance.py` /
    `learned_response_pattern_selection.py` already consume - nothing
    about those modules changes. This test only confirms the produced
    result stays wire-compatible (deep-copyable, JSON-shaped) end to end
    via Core.
    """

    def test_variation_matched_meaning_is_plain_json_shaped(self):
        hello = self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello",
            meaning={"response_patterns": [{"id": "casual_greeting"}]},
        )
        # A different language than the query below, so this exercises
        # the variation fallback rather than a direct exact match.
        hiya = self.items.learn_item("xx", ITEM_TYPE_WORD, "hiya")
        self.rels.relate(hello, hiya, RELATION_SYNONYM)

        resolver = MeaningResolver(self.items, self.rels, variation_matcher=self.matcher)
        result = resolver.resolve("hiya", language="en")
        as_dict = result.to_dict()
        import json
        json.dumps(as_dict)  # must not raise - plain, JSON-shaped, as everywhere else
        self.assertEqual(
            as_dict["meanings"][0]["meaning"]["response_patterns"][0]["id"], "casual_greeting",
        )


class TestCoreIntegration(unittest.TestCase):
    """Core wires the matcher into the resolver/pattern matcher it owns."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.skills_dir = os.path.join(self._tmpdir.name, "skills")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _core(self):
        return Core(memory_db_path=self.db_path, skill_definitions_dir=self.skills_dir)

    def test_core_exposes_a_variation_matcher_wired_into_the_resolver(self):
        core = self._core()
        self.assertIsInstance(core.expression_variation_matcher, LearnedExpressionVariationMatcher)
        self.assertIs(core.meaning_resolver.variation_matcher, core.expression_variation_matcher)
        self.assertIs(core.pattern_matcher.variation_matcher, core.expression_variation_matcher)

    def test_core_passthrough_matches_a_variation(self):
        core = self._core()
        hello = core.learn_language_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"},
        )
        # Taught as a PATTERN, so an item_type=word request below cannot
        # exact-match "hiya" itself - only the relationship connects it.
        hiya = core.learn_language_item("en", ITEM_TYPE_PATTERN, "hiya")
        core.relate_language_items(hello, hiya, RELATION_SYNONYM)

        result = core.match_learned_expression_variation(
            "hiya", language="en", item_type=ITEM_TYPE_WORD,
        )
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.candidate["matched_expression"], "hello")


if __name__ == "__main__":
    unittest.main()
