"""Duplicate detection: flag records that share a normalised value.

How it works
------------
An object's ``duplicates.rules`` each name one or more attributes. Two records match
under a rule when *all* of the rule's fields are non-empty and equal after
normalisation. Matching is done in SQL on an md5 of the normalised key, backed by a
partial expression index per rule (created by :func:`sync_indexes`), so a check costs
an index lookup however many records exist.

State lives in ``_system.duplicate_flags``: one membership row per
(rule, entity, match key), where the *entity* is ``COALESCE(_draft_of_id, _id)`` — a
golden record and its draft copy are the same entity, so they never match each other
and the id stays stable across draft -> publish. A group of rows sharing a key is only
meaningful while it has two or more entities; smaller groups are deleted.

Records in state ``active`` or ``draft`` that are not soft-deleted take part. Retired
and deleted records do not.

Two ways to keep flags current:

* :func:`refresh_entity` — incremental, called from every write path inside the
  caller's transaction, so flags commit or roll back together with the record.
* :func:`rescan_object` — set-based rebuild for a whole object, used when the rules
  change (see :func:`needs_rescan`) or on demand by an admin.

Known limitation: two uncommitted transactions that write the same new value cannot
see each other, so both can miss the match; a rescan finds it.
"""
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.schema_loader import _TYPE_GROUPS

logger = logging.getLogger(__name__)

# Bump when the normalisation SQL changes meaning, so stored flags are rescanned.
NORMALIZER_VERSION = 1

_AUDIT = "_system.audit_log"
_FLAGS = "_system.duplicate_flags"
_SCANS = "_system.duplicate_scans"
_UNIQUE_MEMBER = "uq_duplicate_flags_member"
_ZERO_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# What started a scan, as written to the audit log.
SCAN_TRIGGERS = {
    "manual": "Rescan requested",
    "startup": "Rules changed, scanned at startup",
    "config_reload": "Rules changed, scanned after config reload",
    "import": "Scan after a large import",
}

# Records that take part in matching, and the entity a record belongs to.
_LIVE = "_deleted_at IS NULL AND _state IN ('active', 'draft')"
_ENTITY = "COALESCE(_draft_of_id, _id)"

# ASCII punctuation/symbols plus common typographic punctuation. Spelled out instead
# of using [[:punct:]] so the result does not depend on the database's locale.
_PUNCT = "[!-/:-@\\[-`{-~‘’‚“”„–—…·•]"

_VALUE_MAX = 200  # characters of the normalised value kept for display

# A bulk import of more rows than this is not checked row by row (about 10-25 ms per
# row); the import commits first and one set-based rescan runs in the background.
BULK_IMPORT_RESCAN_THRESHOLD = 500


# ---------------------------------------------------------------------------
# Rules and SQL expressions
# ---------------------------------------------------------------------------

def rules_of(obj_config: dict | None) -> list[dict]:
    """The object's duplicate rules, tolerant of un-normalised config dicts."""
    dup = (obj_config or {}).get("duplicates") or {}
    rules = []
    for rule in dup.get("rules") or []:
        fields = list(rule["fields"])
        rules.append({
            "name": rule.get("name") or " + ".join(fields),
            "fields": fields,
            "normalize": rule.get("normalize", "text"),
        })
    return rules


def _field_sql(attr_key: str, attr: dict, normalize: str) -> str:
    """SQL for one field's normalised value; NULL when the field is empty."""
    reference = attr.get("reference")
    col = f'"{attr_key}_id"' if reference else f'"{attr_key}"'
    attr_type = attr.get("type", "string")

    if not reference and _TYPE_GROUPS.get(attr_type) == "text":
        if normalize == "digits":
            return f"nullif(regexp_replace({col}, '[^0-9]', '', 'g'), '')"
        return (
            "nullif(btrim(regexp_replace("
            f"regexp_replace(lower({col}), '{_PUNCT}', ' ', 'g'), '\\s+', ' ', 'g')), '')"
        )
    # Non-text values are compared exactly. Every expression here is IMMUTABLE, which
    # an index expression requires (timestamp::text, for one, is not).
    if reference or attr_type in ("integer", "boolean"):
        return f"{col}::text"
    if attr_type == "numeric":
        return f"trim_scale({col})::text"
    if attr_type == "date":
        return f"extract(epoch from {col})::text"
    return f"{col}::text"


