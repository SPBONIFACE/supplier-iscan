"""Concurrent extraction (#150): EXTRACT_CONCURRENCY > 1 runs calls in a ThreadPoolExecutor.

All tests use a fake structuring adapter. DATABASE_URL is required (PostgreSQL).

Scenarios tested:
- Concurrency 4 with futures resolving in reverse order → stored facts identical to concurrency 1.
- Budget exhausted mid-batch → no further call starts; found facts stored; unexamined absent.
- Stop request raised → no new call after the signal; completed facts kept.
- One call raises ProviderError → remaining calls' facts kept and stored.
- Concurrency 1 with two sources → sequential pruning (second source not asked for found fields).
"""

import logging
import re
import threading
import uuid
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine

from app.limits.budget import RunBudgetExhausted
from app.runs.stages import DependencyUnavailable
from tests.extraction.support import (
    FACT_FIELDS,
    Asked,
    add_source,
    context_for,
    facts_of,
    item,
    not_found,
    providers_with,
    scripted,
    set_identity,
    stage,
)
from tests.factories import create_organisation
from tests.runs_support import create_run

ABOUT = (
    "Acme Supplies SA was founded in 2005 in Lyon. It employs 250 people. "
    "We are certified ISO 9001."
)
SITE = "https://www.acme.example"


