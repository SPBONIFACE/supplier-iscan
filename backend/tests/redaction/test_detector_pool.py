"""#196: the detector pool grows on demand to its size, never beyond, with the same spans."""

import threading
import time
from collections.abc import Sequence

import pytest

from app.redaction import Redactor
from app.redaction.detector import DetectorPool, detector_instances
from app.redaction.text import RedactionUnavailable
from tests.redaction.support import FakeDetector

Span = tuple[int, int]
NAME = "Anna Keller-Brandt"


class SlowDetector(FakeDetector):
    def __init__(self, meeting: threading.Barrier | None = None) -> None:
        super().__init__((NAME,))
        self.meeting = meeting
        self.busy = threading.Lock()  # each instance serves one call at a time

    def person_spans(self, texts: Sequence[str]) -> list[list[Span]]:
        assert self.busy.acquire(blocking=False), "an instance was used by two calls at once"
        try:
            if self.meeting is not None:
                self.meeting.wait()
            else:
                time.sleep(0.02)
            return super().person_spans(texts)
        finally:
            self.busy.release()


def run_in_threads(pool: DetectorPool, count: int) -> list[list[list[Span]]]:
    results: list[list[list[Span]]] = [[] for _ in range(count)]

    def call(index: int) -> None:
        results[index] = pool.person_spans([f"{NAME} works here"])

    threads = [threading.Thread(target=call, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return results


def test_two_calls_run_on_two_instances_at_once() -> None:
    meeting = threading.Barrier(2, timeout=10)
    made: list[SlowDetector] = []

    def factory() -> SlowDetector:
        made.append(SlowDetector(meeting))
        return made[-1]

    pool = DetectorPool(SlowDetector(meeting), factory, 2)

    results = run_in_threads(pool, 2)

    assert results == [[[(0, 18)]], [[(0, 18)]]]
    assert len(made) == 1  # the second instance was made when the first was busy


def test_one_instance_serialises_and_makes_no_other() -> None:
    made: list[SlowDetector] = []

    def factory() -> SlowDetector:
        made.append(SlowDetector())
        return made[-1]

    pool = DetectorPool(SlowDetector(), factory, 1)

    results = run_in_threads(pool, 4)

    assert made == []
    assert results == [[[(0, 18)]]] * 4


def test_the_pool_never_makes_more_than_its_size() -> None:
    made: list[SlowDetector] = []

    def factory() -> SlowDetector:
        made.append(SlowDetector())
        return made[-1]

    pool = DetectorPool(SlowDetector(), factory, 2)

    run_in_threads(pool, 8)

    assert len(made) <= 1


def test_a_failed_instance_load_frees_its_place() -> None:
    attempts = 0

    def factory() -> SlowDetector:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RedactionUnavailable
        return SlowDetector()

    pool = DetectorPool(SlowDetector(), factory, 2)
    held = pool._acquire()  # the only instance is busy: the next call makes a second one

    with pytest.raises(RedactionUnavailable):
        pool.person_spans(["x"])
    assert pool.person_spans([NAME]) == [[(0, 18)]]  # the place was freed: a second try is made
    assert attempts == 2
    pool._release(held)


def test_a_redactor_over_a_pool_gives_the_same_text_as_over_one_detector() -> None:
    text = f"Contact: {NAME}, anna@acme.example, +33 1 23 45 67 89."
    single = Redactor(FakeDetector((NAME,))).redact(text).text
    pooled = Redactor(DetectorPool(SlowDetector(), SlowDetector, 2)).redact(text).text
    assert pooled == single


def test_the_instance_count_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDACTION_DETECTOR_INSTANCES", raising=False)
    assert detector_instances() == 1
    monkeypatch.setenv("REDACTION_DETECTOR_INSTANCES", "2")
    assert detector_instances() == 2
    for bad in ("0", "9", "two", "-1"):
        monkeypatch.setenv("REDACTION_DETECTOR_INSTANCES", bad)
        with pytest.raises(RedactionUnavailable):
            detector_instances()