def _field_sqls(obj_config: dict, rule: dict) -> list[str]:
    attrs = obj_config.get("attributes") or {}
    return [_field_sql(f, attrs[f], rule["normalize"]) for f in rule["fields"]]


def key_sql(obj_config: dict, rule: dict) -> str:
    """SQL for the rule's match key: an md5, or NULL unless every field has a value."""
    parts = _field_sqls(obj_config, rule)
    if len(parts) == 1:
        return f"md5({parts[0]})"  # md5(NULL) is NULL
    all_present = " AND ".join(f"{p} IS NOT NULL" for p in parts)
    joined = " || chr(31) || ".join(parts)
    return f"CASE WHEN {all_present} THEN md5({joined}) END"


def _value_sql(obj_config: dict, rule: dict) -> str:
    """SQL for the human-readable normalised value shown next to a flag."""
    separator = " || ' | ' || "
    return f"left({separator.join(_field_sqls(obj_config, rule))}, {_VALUE_MAX})"


def _qualified(schema: str, obj: str) -> str:
    return f'"{schema}"."{obj}"'


def _index_name(schema: str, obj: str, discriminator: str) -> str:
    """Short deterministic index name (identifiers are limited to 63 characters)."""
    digest = hashlib.md5(  # nosec B324 — naming only, not security
        f"{schema}.{obj}.{discriminator}".encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return f"ix_dup_{digest}"


def rules_fingerprint(obj_config: dict | None) -> str:
    """Stable fingerprint of what the object's rules mean in SQL ('' without rules)."""
    rules = rules_of(obj_config)
    if not rules:
        return ""
    spec = {
        "version": NORMALIZER_VERSION,
        "rules": [{"name": r["name"], "key": key_sql(obj_config, r)} for r in rules],
    }
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Indexes (created by TableManager.sync_schema)
# ---------------------------------------------------------------------------

def sync_indexes(engine, config: dict) -> None:
    """Create the expression index per rule and drop indexes of removed/changed rules."""
    for schema, schema_body in (config.get("schemas") or {}).items():
        for obj, obj_config in (schema_body.get("objects") or {}).items():
            tbl = _qualified(schema, obj)
            desired: dict[str, str] = {}
            rules = rules_of(obj_config)
            for rule in rules:
                key = key_sql(obj_config, rule)
                name = _index_name(schema, obj, f"{rule['name']}.{key}")
                desired[name] = (
                    f'CREATE INDEX IF NOT EXISTS "{name}" ON {tbl} (({key})) WHERE {_LIVE}'
                )
            if rules:
                # Entity lookups find an entity's draft copy through _draft_of_id.
                name = _index_name(schema, obj, "draft_of")
                desired[name] = (
                    f'CREATE INDEX IF NOT EXISTS "{name}" ON {tbl} (_draft_of_id) '
                    "WHERE _draft_of_id IS NOT NULL"
                )

            with engine.begin() as conn:
                existing = {
                    row[0] for row in conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = :s AND tablename = :t "
                            "AND indexname LIKE 'ix\\_dup\\_%'"
                        ),
                        {"s": schema, "t": obj},
                    )
                }
                for stale in existing - set(desired):
                    conn.execute(text(f'DROP INDEX IF EXISTS "{schema}"."{stale}"'))
                for ddl in desired.values():
                    conn.execute(text(ddl))  # nosec B608 — identifiers are config-validated


# ---------------------------------------------------------------------------
# Incremental maintenance (called from the write paths)
# ---------------------------------------------------------------------------

def entity_id_of(record: dict) -> uuid.UUID:
    """The entity a record row belongs to: its golden record's id for a draft copy."""
    return record.get("_draft_of_id") or record["_id"]