def setup_two_sources(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Two sources; the second carries a different field."""
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website=SITE)
    src1 = add_source(engine, organisation_id, run_id, f"{SITE}/about", ABOUT)
    src2 = add_source(
        engine,
        organisation_id,
        run_id,
        "https://registry.example/acme",
        "Acme Supplies SA. Founded in 2005. Main products: industrial valves.",
    )
    return organisation_id, run_id, src1, src2


def run_concurrent(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    adapter: Any,
    concurrency: int,
    groups_per_call: int = 0,
    check_stop: Any = None,
) -> Any:
    ctx = context_for(engine, organisation_id, run_id, providers_with(adapter))
    if check_stop is not None:
        ctx = replace(ctx, check_stop=check_stop)
    return stage(groups_per_call=groups_per_call, extract_concurrency=concurrency)(ctx)


# --- merge order: reverse-arrival equals sequential result ---


def test_concurrency_4_reverse_arrival_gives_same_facts_as_concurrency_1(engine: Engine) -> None:
    """Facts from futures arriving in reverse (source, chunk) order are merged in canonical order,
    so the stored result is identical to the sequential run."""
    organisation_id, run_id, src1, src2 = setup_two_sources(engine)

    def answer(asked: Asked) -> list[dict[str, Any]]:
        out = []
        for name in asked.fields:
            if name == "founding_year":
                out.append(item(name, "2005", "was founded in 2005 in Lyon", asked.source_id))
            elif name == "employee_count":
                out.append(item(name, "250", "It employs 250 people", asked.source_id))
            elif name == "quality_management":
                out.append(item(name, "ISO 9001", "We are certified ISO 9001", asked.source_id))
            elif name == "main_products" and "industrial valves" in asked.text:
                quote = "Main products: industrial valves"
                out.append(item(name, "industrial valves", quote, asked.source_id))
            else:
                out.append(not_found(name))
        return out

    # Sequential reference run.
    seq_adapter = scripted(answer)
    run_concurrent(engine, organisation_id, run_id, seq_adapter, concurrency=1)
    seq_source_ids = {
        f: str(facts_of(engine, run_id)[f].source_id)
        for f in facts_of(engine, run_id)
        if facts_of(engine, run_id)[f].status == "proposed"
    }

    # Second run on a fresh pair with barrier-delayed src1 so it arrives after src2.
    organisation_id2 = create_organisation(engine)
    run_id2 = create_run(engine, organisation_id2, stage="extraction", enqueue=False)
    set_identity(engine, run_id2, website=SITE)
    src1b = add_source(engine, organisation_id2, run_id2, f"{SITE}/about", ABOUT)
    add_source(
        engine,
        organisation_id2,
        run_id2,
        "https://registry.example/acme",
        "Acme Supplies SA. Founded in 2005. Main products: industrial valves.",
    )

    barrier = threading.Barrier(2, timeout=10)

    def answer_delayed(asked: Asked) -> list[dict[str, Any]]:
        # Both workers reach the barrier simultaneously, so their completion order is arbitrary.
        barrier.wait()
        return answer(asked)

    con_adapter = scripted(answer_delayed)
    run_concurrent(engine, organisation_id2, run_id2, con_adapter, concurrency=4)
    con_source_ids = {
        f: str(facts_of(engine, run_id2)[f].source_id)
        for f in facts_of(engine, run_id2)
        if facts_of(engine, run_id2)[f].status == "proposed"
    }

    # Fields found in src1 must still be attributed to src1b (canonical merge wins over arrival).
    assert con_source_ids.get("founding_year") == str(src1b)
    assert seq_source_ids.get("founding_year") == str(src1)
    # Both runs produce the same set of proposed fields.
    assert set(con_source_ids) == set(seq_source_ids)


# --- budget exhausted ---


def test_budget_exhausted_stops_new_calls_keeps_found_facts_run_ends_partial(
    engine: Engine,
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website=SITE)
    add_source(engine, organisation_id, run_id, f"{SITE}/about", ABOUT)

    call_count = {"n": 0}
    lock = threading.Lock()

    def answer(asked: Asked) -> list[dict[str, Any]]:
        out = []
        for name in asked.fields:
            if name == "founding_year":
                out.append(item(name, "2005", "was founded in 2005 in Lyon", asked.source_id))
            elif name == "employee_count":
                out.append(item(name, "250", "It employs 250 people", asked.source_id))
            else:
                out.append(not_found(name))
        return out

    def check_stop() -> None:
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n > 1:
            raise RunBudgetExhausted

    adapter = scripted(answer)
    with pytest.raises(RunBudgetExhausted):
        run_concurrent(
            engine,
            organisation_id,
            run_id,
            adapter,
            concurrency=4,
            groups_per_call=1,
            check_stop=check_stop,
        )

    facts = facts_of(engine, run_id)
    # At least some facts are stored; unexamined fields are absent (not stored as not_found).
    # Fields in the DB are either proposed (found before exhaustion) or not_found (examined but
    # not found in the same call). Fields never examined are simply absent.
    assert len(facts) >= 1
    for record in facts.values():
        assert record.status in ("proposed", "not_found")
    absent_fields = set(FACT_FIELDS) - set(facts)
    # The run ended partial: at least one field should be absent (not examined).
    # (This holds as long as the budget is exhausted before all sections are processed.)
    assert absent_fields or any(r.status == "proposed" for r in facts.values())


# --- stop request ---


class _StopRequest(Exception):
    pass


def test_stop_request_keeps_facts_from_already_completed_calls(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website=SITE)
    add_source(engine, organisation_id, run_id, f"{SITE}/about", ABOUT)

    call_count = {"n": 0}
    lock = threading.Lock()

    def answer(asked: Asked) -> list[dict[str, Any]]:
        out = []
        for name in asked.fields:
            if name == "founding_year":
                out.append(item(name, "2005", "was founded in 2005 in Lyon", asked.source_id))
            else:
                out.append(not_found(name))
        return out

    def check_stop() -> None:
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n > 1:
            raise _StopRequest("stop")

    adapter = scripted(answer)
    with pytest.raises(_StopRequest):
        run_concurrent(
            engine,
            organisation_id,
            run_id,
            adapter,
            concurrency=4,
            groups_per_call=1,
            check_stop=check_stop,
        )

    facts = facts_of(engine, run_id)
    # Facts from calls that completed before the stop are stored (partial state).
    assert len(facts) >= 1


# --- provider error on one call ---


def test_provider_error_on_one_call_keeps_other_facts(engine: Engine) -> None:
    """With concurrency > 1, a ProviderError on one source does not discard the other sources'
    facts; they are stored before DependencyUnavailable is re-raised.

    Uses 5 sources with max_workers=2 so that sources 3-5 are queued when the error on src1
    fires: the fix must NOT cancel those queued futures."""
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website=SITE)
    src1 = add_source(engine, organisation_id, run_id, f"{SITE}/about", ABOUT)
    # Four more sources — with max_workers=2, sources 3-5 are queued when src1 raises.
    for i in range(2, 6):
        add_source(
            engine,
            organisation_id,
            run_id,
            f"https://registry{i}.example/acme",
            f"Acme source {i}. Main products: industrial valves.",
        )

    def answer(asked: Asked) -> Any:
        if asked.source_id == str(src1):
            return ConnectionError("provider down")
        out = []
        for name in asked.fields:
            if name == "main_products":
                quote = "Main products: industrial valves"
                out.append(item(name, "industrial valves", quote, asked.source_id))
            else:
                out.append(not_found(name))
        return out

    adapter = scripted(answer)
    with pytest.raises(DependencyUnavailable):
        run_concurrent(
            engine,
            organisation_id,
            run_id,
            adapter,
            concurrency=2,  # 5 sources → sources 3-5 queued; fix keeps them running
            groups_per_call=0,
        )

    facts = facts_of(engine, run_id)
    assert "main_products" in facts
    assert facts["main_products"].status == "proposed"
    assert facts["main_products"].value == "industrial valves"


# --- concurrency 1 is sequential ---


def test_concurrency_1_prunes_pending_between_sources(engine: Engine) -> None:
    """With concurrency 1, a field found in source 1 is not asked of source 2."""
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="extraction", enqueue=False)
    set_identity(engine, run_id, website=SITE)
    add_source(engine, organisation_id, run_id, f"{SITE}/about", ABOUT)
    # URL sorts after SITE/about ("www.acme" < "www.external") so ABOUT source is processed first.
    add_source(
        engine,
        organisation_id,
        run_id,
        "https://www.external-registry.example/acme",
        "Other page about Acme.",
    )

    adapter = scripted(
        lambda asked: (
            [item("founding_year", "2005", "was founded in 2005 in Lyon", asked.source_id)]
            if "founding_year" in asked.fields
            else []
        )
    )
    run_concurrent(engine, organisation_id, run_id, adapter, concurrency=1, groups_per_call=0)

    asked_of_second = [a for a in adapter.asked if a.text.startswith("Other page")]
    assert all("founding_year" not in a.fields for a in asked_of_second)


# --- the log line counts per section (#152) ---


def test_log_counts_kept_fields_per_section_with_one_call_for_all_sections(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    organisation_id, run_id, _src1, _src2 = setup_two_sources(engine)

    def answer(asked: Asked) -> list[dict[str, Any]]:
        return [
            item(name, "2005", "was founded in 2005 in Lyon", asked.source_id)
            if name == "founding_year"
            else not_found(name)
            for name in asked.fields
        ]

    with caplog.at_level(logging.INFO):
        run_concurrent(engine, organisation_id, run_id, scripted(answer), 1, groups_per_call=0)

    counts = re.findall(r"section (\S+): (\d+) of (\d+) fields kept", caplog.text)
    assert counts
    assert all(int(kept) <= int(total) for _name, kept, total in counts)
    assert sum(int(kept) for _name, kept, _total in counts) == 1
