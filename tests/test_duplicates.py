"""Duplicate detection core (app/core/duplicates.py) against a real PostgreSQL.

Uses a dedicated schema and its own TableManager — not the session-scoped `client`
fixture's shared state, which must never be re-synced (see CLAUDE.md).
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core import duplicates as dup
from app.core.table_manager import TableManager

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping integration tests",
)

SCHEMA = "dup_core_test"

RULES = [
    {"name": "Same email", "fields": ["email"], "normalize": "text"},
    {"name": "Same phone", "fields": ["phone"], "normalize": "digits"},
    {"name": "Same name and country", "fields": ["last_name", "country"], "normalize": "text"},
    {"name": "Same birth date and name", "fields": ["birth_date", "last_name"]},
    {"name": "Same score and amount", "fields": ["score", "amount"]},
    {"name": "Same employer and name", "fields": ["employer", "last_name"]},
]


def _config(rules=RULES) -> dict:
    return {"schemas": {SCHEMA: {"objects": {
        "company": {
            "name": "Company", "parent": None,
            "attributes": {"name": {"name": "Name", "type": "string"}},
        },
        "contact": {
            "name": "Contact", "parent": None,
            "attributes": {
                "email": {"name": "Email", "type": "email"},
                "phone": {"name": "Phone", "type": "string"},
                "last_name": {"name": "Last name", "type": "string"},
                "country": {"name": "Country", "type": "string"},
                "birth_date": {"name": "Birth date", "type": "date"},
                "score": {"name": "Score", "type": "integer"},
                "amount": {"name": "Amount", "type": "numeric"},
                "employer": {"name": "Employer", "type": "string", "reference": "company"},
            },
            "duplicates": {"dismissed_by": "editor", "rules": rules},
        },
    }}}}


@pytest.fixture
def env():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    tm = TableManager(engine)
    config = _config()
    tm.sync_schema(config)
    obj_config = config["schemas"][SCHEMA]["objects"]["contact"]
    yield engine, tm, obj_config
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        conn.execute(text("DELETE FROM _system.duplicate_flags WHERE schema_name = :s"),
                     {"s": SCHEMA})
        conn.execute(text("DELETE FROM _system.duplicate_scans WHERE schema_name = :s"),
                     {"s": SCHEMA})
        conn.execute(text(
            "DELETE FROM _system.audit_log WHERE action = 'DUPLICATE_SCAN' "
            "AND new_values->>'schema' = :s"), {"s": SCHEMA})
        conn.commit()
    engine.dispose()


class Contacts:
    """Tiny driver: insert/modify contact rows and run refresh_entity like a write path."""

    def __init__(self, engine, tm, obj_config):
        self.engine, self.tm, self.obj_config = engine, tm, obj_config
        self.table = tm.get_table(SCHEMA, "contact")

    def add(self, state="active", draft_of=None, refresh=True, **values) -> uuid.UUID:
        rid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        with Session(self.engine) as db:
            db.execute(self.table.insert().values(
                _id=rid, _state=state, _draft_of_id=draft_of, _created_at=now,
                _updated_at=now, **values))
            if refresh:
                dup.refresh_entity(db, SCHEMA, "contact", self.obj_config,
                                   draft_of or rid)
            db.commit()
        return rid

    def update(self, rid, entity=None, **values):
        with Session(self.engine) as db:
            db.execute(self.table.update().where(self.table.c._id == rid).values(**values))
            dup.refresh_entity(db, SCHEMA, "contact", self.obj_config, entity or rid)
            db.commit()

    def refresh(self, entity):
        with Session(self.engine) as db:
            result = dup.refresh_entity(db, SCHEMA, "contact", self.obj_config, entity)
            db.commit()
        return result

    def flags(self, rule=None, status=None) -> set:
        """{(rule, entity_id)} currently flagged."""
        sql = ("SELECT rule_name, entity_id FROM _system.duplicate_flags "
               "WHERE schema_name = :s AND object_name = 'contact'")
        params = {"s": SCHEMA}
        if rule:
            sql += " AND rule_name = :r"
            params["r"] = rule
        if status:
            sql += " AND status = :st"
            params["st"] = status
        with self.engine.connect() as conn:
            return {(r[0], r[1]) for r in conn.execute(text(sql), params)}

    def entities(self, rule) -> set:
        return {e for _, e in self.flags(rule)}


@pytest.fixture
def contacts(env):
    return Contacts(*env)


EMAIL = "Same email"


def test_exact_and_normalised_values_match(contacts):
    a = contacts.add(email="Anna@X.com")
    b = contacts.add(email="  anna@x.COM ")
    contacts.add(email="other@x.com")
    assert contacts.entities(EMAIL) == {a, b}


def test_punctuation_and_spacing_are_normalised_but_structure_is_kept(contacts):
    a = contacts.add(last_name="O'Brien,   Pat", country="IE")
    b = contacts.add(last_name="o brien pat", country="ie")
    # a@bc.com and ab@c.com must NOT collapse to the same key
    contacts.add(email="a@bc.com")
    contacts.add(email="ab@c.com")
    assert contacts.entities("Same name and country") == {a, b}
    assert contacts.entities(EMAIL) == set()


def test_empty_values_never_match(contacts):
    contacts.add()
    contacts.add()
    contacts.add(email="", phone="", last_name="  ", country="--")
    contacts.add(email="", phone="", last_name="  ", country="--")
    assert contacts.flags() == set()


def test_digits_normalisation(contacts):
    a = contacts.add(phone="070-123 45 67")
    b = contacts.add(phone="(0701) 234567")
    contacts.add(phone="070 123 45 68")
    contacts.add(phone="n/a")  # no digits at all: empty, never matches
    contacts.add(phone="none")
    assert contacts.entities("Same phone") == {a, b}


def test_composite_rule_needs_every_field_to_match(contacts):
    a = contacts.add(last_name="Berg", country="SE")
    b = contacts.add(last_name="BERG", country="se")
    contacts.add(last_name="Berg", country="NO")  # different country
    contacts.add(last_name="Berg")                # country missing
    assert contacts.entities("Same name and country") == {a, b}


def test_non_text_values_are_compared_exactly(contacts):
    d1, d2 = datetime(1990, 5, 17), datetime(1990, 5, 18)
    a = contacts.add(birth_date=d1, last_name="Lind")
    b = contacts.add(birth_date=d1, last_name="lind")
    contacts.add(birth_date=d2, last_name="Lind")
    assert contacts.entities("Same birth date and name") == {a, b}

    c = contacts.add(score=7, amount="1.0")
    e = contacts.add(score=7, amount="1.00")   # numeric scale must not matter
    contacts.add(score=8, amount="1.0")
    assert contacts.entities("Same score and amount") == {c, e}


def test_reference_fields_compare_the_referenced_record(contacts, env):
    engine, tm, _ = env
    company = tm.get_table(SCHEMA, "company")
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for cid in (c1, c2):
            conn.execute(company.insert().values(
                _id=cid, _state="active", _created_at=now, _updated_at=now))
    a = contacts.add(employer_id=c1, last_name="Nord")
    b = contacts.add(employer_id=c1, last_name="nord")
    contacts.add(employer_id=c2, last_name="Nord")
    assert contacts.entities("Same employer and name") == {a, b}


def test_a_draft_copy_never_matches_its_own_golden_record(contacts):
    golden = contacts.add(email="a@x.com")
    contacts.add(state="draft", draft_of=golden, email="a@x.com")
    assert contacts.flags() == set()


def test_a_new_draft_matches_an_active_record_and_vice_versa(contacts):
    active = contacts.add(email="a@x.com")
    draft = contacts.add(state="draft", email="A@x.com")
    assert contacts.entities(EMAIL) == {active, draft}


def test_draft_edit_moves_the_entity_between_groups_and_publish_keeps_it(contacts):
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="b@x.com")
    draft = contacts.add(state="draft", draft_of=a, email="b@x.com")
    # The draft makes entity A match B; A's golden value still matches nobody.
    assert contacts.entities(EMAIL) == {a, b}

    # Publish: golden takes the draft's value, the draft is soft-deleted.
    now = datetime.now(timezone.utc)
    with Session(contacts.engine) as db:
        t = contacts.table
        db.execute(t.update().where(t.c._id == a).values(email="b@x.com"))
        db.execute(t.update().where(t.c._id == draft).values(_deleted_at=now))
        dup.refresh_entity(db, SCHEMA, "contact", contacts.obj_config, a)
        db.commit()
    assert contacts.entities(EMAIL) == {a, b}
    with contacts.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT count(*) FROM _system.duplicate_flags WHERE schema_name = :s"),
            {"s": SCHEMA}).scalar()
    assert rows == 2  # no stale row for the old key


def test_delete_and_retire_dissolve_groups(contacts):
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="a@x.com")
    c = contacts.add(email="a@x.com")
    assert contacts.entities(EMAIL) == {a, b, c}

    contacts.update(c, _deleted_at=datetime.now(timezone.utc))
    assert contacts.entities(EMAIL) == {a, b}

    contacts.update(b, _state="retired")
    assert contacts.flags() == set()   # a is alone again


def test_refresh_reports_the_groups_an_entity_is_in(contacts):
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="a@x.com", refresh=False)
    result = contacts.refresh(b)
    assert len(result) == 1
    assert result[0]["rule"] == EMAIL
    assert result[0]["value"] == "a x com"
    assert result[0]["matches"] == [a]
    assert contacts.refresh(a) == [{"rule": EMAIL, "value": "a x com", "matches": [b]}]


def _dismiss(contacts, entity, rule=EMAIL):
    with contacts.engine.begin() as conn:
        conn.execute(text(
            "UPDATE _system.duplicate_flags SET status = 'dismissed', dismissed_by = 'u' "
            "WHERE schema_name = :s AND rule_name = :r AND entity_id = :e"),
            {"s": SCHEMA, "r": rule, "e": entity})


def test_dismissal_survives_unrelated_edits(contacts):
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="a@x.com")
    _dismiss(contacts, b)
    contacts.update(b, country="SE")
    contacts.update(a, country="NO")
    assert contacts.flags(EMAIL, status="dismissed") == {(EMAIL, b)}
    assert contacts.flags(EMAIL, status="open") == {(EMAIL, a)}


def test_dismissal_is_reopened_when_the_value_changes(contacts):
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="a@x.com")
    _dismiss(contacts, b)
    c = contacts.add(email="z@x.com")
    # b changes to a value shared with c: new key, so a fresh open flag, not dismissed
    contacts.update(b, email="z@x.com")
    assert contacts.flags(EMAIL, status="dismissed") == set()
    assert contacts.flags(EMAIL, status="open") == {(EMAIL, b), (EMAIL, c)}
    assert a not in contacts.entities(EMAIL)


def test_dismissed_members_are_reopened_when_a_newcomer_joins(contacts):
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="a@x.com")
    _dismiss(contacts, a)
    _dismiss(contacts, b)
    c = contacts.add(email="a@x.com")
    assert contacts.flags(EMAIL, status="dismissed") == set()
    assert contacts.entities(EMAIL) == {a, b, c}


def test_rescan_matches_incremental_state_and_finds_unrefreshed_records(env):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    a = contacts.add(email="a@x.com")
    b = contacts.add(email="A@x.com")
    # Written without a refresh, as if the data predates the rules
    c = contacts.add(email="a@x.com ", refresh=False)
    p = contacts.add(phone="0701", refresh=False)
    q = contacts.add(phone="0-70-1", refresh=False)
    assert contacts.entities(EMAIL) == {a, b}
    _dismiss(contacts, a)

    result = dup.rescan_object(engine, SCHEMA, "contact", obj_config)

    assert contacts.entities(EMAIL) == {a, b, c}
    assert contacts.entities("Same phone") == {p, q}
    # c is a newcomer to the group, so the earlier dismissal of a is reopened
    assert contacts.flags(EMAIL, status="dismissed") == set()
    assert result["record_count"] == 5 and result["groups"] == 2

    # A second scan changes nothing, and a dismissal now survives it
    _dismiss(contacts, a)
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert contacts.flags(EMAIL, status="dismissed") == {(EMAIL, a)}


def test_rescan_drops_flags_of_removed_rules_and_stale_rows(env):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    contacts.add(email="a@x.com")
    contacts.add(email="a@x.com")
    contacts.add(phone="1")
    contacts.add(phone="1")
    assert contacts.flags()

    only_email = {**obj_config, "duplicates": {"rules": [RULES[0]]}}
    dup.rescan_object(engine, SCHEMA, "contact", only_email)
    assert {r for r, _ in contacts.flags()} == {EMAIL}

    no_rules = {**obj_config, "duplicates": {"rules": []}}
    dup.rescan_object(engine, SCHEMA, "contact", no_rules)
    assert contacts.flags() == set()


def test_fingerprint_and_needs_rescan(env):
    engine, tm, obj_config = env
    assert dup.needs_rescan(engine, SCHEMA, "contact", obj_config)
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert not dup.needs_rescan(engine, SCHEMA, "contact", obj_config)

    changed = {**obj_config, "duplicates": {"rules": [
        {**RULES[0], "normalize": "digits"}, *RULES[1:]]}}
    assert dup.needs_rescan(engine, SCHEMA, "contact", changed)

    # An object that never had rules never needs a scan
    assert not dup.needs_rescan(engine, SCHEMA, "company", {"attributes": {}})
    assert dup.rules_fingerprint({"attributes": {}}) == ""


def test_rules_of_tolerates_unnormalised_config():
    assert dup.rules_of(None) == []
    assert dup.rules_of({"attributes": {}}) == []
    assert dup.rules_of({"duplicates": {"rules": [{"fields": ["a", "b"]}]}}) == [
        {"name": "a + b", "fields": ["a", "b"], "normalize": "text"}]


def test_indexes_follow_the_rules(env):
    engine, tm, obj_config = env

    def index_names():
        with engine.connect() as conn:
            return {r[0] for r in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = :s "
                "AND tablename = 'contact' AND indexname LIKE 'ix\\_dup\\_%'"), {"s": SCHEMA})}

    assert len(index_names()) == len(RULES) + 1   # one per rule + the draft-of index

    tm.sync_schema(_config(RULES[:2]))
    assert len(index_names()) == 3

    tm.sync_schema(_config([]))
    assert index_names() == set()


# --- requested rescans, interrupted scans, automatic rescan --------------------------

def _scan_row(engine):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT scanned_at, rescan_requested_at FROM _system.duplicate_scans "
            "WHERE schema_name = :s AND object_name = 'contact'"), {"s": SCHEMA}).first()


def _request(engine):
    with Session(engine) as db:
        dup.request_rescan(db, SCHEMA, "contact")
        db.commit()


def test_a_requested_rescan_is_cleared_only_by_a_scan_that_began_after_it(env):
    engine, tm, obj_config = env
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert not dup.needs_rescan(engine, SCHEMA, "contact", obj_config)

    _request(engine)   # rules unchanged, yet a rescan is now outstanding
    assert dup.needs_rescan(engine, SCHEMA, "contact", obj_config)
    assert dup.scan_info(engine, SCHEMA, "contact", obj_config)["needs_rescan"]
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert not dup.needs_rescan(engine, SCHEMA, "contact", obj_config)

    # A request made after the scan began (e.g. an import committed meanwhile) survives it
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE _system.duplicate_scans SET rescan_requested_at = "
            "clock_timestamp() + interval '1 hour' WHERE schema_name = :s"), {"s": SCHEMA})
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert dup.needs_rescan(engine, SCHEMA, "contact", obj_config)


def test_requesting_a_rescan_of_a_never_scanned_object_stores_nothing(env):
    engine, tm, obj_config = env
    _request(engine)
    assert _scan_row(engine) is None      # nothing to store ...
    assert dup.needs_rescan(engine, SCHEMA, "contact", obj_config)   # ... it is due anyway


def test_only_if_needed_skips_a_scan_that_someone_else_already_did(env):
    engine, tm, obj_config = env
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    scanned_at = _scan_row(engine)[0]

    assert dup.rescan_object(
        engine, SCHEMA, "contact", obj_config, only_if_needed=True) == {"skipped": True}
    assert _scan_row(engine)[0] == scanned_at

    _request(engine)
    result = dup.rescan_object(engine, SCHEMA, "contact", obj_config, only_if_needed=True)
    assert "skipped" not in result and _scan_row(engine)[0] > scanned_at


def test_an_interrupted_scan_leaves_flags_and_scan_state_untouched(env, monkeypatch):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    contacts.add(email="a@x.com", refresh=False)
    contacts.add(email="a@x.com", refresh=False)

    def die(*args, **kwargs):
        raise RuntimeError("server stopped")

    # rules_fingerprint() is called after the flags were rebuilt, just before the commit
    with monkeypatch.context() as patch:
        patch.setattr(dup, "rules_fingerprint", die)
        with pytest.raises(RuntimeError):
            dup.rescan_object(engine, SCHEMA, "contact", obj_config)

    assert contacts.flags() == set()          # the rebuilt flags were rolled back
    assert _scan_row(engine) is None          # and nothing says the object was scanned
    assert dup.needs_rescan(engine, SCHEMA, "contact", obj_config)
    assert not dup.scan_running(engine, SCHEMA, "contact")   # the lock went with it


def _loaded_config(obj_config, rescan="on_rule_change") -> dict:
    return {"schemas": {SCHEMA: {"objects": {"contact": obj_config, "company": {
        "name": "Company", "attributes": {}}}}}, "duplicates": {"rescan": rescan}}


def test_automatic_rescan_scans_objects_whose_rules_changed(env):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    a = contacts.add(email="a@x.com", refresh=False)   # data that predates the rules
    b = contacts.add(email="A@x.com", refresh=False)
    config = _loaded_config(obj_config)

    assert [(s, o) for s, o, _ in dup.pending_rescans(engine, config)] == [(SCHEMA, "contact")]
    thread = dup.start_auto_rescan(engine, config)
    thread.join(timeout=30)

    assert contacts.entities(EMAIL) == {a, b}
    assert dup.pending_rescans(engine, config) == []
    assert dup.start_auto_rescan(engine, config) is None   # nothing left: costs nothing

    # Changing a rule makes just that object due again
    changed = {**obj_config, "duplicates": {"rules": [{**RULES[0], "normalize": "digits"}]}}
    assert [o for _, o, _ in dup.pending_rescans(engine, _loaded_config(changed))] == ["contact"]


def test_automatic_rescan_in_manual_mode_only_reports(env, caplog):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    contacts.add(email="a@x.com", refresh=False)
    contacts.add(email="a@x.com", refresh=False)

    with caplog.at_level("WARNING", logger="app.core.duplicates"):
        assert dup.start_auto_rescan(engine, _loaded_config(obj_config, "manual")) is None

    assert contacts.flags() == set()
    assert dup.needs_rescan(engine, SCHEMA, "contact", obj_config)
    assert f"{SCHEMA}.contact" in caplog.text and "Duplicates page" in caplog.text


def test_automatic_rescan_purges_flags_when_all_rules_are_removed(env):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    contacts.add(email="a@x.com")
    contacts.add(email="a@x.com")
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert contacts.flags()

    no_rules = {**obj_config, "duplicates": {"rules": []}}
    dup.start_auto_rescan(engine, _loaded_config(no_rules)).join(timeout=30)
    assert contacts.flags() == set()
    assert not dup.needs_rescan(engine, SCHEMA, "contact", no_rules)


# --- audit trail of scans -------------------------------------------------------------

def _scan_audit(engine):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT user_name, schema_name, object_name, record_id::text, new_values, reason "
            "FROM _system.audit_log WHERE action = 'DUPLICATE_SCAN' "
            "AND new_values->>'schema' = :s ORDER BY timestamp"), {"s": SCHEMA}).all()


def test_every_completed_scan_is_audited_with_its_trigger(env):
    engine, tm, obj_config = env
    contacts = Contacts(engine, tm, obj_config)
    contacts.add(email="a@x.com", refresh=False)
    contacts.add(email="A@x.com", refresh=False)

    dup.rescan_object(engine, SCHEMA, "contact", obj_config, trigger="manual", user_name="anna")
    dup.start_auto_rescan(engine, _loaded_config(
        {**obj_config, "duplicates": {"rules": [RULES[0]]}}), trigger="config_reload"
    ).join(timeout=30)

    manual, reload_ = _scan_audit(engine)
    assert manual.user_name == "anna" and manual.new_values["trigger"] == "manual"
    assert manual.new_values["record_count"] == 2 and manual.new_values["groups"] == 1
    assert manual.new_values["object"] == "contact" and manual.new_values["duration_ms"] >= 0
    # A system event: schema _system, no record, readable sentence for the Auth Events tab
    assert (manual.schema_name, manual.object_name) == ("_system", "duplicate_scan")
    assert manual.record_id == "00000000-0000-0000-0000-000000000000"
    assert f"{SCHEMA}.contact" in manual.reason and "2 records" in manual.reason
    assert reload_.user_name == "system" and reload_.new_values["trigger"] == "config_reload"


def test_skipped_and_interrupted_scans_write_no_audit_entry(env, monkeypatch):
    engine, tm, obj_config = env
    dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert len(_scan_audit(engine)) == 1
    dup.rescan_object(engine, SCHEMA, "contact", obj_config, only_if_needed=True)  # skipped
    assert len(_scan_audit(engine)) == 1

    _request(engine)
    with monkeypatch.context() as patch:
        patch.setattr(dup, "rules_fingerprint", lambda *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            dup.rescan_object(engine, SCHEMA, "contact", obj_config)
    assert len(_scan_audit(engine)) == 1