def refresh_entity(db, schema: str, obj: str, obj_config: dict | None, entity_id) -> list[dict]:
    """Bring the flags for one entity up to date; call after any change to its data.

    Runs in the caller's transaction (``db`` is a SQLAlchemy ``Session``) so the flags
    commit or roll back together with the record. Also call it after a delete or retire,
    which removes the entity from matching. Returns the groups the entity is flagged in:
    ``[{"rule": str, "value": str, "matches": [entity ids of the other members]}]``.
    """
    rules = rules_of(obj_config)
    if not rules:
        return []

    entity_id = uuid.UUID(str(entity_id))
    now = datetime.now(timezone.utc)
    tbl = _qualified(schema, obj)
    flagged: list[dict] = []

    for rule in rules:
        key = key_sql(obj_config, rule)
        val = _value_sql(obj_config, rule)
        scope = {"s": schema, "o": obj, "r": rule["name"]}

        current = {
            row[0]: row[1] for row in db.execute(
                text(
                    f"SELECT h, min(v) FROM (SELECT {key} AS h, {val} AS v FROM {tbl} "  # nosec B608
                    f"WHERE (_id = :e OR _draft_of_id = :e) AND {_LIVE}) x "
                    "WHERE h IS NOT NULL GROUP BY h"
                ),
                {"e": entity_id},
            )
        }
        stored = {
            row[0] for row in db.execute(
                text(
                    f"SELECT match_hash FROM {_FLAGS} WHERE schema_name = :s "
                    "AND object_name = :o AND rule_name = :r AND entity_id = :e"
                ),
                {**scope, "e": entity_id},
            )
        }

        # Keys the entity no longer has: drop its rows (a dismissal dies with its key).
        stale = stored - set(current)
        if stale:
            db.execute(
                text(
                    f"DELETE FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
                    "AND rule_name = :r AND entity_id = :e AND match_hash = ANY(:hs)"
                ),
                {**scope, "e": entity_id, "hs": list(stale)},
            )

        for match_hash in stale:
            _regroup(db, tbl, scope, key, val, match_hash, now)
        for match_hash, value in current.items():
            members = _regroup(db, tbl, scope, key, val, match_hash, now)
            if len(members) >= 2:
                flagged.append({
                    "rule": rule["name"],
                    "value": value,
                    "matches": [m for m in members if m != entity_id],
                })
    return flagged


def response_fields(flagged: list[dict]) -> dict:
    """The part of a create/update response that tells the caller about new matches.

    Empty when nothing matched, so existing clients see no change.
    """
    if not flagged:
        return {}
    return {"possible_duplicates": [
        {"rule": f["rule"], "value": f["value"], "matches": [str(m) for m in f["matches"]]}
        for f in flagged
    ]}


def _regroup(db, tbl: str, scope: dict, key: str, val: str, match_hash: str, now) -> list:
    """Reconcile the flag rows of one group (rule + match key); return its members."""
    rows = db.execute(
        text(
            f"SELECT {_ENTITY} AS e, min({val}) AS v FROM {tbl} "  # nosec B608
            f"WHERE {key} = :h AND {_LIVE} GROUP BY {_ENTITY}"
        ),
        {"h": match_hash},
    ).all()
    members = [r[0] for r in rows]
    value = rows[0][1] if rows else None

    existing = {
        row[0]: row[1] for row in db.execute(
            text(
                f"SELECT entity_id, status FROM {_FLAGS} WHERE schema_name = :s "
                "AND object_name = :o AND rule_name = :r AND match_hash = :h"
            ),
            {**scope, "h": match_hash},
        )
    }

    if len(members) < 2:
        # A lone record is not a duplicate of anything.
        if existing:
            db.execute(
                text(
                    f"DELETE FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
                    "AND rule_name = :r AND match_hash = :h"
                ),
                {**scope, "h": match_hash},
            )
        return members

    gone = set(existing) - set(members)
    if gone:
        db.execute(
            text(
                f"DELETE FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
                "AND rule_name = :r AND match_hash = :h AND entity_id = ANY(:es)"
            ),
            {**scope, "h": match_hash, "es": list(gone)},
        )

    new = [m for m in members if m not in existing]
    for member in new:
        db.execute(
            text(
                f"INSERT INTO {_FLAGS} (id, schema_name, object_name, rule_name, entity_id, "
                "match_hash, match_value, status, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :s, :o, :r, :e, :h, :v, 'open', :now, :now) "
                f"ON CONFLICT ON CONSTRAINT {_UNIQUE_MEMBER} DO NOTHING"
            ),
            {**scope, "e": member, "h": match_hash, "v": value, "now": now},
        )
    if new and "dismissed" in existing.values():
        # A newcomer was never reviewed against the members dismissed earlier.
        db.execute(
            text(
                f"UPDATE {_FLAGS} SET status = 'open', dismissed_by = NULL, "
                "dismissed_at = NULL, dismiss_reason = NULL, updated_at = :now "
                "WHERE schema_name = :s AND object_name = :o AND rule_name = :r "
                "AND match_hash = :h AND status = 'dismissed'"
            ),
            {**scope, "h": match_hash, "now": now},
        )
    return members


