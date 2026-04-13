"""Property tests for the agglutinative grammar parser.

_expand_agglutination is pure — no database, no side effects.
These tests verify structural invariants of the parsing.
"""

from hypothesis import given, strategies as st, assume

from rhizome_alkahest.cmd_grammar import _expand_agglutination


# Strategy: simple word-like tokens (no special chars)
word = st.from_regex(r"[a-z][a-z0-9\-]{0,20}", fullmatch=True)

# Strategy: a set of grammar predicates
grammar_set = st.frozensets(word, min_size=0, max_size=10).map(set)


class TestExpandNoSpecialChars:
    """Tokens without : or ~ should pass through unchanged."""

    @given(token=word, grammar=grammar_set)
    def test_plain_token_is_root(self, token, grammar):
        assume(":" not in token and "~" not in token)
        root, chains, annotations = _expand_agglutination(token, grammar)
        assert root == token
        assert chains == []
        assert annotations == []


class TestExpandColonChains:
    """Colon-separated tokens with grammar predicates produce chains."""

    @given(subject=word, predicate=word, obj=word)
    def test_known_predicate_produces_chain(self, subject, predicate, obj):
        assume(predicate != subject and predicate != obj)
        grammar = {predicate}
        token = f"{subject}:{predicate}:{obj}"
        root, chains, annotations = _expand_agglutination(token, grammar)
        assert root == subject
        assert len(chains) == 1
        assert chains[0] == (predicate, obj)

    @given(subject=word, not_pred=word, obj=word)
    def test_unknown_predicate_stays_in_root(self, subject, not_pred, obj):
        grammar = set()  # empty grammar — nothing is a predicate
        token = f"{subject}:{not_pred}:{obj}"
        root, chains, annotations = _expand_agglutination(token, grammar)
        # Should fold back into root since not_pred isn't in grammar
        assert chains == [] or root != subject  # either no chains or root absorbed it

    @given(s=word, p1=word, o1=word, p2=word, o2=word)
    def test_chain_produces_correct_count(self, s, p1, o1, p2, o2):
        assume(len({s, p1, o1, p2, o2}) == 5)  # all distinct
        grammar = {p1, p2}
        token = f"{s}:{p1}:{o1}:{p2}:{o2}"
        root, chains, annotations = _expand_agglutination(token, grammar)
        assert root == s
        assert len(chains) == 2


class TestExpandTildeAnnotations:
    """Tilde-separated parts produce annotations."""

    @given(subject=word, marker=word)
    def test_bare_tilde_produces_annotation(self, subject, marker):
        grammar = set()
        token = f"{subject}~{marker}"
        root, chains, annotations = _expand_agglutination(token, grammar)
        assert root == subject
        assert len(annotations) == 1
        assert annotations[0][0] == marker
        assert annotations[0][1] == []

    @given(subject=word, pred=word, val=word)
    def test_tilde_with_colon_value(self, subject, pred, val):
        grammar = set()
        token = f"{subject}~{pred}:{val}"
        root, chains, annotations = _expand_agglutination(token, grammar)
        assert root == subject
        assert len(annotations) == 1
        assert annotations[0][0] == pred
        assert annotations[0][1] == [val]


class TestAliases:
    """Aliases should resolve in both chains and annotations."""

    @given(subject=word, abbrev=word, full=word, obj=word)
    def test_alias_resolves_in_chain(self, subject, abbrev, full, obj):
        assume(len({subject, abbrev, full, obj}) == 4)
        grammar = {abbrev}  # abbrev is in grammar
        aliases = {abbrev: full}
        token = f"{subject}:{abbrev}:{obj}"
        root, chains, annotations = _expand_agglutination(token, grammar, aliases)
        assert root == subject
        assert len(chains) == 1
        assert chains[0] == (full, obj)  # resolved to full name
