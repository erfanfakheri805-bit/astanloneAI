"""
Knowledge System
=================
Structured representation of what the application knows.

Unlike a plain text log, every knowledge entry is a record with:
    name, kind, description, status, source, version, timestamps

Relationships between entries are stored separately, so the knowledge
base behaves like a small graph rather than a flat list. This is the
substrate the Concept System and Learning System build on top of.
"""

import contextlib
import re
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


_WORD_RE = re.compile(r"[A-Za-z0-9_']+")


def _tokenize(text):
    return {m.group().lower() for m in _WORD_RE.finditer(text or "")}


# Prompt 658: search() returns at most this many rows. The cap is applied AFTER
# relevance ranking (it used to be a SQL LIMIT that ran before ranking and could
# drop the best match).
_SEARCH_MAX_ROWS = 200


def _like_literal(text):
    """Prompt 658: escape LIKE metacharacters (\\ % _) so a query matches its literal
    text only ("_" is a legal query token and used to match any character)."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# Prompt 663: the statuses set_status() can write. "stub" is created only by relate(); other
# stored values (e.g. legacy "deprecated" via direct learn()) are left as they are.
LIFECYCLE_STATUSES = frozenset({"active", "inactive"})


class KnowledgeSystem:
    def __init__(self, memory):
        self.memory = memory

    def learn(self, name, description, kind="concept", source="user", status="active", confidence=None,
              source_text=None, learning_method=None):
        """Create a new knowledge entry, or version-bump an existing one.

        `confidence` of None means "leave it alone if updating, default to
        1.0 if this is a brand-new entry" - re-teaching a concept without
        explicitly restating a confidence shouldn't silently reset it.

        `source_text` (the sentence/instruction this came from) and
        `learning_method` (e.g. "ael" or "natural_language_understanding")
        are provenance metadata, same policy as `confidence`: None means
        "don't overwrite what's already there" on an update, so a stub
        concept auto-created by a bare AEL RELATE doesn't lose real
        provenance recorded later by a fuller TEACH/understanding-engine
        call, and vice versa.
        """
        # Prompt 632: a knowledge record needs a real name. Blank /
        # non-string names used to be persisted as junk rows; they are
        # now rejected before anything is written.
        if not isinstance(name, str) or not name.strip():
            raise ValueError("knowledge name must be a non-empty string")

        existing = self.get(name)
        now = _now()
        if existing:
            new_confidence = existing["confidence"] if confidence is None else confidence
            new_source_text = existing["source_text"] if source_text is None else source_text
            new_learning_method = existing["learning_method"] if learning_method is None else learning_method
            # Prompt 632: repeating an identical learning operation is
            # a no-op - no version bump, no timestamp churn.
            if (existing["description"] == description and existing["kind"] == kind
                    and existing["status"] == status and existing["source"] == source
                    and existing["confidence"] == new_confidence
                    and existing["source_text"] == new_source_text
                    and existing["learning_method"] == new_learning_method):
                return existing
            self.memory._run(
                "UPDATE knowledge SET description = ?, kind = ?, status = ?, source = ?, confidence = ?, "
                "source_text = ?, learning_method = ?, version = version + 1, updated_at = ? WHERE name = ?",
                (description, kind, status, source, new_confidence, new_source_text, new_learning_method,
                 now, name),
            )
            return self.get(name)

        self.memory._run(
            "INSERT INTO knowledge (name, kind, description, status, source, confidence, source_text, "
            "learning_method, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (name, kind, description, status, source, 1.0 if confidence is None else confidence,
             source_text, learning_method, now, now),
        )
        return self.get(name)

    def correct(self, name, description, source=None, confidence=None, source_text=None,
                learning_method=None, status=None):
        """Prompt 633: controlled correction of an EXISTING knowledge
        record. Unlike learn() (exact, case-sensitive identity - it
        would create a competing "python" record next to "Python"),
        this resolves `name` to the one existing logical record - the
        exact-case match if there is one, otherwise the single
        case-insensitive match - and updates that record in place via
        learn(), so version, provenance and confidence keep the
        existing model's semantics (None = keep what is stored).

        Returns the updated record (unchanged and unversioned if the
        correction is identical to what is already stored). Returns
        None, writing nothing, if no such record exists - a correction
        never creates knowledge (use learn() for that). Raises
        ValueError, writing nothing, for a blank name/description or an
        ambiguous case-insensitive match."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("knowledge name must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("corrected description must be a non-empty string")

        existing, resolution = self._resolve_name(name)
        if resolution == "ambiguous":
            raise ValueError(f"ambiguous knowledge name: {name!r} matches "
                             f"{len(self._case_insensitive_matches(name))} records")
        if existing is None:
            return None

        return self.learn(
            existing["name"], description, kind=existing["kind"],
            source=existing["source"] if source is None else source,
            status="active" if status is None else status,
            confidence=confidence, source_text=source_text, learning_method=learning_method,
        )

    def set_status(self, name, status, source=None, source_text=None, learning_method=None):
        """Prompt 663: explicit lifecycle operation - retire ("inactive") or reactivate ("active")
        an EXISTING knowledge record in place.

        Target resolution is the Prompt 637 path (exact case, else the single case-insensitive
        match). Returns the record, or None (nothing written) if no such record exists - a status
        change never creates knowledge. Raises ValueError, writing nothing, for a blank / non-string
        name, an ambiguous name, a status outside LIFECYCLE_STATUSES ("active", "inactive"), or a
        "stub" record (a stub is a placeholder awaiting real teaching; it leaves "stub" only via
        teach()/correct()). Requesting the status a record already has is a true no-op: nothing is
        written (version / updated_at unchanged) and the stored record is returned.

        A real transition is one ordinary mutation through learn(): version + 1, updated_at moves,
        id / name / created_at / description / kind / confidence are untouched, and source /
        source_text / learning_method keep their stored values unless explicitly supplied.
        Retrieval APIs do not filter by status; nothing is deleted."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("knowledge name must be a non-empty string")
        if not isinstance(status, str) or status not in LIFECYCLE_STATUSES:
            raise ValueError(f"lifecycle status must be one of {sorted(LIFECYCLE_STATUSES)}, got {status!r}")
        existing, resolution = self._resolve_name(name)
        if resolution == "ambiguous":
            raise ValueError(f"ambiguous knowledge name: {name!r} matches "
                             f"{len(self._case_insensitive_matches(name))} records")
        if existing is None:
            return None
        if existing["status"] == "stub":
            raise ValueError(f"knowledge record {existing['name']!r} is a stub; teach it before changing its status")
        if existing["status"] == status:
            return existing
        return self.learn(
            existing["name"], existing["description"], kind=existing["kind"],
            source=existing["source"] if source is None else source,
            status=status, confidence=None, source_text=source_text, learning_method=learning_method,
        )

    def get(self, name):
        return self.memory.query_one("SELECT * FROM knowledge WHERE name = ?", (name,))

    def _case_insensitive_matches(self, name):
        return self.memory.query(
            "SELECT * FROM knowledge WHERE LOWER(name) = LOWER(?) ORDER BY name, id", (name,)
        )

    def _resolve_name(self, name):
        """Prompt 637: the one deterministic name-resolution path (read-only).

        Returns (record, status) where status is one of:
          "exact"            - exact-case match (always wins),
          "case_insensitive" - no exact match, exactly one case-insensitive match,
          "ambiguous"        - no exact match, several case-insensitive matches
                               (record is None: nothing is silently chosen),
          "not_found"        - nothing matches (record is None).
        """
        if not isinstance(name, str):
            return None, "not_found"
        exact = self.get(name)
        if exact is not None:
            return exact, "exact"
        matches = self._case_insensitive_matches(name)
        if len(matches) == 1:
            return matches[0], "case_insensitive"
        if len(matches) > 1:
            return None, "ambiguous"
        return None, "not_found"

    def resolve_name(self, name):
        """Read-only structured lookup: {"status", "record", "candidates"}.
        `candidates` lists the matching stored names (sorted) so a caller can
        see WHY a lookup was ambiguous; it is empty unless status is
        "ambiguous". Never writes anything."""
        record, status = self._resolve_name(name)
        candidates = ([m["name"] for m in self._case_insensitive_matches(name)]
                      if status == "ambiguous" else [])
        return {"status": status, "record": record, "candidates": candidates}

    def find_by_name_case_insensitive(self, name):
        """Like get(), but case-insensitive. Used for matching a candidate
        term pulled out of free conversational text (see
        understanding/term_extraction.py) against a name that was TAUGHT
        with different casing - AEL's exact-match `get()` stays
        case-sensitive since RELATE's stub-creation logic depends on it
        treating e.g. 'Python' and 'python' as distinct names.

        Prompt 637: deterministic. An exact-case match wins; otherwise a
        single case-insensitive match is returned; if several records
        differ only by case, None is returned rather than silently
        picking one (use resolve_name() to see the candidates)."""
        return self._resolve_name(name)[0]

    def resolve_current_name(self, name):
        """Prompt 667: read-only name resolution for CURRENT conversational use.

        Same lookup order as resolve_name() (exact case wins, else a single case-insensitive
        match, else ambiguous), but records whose stored status is explicitly "inactive"
        (Prompt 663) are not candidates: they neither win an exact match nor take part in
        (or cause) ambiguity among the active/stub/legacy-status records. Returns
        {"status", "record", "candidates"} where status is "exact" | "case_insensitive" |
        "ambiguous" | "not_found" | "inactive". "inactive" means nothing current matched but at
        least one inactive record did (record is None) - callers treat it like "not_found" for
        answering, but can tell the two apart. resolve_name()/get()/find_by_name_case_insensitive()
        keep their raw contract (they still return inactive rows). Never writes anything."""
        if not isinstance(name, str):
            return {"status": "not_found", "record": None, "candidates": []}
        exact = self.get(name)
        if exact is not None and exact.get("status") != "inactive":
            return {"status": "exact", "record": exact, "candidates": []}
        matches = self._case_insensitive_matches(name)
        current = [m for m in matches if m.get("status") != "inactive"]
        if len(current) == 1:
            return {"status": "case_insensitive", "record": current[0], "candidates": []}
        if len(current) > 1:
            return {"status": "ambiguous", "record": None, "candidates": [m["name"] for m in current]}
        if matches:
            return {"status": "inactive", "record": None, "candidates": []}
        return {"status": "not_found", "record": None, "candidates": []}

    def find_current_by_name_case_insensitive(self, name):
        """Prompt 667: like find_by_name_case_insensitive(), but for current use - an inactive
        record is never returned (see resolve_current_name). Ambiguity among current records still
        returns None rather than picking one."""
        return self.resolve_current_name(name)["record"]

    def search(self, term, limit=20):
        """Deterministic keyword-overlap search across name +
        description (Stage 3 - Relevance Selection).

        A plain "%term%" substring search only matches when the whole
        query phrase happens to appear verbatim - it cannot find a
        concept named "Python" from a query like "Tell me about
        Python and indentation" once other words are involved. This
        instead widens recall (candidate rows are anything sharing at
        least one meaningful word with the query, via one LIKE clause
        per query token, plus the original whole-phrase LIKE for
        literal matches) and then ranks candidates deterministically
        in Python by how many query words they actually share, so the
        most relevant record surfaces first; remaining ties are broken by
        name (Prompt 637), not by timestamp or storage order. No embeddings, no
        semantic model - just explicit, inspectable token overlap.

        Inputs (Prompt 660): `term` is a str or None; `limit` is None (the
        200-row cap) or an int >= 0 (0 -> []). Anything else raises
        TypeError (wrong type) / ValueError (negative limit) before any
        query runs."""
        # Prompt 660: explicit, side-effect-free input validation (before any
        # query). `term` must be a str or None (None/blank/token-less -> []);
        # `limit` must be None (= the 200-row cap) or an int >= 0 (bool is
        # rejected). Previously truthiness/slicing accidents decided these:
        # 0/False/[]/b"" queries returned [] while 5 raised, and a negative
        # limit silently sliced from the end.
        if term is not None and not isinstance(term, str):
            raise TypeError(f"search term must be a str or None, not {type(term).__name__}")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError(f"search limit must be an int or None, not {type(limit).__name__}")
            if limit < 0:
                raise ValueError(f"search limit must be >= 0 or None, got {limit}")

        query_tokens = _tokenize(term)
        if not query_tokens:
            return []

        clauses = []
        params = []
        for token in query_tokens:
            clauses.append("name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\'")
            like = _like_literal(token)
            params.extend([like, like])
        full_phrase_like = _like_literal(term)
        sql = (
            "SELECT * FROM knowledge WHERE (" + ") OR (".join(clauses) + ") "
            "OR name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' ORDER BY name, id"
        )
        params.extend([full_phrase_like, full_phrase_like])
        rows = self.memory.query(sql, tuple(params))

        seen = set()
        candidates = []
        for row in rows:
            if row["name"] in seen:
                continue
            seen.add(row["name"])
            candidates.append(row)

        def _score(row):
            row_tokens = _tokenize(row["name"]) | _tokenize(row.get("description"))
            overlap = len(query_tokens & row_tokens)
            # A literal whole-phrase match on the name itself (the old
            # search()'s only signal) is still the strongest possible
            # relevance signal, so it outranks pure token overlap.
            exact_name_hit = 1 if term.lower() in (row["name"] or "").lower() else 0
            # Prompt 637: ties break on the stored name (then id), never on
            # a timestamp, so identical queries always rank identically.
            return (-exact_name_hit, -overlap, row["name"] or "", row["id"])

        candidates.sort(key=_score)
        # Prompt 658: cap AFTER ranking so the most relevant rows are the ones kept.
        cap = _SEARCH_MAX_ROWS if limit is None else min(limit, _SEARCH_MAX_ROWS)
        return candidates[:cap]

    def all(self, kind=None):
        if kind:
            return self.memory.query("SELECT * FROM knowledge WHERE kind = ? ORDER BY name, id", (kind,))
        return self.memory.query("SELECT * FROM knowledge ORDER BY name, id")

    def _atomic(self):
        """Prompt 645: the store's atomic scope if it has one (a real
        MemorySystem), else a no-op context (stubs/fakes keep working)."""
        fn = getattr(type(self.memory), "_atomic", None)
        return fn(self.memory) if callable(fn) else contextlib.nullcontext()

    def relate(self, from_name, to_name, relation_type, confidence=None, source_type=None,
               source_text=None, learning_method=None):
        with self._atomic():
            return self._relate(from_name, to_name, relation_type, confidence=confidence,
                                source_type=source_type, source_text=source_text,
                                learning_method=learning_method)

    def _relate(self, from_name, to_name, relation_type, confidence=None, source_type=None,
                source_text=None, learning_method=None):
        """Store a directed relationship between two knowledge entries.
        Auto-creates placeholder entries for names that don't exist yet,
        so relationships can be declared before full descriptions exist.

        Idempotent: repeating the exact same (from, to, relation_type)
        triple never creates a duplicate graph edge (still backed by the
        unique index from memory_system._migration_2). A repeat's
        provenance columns (added in _migration_3) are refreshed only
        when a genuinely different *effective* value is supplied -
        `confidence`/`source_type`/`source_text`/`learning_method` each
        keep the existing "None = leave what's stored alone" policy, so
        an omitted argument is never compared as if it were a change.
        Prompt 636: when every effective value already matches what's
        stored, the repeat is a true no-op - no write at all, so
        `updated_at` and every column stay exactly as they were. This
        mirrors the idempotent learn()/teach() behaviour from Prompt
        632. Only when at least one effective value genuinely differs
        does the existing "update appropriate metadata, preserve the
        original information" refresh happen (`updated_at` moves
        forward, `created_at` and any not-newly-supplied metadata are
        left alone); the row is never deleted or replaced wholesale.

        Returns True if a new relationship row was created, False if
        this exact triple already existed (whether refreshed or left
        untouched as a no-op).
        """
        # Prompt 644: validate everything BEFORE any stub is created, so a
        # rejected relate() leaves no orphan stub rows (and no history gap).
        for n in (from_name, to_name):
            if not isinstance(n, str) or not n.strip():
                raise ValueError("knowledge name must be a non-empty string")
        if relation_type is None:
            raise ValueError("relation type must not be None")

        for n in (from_name, to_name):
            if not self.get(n):
                self.learn(n, description=None, kind="concept", source=source_type or "inferred",
                           status="stub", source_text=source_text, learning_method=learning_method)

        now = _now()
        existing = self.memory.query_one(
            "SELECT * FROM relationships WHERE from_name = ? AND to_name = ? AND relation_type = ?",
            (from_name, to_name, relation_type),
        )
        if existing:
            new_confidence = existing["confidence"] if confidence is None else confidence
            new_source_type = existing["source_type"] if source_type is None else source_type
            new_source_text = existing["source_text"] if source_text is None else source_text
            new_learning_method = (
                existing["learning_method"] if learning_method is None else learning_method
            )
            if (existing["confidence"] == new_confidence
                    and existing["source_type"] == new_source_type
                    and existing["source_text"] == new_source_text
                    and existing["learning_method"] == new_learning_method):
                return False  # exact repeat: nothing to write
            self.memory._run(
                "UPDATE relationships SET confidence = ?, source_type = ?, source_text = ?, "
                "learning_method = ?, updated_at = ? WHERE id = ?",
                (new_confidence, new_source_type, new_source_text, new_learning_method,
                 now, existing["id"]),
            )
            return False

        self.memory._run(
            "INSERT INTO relationships (from_name, to_name, relation_type, created_at, updated_at, "
            "confidence, source_type, source_text, learning_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (from_name, to_name, relation_type, now, now, confidence, source_type, source_text,
             learning_method),
        )
        return True

    def relationships_for(self, name):
        outgoing = self.memory.query(
            "SELECT * FROM relationships WHERE from_name = ? ORDER BY relation_type, to_name, id", (name,)
        )
        incoming = self.memory.query(
            "SELECT * FROM relationships WHERE to_name = ? ORDER BY relation_type, from_name, id", (name,)
        )
        return {"outgoing": outgoing, "incoming": incoming}

    def current_relationships_for(self, name):
        """Prompt 668: read-only, same shape as relationships_for(), but only rows usable for
        CURRENT inference - a row is dropped when its other endpoint, or `name` itself, is a
        record whose stored status is explicitly "inactive" (Prompt 663). Endpoints without a
        record, and active / stub / legacy-status endpoints, are kept. relationships_for() and
        the stored rows are unchanged; nothing is written or cached."""
        rels = self.relationships_for(name)
        usable = {}

        def current(n):
            if n not in usable:
                record = self.get(n)
                usable[n] = not (record is not None and record.get("status") == "inactive")
            return usable[n]

        if not current(name):
            return {"outgoing": [], "incoming": []}
        return {
            "outgoing": [r for r in rels["outgoing"] if current(r["to_name"])],
            "incoming": [r for r in rels["incoming"] if current(r["from_name"])],
        }