# ---------------------------------------------------------------------------
# Full rescan
# ---------------------------------------------------------------------------

def _scan_row_needs_rescan(row, obj_config: dict | None) -> bool:
    """`row` is (rules_fingerprint, rescan_requested_at) of duplicate_scans, or None."""
    fingerprint, requested_at = (row[0], row[1]) if row else ("", None)
    return (fingerprint or "") != rules_fingerprint(obj_config) or requested_at is not None


def needs_rescan(engine, schema: str, obj: str, obj_config: dict | None) -> bool:
    """True when the object's rules differ from the ones last scanned, or a rescan was
    requested (a big import, or a scan that was interrupted before it could finish)."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT rules_fingerprint, rescan_requested_at FROM {_SCANS} "
                "WHERE schema_name = :s AND object_name = :o"
            ),
            {"s": schema, "o": obj},
        ).first()
    return _scan_row_needs_rescan(row, obj_config)


def request_rescan(db, schema: str, obj: str) -> None:
    """Record, in the caller's transaction, that the object must be rescanned.

    Used by a big import: it commits its rows without checking them, so until the
    follow-up rescan finishes the flags are incomplete. The request is stored with the
    rows, so if the server dies before the rescan has run it is still there at the next
    start. Without a duplicate_scans row nothing needs storing: an object with rules that
    was never scanned is already reported as needing a rescan.
    """
    db.execute(
        text(
            f"UPDATE {_SCANS} SET rescan_requested_at = clock_timestamp() "
            "WHERE schema_name = :s AND object_name = :o"
        ),
        {"s": schema, "o": obj},
    )


def _rescan_lock_key(schema: str, obj: str) -> str:
    return f"duplicate-rescan:{schema}.{obj}"


def scan_running(engine, schema: str, obj: str) -> bool:
    """True while a rescan of the object holds its advisory lock.

    Derived from the lock itself rather than a stored flag, so a crashed or killed
    scan can never leave the object stuck in a "running" state.
    """
    with engine.connect() as conn:
        return bool(conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                "AND granted AND objsubid = 1 "
                "AND ((classid::bigint << 32) | objid::bigint) = hashtext(:k)::bigint)"
            ),
            {"k": _rescan_lock_key(schema, obj)},
        ).scalar())


def scan_info(engine, schema: str, obj: str, obj_config: dict | None) -> dict:
    """What the last scan of an object found out, and whether the rules changed since."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rules_fingerprint, rescan_requested_at, record_count, duration_ms, "
                f"scanned_at FROM {_SCANS} WHERE schema_name = :s AND object_name = :o"
            ),
            {"s": schema, "o": obj},
        ).first()
    return {
        "scanned_at": row[4] if row else None,
        "record_count": row[2] if row else None,
        "duration_ms": row[3] if row else None,
        "needs_rescan": _scan_row_needs_rescan(row, obj_config),
    }


def count_live_records(engine, schema: str, obj: str) -> int:
    """Records that take part in matching (active/draft, not deleted)."""
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {_qualified(schema, obj)} WHERE {_LIVE}")  # nosec B608
        ).scalar() or 0


def rescan_object(
    engine, schema: str, obj: str, obj_config: dict | None, only_if_needed: bool = False,
    trigger: str = "manual", user_name: str | None = None,
) -> dict:
    """Rebuild every flag of one object from its data, set-based and in one transaction.

    Dismissals survive when the same (entity, key) is still in a group; a dismissed
    member is reopened when the rebuild adds a new member to its group. Returns
    ``{"record_count", "duration_ms", "groups"}``.

    Being one transaction, a scan that is interrupted (server stopped or killed) leaves
    no trace: the flags and the stored fingerprint stay as they were, so the object still
    reads as needing a rescan. With ``only_if_needed`` the scan re-checks that after it
    got the lock and returns ``{"skipped": True}`` if a concurrent scan already did the
    work (several workers start up at the same time).

    A completed scan writes one ``DUPLICATE_SCAN`` audit entry, in the same transaction,
    saying what ``trigger`` started it (see ``SCAN_TRIGGERS``), who (``user_name``), how
    long it took and what it found. Its timestamp is the end; the start is that minus the
    duration. A scan that never completes writes nothing.
    """
    started = time.monotonic()
    rules = rules_of(obj_config)
    tbl = _qualified(schema, obj)
    now = datetime.now(timezone.utc)
    groups = 0

    with engine.begin() as conn:
        # One rescan per object at a time (two overlapping imports each schedule one).
        # A single transaction-level lock cannot deadlock, unlike per-key locks.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": _rescan_lock_key(schema, obj)},
        )
        # Database clock, taken before any data is read: a rescan requested after this
        # moment is not covered by this scan and must survive it.
        began = conn.execute(text("SELECT clock_timestamp()")).scalar()

        if only_if_needed:
            row = conn.execute(
                text(
                    f"SELECT rules_fingerprint, rescan_requested_at FROM {_SCANS} "
                    "WHERE schema_name = :s AND object_name = :o"
                ),
                {"s": schema, "o": obj},
            ).first()
            if not _scan_row_needs_rescan(row, obj_config):
                return {"skipped": True}

        # Flags of rules that no longer exist.
        conn.execute(
            text(
                f"DELETE FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
                "AND NOT (rule_name = ANY(:names))"
            ),
            {"s": schema, "o": obj, "names": [r["name"] for r in rules]},
        )

        for rule in rules:
            key = key_sql(obj_config, rule)
            val = _value_sql(obj_config, rule)
            scope = {"s": schema, "o": obj, "r": rule["name"], "now": now}

            conn.execute(text("DROP TABLE IF EXISTS _dup_desired"))
            conn.execute(text(
                "CREATE TEMP TABLE _dup_desired ON COMMIT DROP AS "  # nosec B608
                f"WITH base AS (SELECT {key} AS h, {_ENTITY} AS e, {val} AS v "
                f"FROM {tbl} WHERE {_LIVE}), "
                "dedup AS (SELECT h, e, min(v) AS v FROM base WHERE h IS NOT NULL "
                "GROUP BY h, e), "
                "grp AS (SELECT h FROM dedup GROUP BY h HAVING count(*) > 1) "
                "SELECT d.h AS match_hash, d.e AS entity_id, d.v AS match_value "
                "FROM dedup d JOIN grp g ON g.h = d.h"
            ))
            groups += conn.execute(
                text("SELECT count(DISTINCT match_hash) FROM _dup_desired")
            ).scalar() or 0

            conn.execute(
                text(
                    f"DELETE FROM {_FLAGS} f WHERE f.schema_name = :s AND f.object_name = :o "
                    "AND f.rule_name = :r AND NOT EXISTS (SELECT 1 FROM _dup_desired d "
                    "WHERE d.match_hash = f.match_hash AND d.entity_id = f.entity_id)"
                ),
                scope,
            )
            conn.execute(
                text(
                    f"WITH ins AS (INSERT INTO {_FLAGS} (id, schema_name, object_name, "
                    "rule_name, entity_id, match_hash, match_value, status, created_at, "
                    "updated_at) SELECT gen_random_uuid(), :s, :o, :r, d.entity_id, "
                    "d.match_hash, d.match_value, 'open', :now, :now FROM _dup_desired d "
                    f"ON CONFLICT ON CONSTRAINT {_UNIQUE_MEMBER} DO NOTHING "
                    "RETURNING match_hash) "
                    f"UPDATE {_FLAGS} SET status = 'open', dismissed_by = NULL, "
                    "dismissed_at = NULL, dismiss_reason = NULL, updated_at = :now "
                    "WHERE schema_name = :s AND object_name = :o AND rule_name = :r "
                    "AND status = 'dismissed' AND match_hash IN (SELECT match_hash FROM ins)"
                ),
                scope,
            )

        record_count = conn.execute(
            text(f"SELECT count(*) FROM {tbl} WHERE {_LIVE}")  # nosec B608
        ).scalar() or 0
        duration_ms = int((time.monotonic() - started) * 1000)
        conn.execute(
            text(
                f"INSERT INTO {_SCANS} (schema_name, object_name, rules_fingerprint, "
                "record_count, duration_ms, scanned_at) "
                "VALUES (:s, :o, :fp, :n, :ms, :now) "
                "ON CONFLICT (schema_name, object_name) DO UPDATE SET "
                "rules_fingerprint = :fp, record_count = :n, duration_ms = :ms, "
                "scanned_at = :now, rescan_requested_at = CASE "
                f"WHEN {_SCANS}.rescan_requested_at <= :began THEN NULL "
                f"ELSE {_SCANS}.rescan_requested_at END"
            ),
            {
                "s": schema, "o": obj, "fp": rules_fingerprint(obj_config),
                "n": record_count, "ms": duration_ms, "now": now, "began": began,
            },
        )
        conn.execute(
            text(
                f"INSERT INTO {_AUDIT} (id, timestamp, user_name, schema_name, object_name, "
                "record_id, action, new_values, reason) VALUES (gen_random_uuid(), "
                "clock_timestamp(), :user, '_system', 'duplicate_scan', :rid, "
                "'DUPLICATE_SCAN', CAST(:values AS json), :reason)"
            ),
            {
                "user": user_name or "system", "rid": _ZERO_UUID,
                "values": json.dumps({
                    "schema": schema, "object": obj, "trigger": trigger,
                    "record_count": record_count, "groups": groups,
                    "duration_ms": duration_ms,
                }),
                "reason": (
                    f"{SCAN_TRIGGERS.get(trigger, trigger)}: {schema}.{obj} - "
                    f"{record_count} records, {groups} groups, {duration_ms} ms"
                ),
            },
        )

    logger.info(
        "Duplicate scan of %s.%s (%s): %d records, %d groups, %d ms",
        schema, obj, trigger, record_count, groups, duration_ms,
    )
    return {"record_count": record_count, "duration_ms": duration_ms, "groups": groups}


def rescan_in_background(
    engine, schema: str, obj: str, obj_config: dict | None,
    trigger: str = "manual", user_name: str | None = None,
) -> None:
    """Run :func:`rescan_object` as a background task: failures are logged, never raised."""
    try:
        rescan_object(engine, schema, obj, obj_config, trigger=trigger, user_name=user_name)
    except Exception:
        logger.exception("Background duplicate scan of %s.%s failed", schema, obj)


def pending_rescans(engine, config: dict) -> list[tuple[str, str, dict]]:
    """(schema, object, object config) of every object that needs a rescan."""
    todo = []
    for schema, schema_body in (config.get("schemas") or {}).items():
        for obj, obj_config in (schema_body.get("objects") or {}).items():
            if needs_rescan(engine, schema, obj, obj_config):
                todo.append((schema, obj, obj_config))
    return todo


def start_auto_rescan(
    engine, config: dict, trigger: str = "startup",
) -> threading.Thread | None:
    """After a config load: rescan, in the background, whatever needs it.

    That is every object whose rules changed since it was last scanned (including the
    first time rules are added), plus any whose scan was requested but never finished.
    Objects that need nothing cost nothing, so this is cheap on every start. With
    ``duplicates.rescan: manual`` nothing is started; the outstanding objects are only
    logged and the Duplicates page offers the Rescan button. Returns the thread, if any.
    """
    mode = (config.get("duplicates") or {}).get("rescan", "on_rule_change")
    try:
        todo = pending_rescans(engine, config)
    except Exception:
        logger.exception("Could not check which objects need a duplicate rescan")
        return None
    if not todo:
        return None

    names = ", ".join(f"{schema}.{obj}" for schema, obj, _ in todo)
    if mode == "manual":
        logger.warning(
            "Duplicate flags may be out of date for: %s. duplicates.rescan is 'manual', so "
            "run a rescan from the Duplicates page.", names,
        )
        return None

    logger.info("Duplicate rescan starting in the background for: %s", names)
    thread = threading.Thread(
        target=_auto_rescan, args=(engine, todo, trigger), name="duplicate-rescan",
        daemon=True
    )
    thread.start()
    return thread


def _auto_rescan(engine, todo: list[tuple[str, str, dict]], trigger: str) -> None:
    for schema, obj, obj_config in todo:
        try:
            rescan_object(
                engine, schema, obj, obj_config, only_if_needed=True, trigger=trigger
            )
        except Exception:
            logger.exception("Automatic duplicate scan of %s.%s failed", schema, obj)
