import { describe, expect, it } from "vitest";
import type { Fact } from "./api";
import { buildNoteIndex, readEventDate, sortTimeline } from "./notes";

const fact = (id: string, source: string | null, quote: string | null = "q"): Fact =>
  ({
    id,
    field: id,
    section: "s",
    status: "proposed",
    value: "v",
    quote,
    source_id: source,
    source_url: source ? `https://${source}.example/` : null,
    source_type: "supplier_claim",
    publisher: source,
    fetched_at: null,
  }) as unknown as Fact;

describe("note numbers", () => {
  it("numbers per source in order of first appearance, and keeps a source's number", () => {
    const a1 = fact("a1", "alpha");
    const b = fact("b", "beta");
    const a2 = fact("a2", "alpha");
    const index = buildNoteIndex([b, a1, a2]);
    expect(index.numberOf(b)).toBe(1);
    expect(index.numberOf(a1)).toBe(2);
    expect(index.numberOf(a2)).toBe(2);
    expect(index.sources.map((s) => s.title)).toEqual(["beta", "alpha"]);
  });

  it("gives no number to a fact without a quote", () => {
    const none = fact("n", "alpha", null);
    expect(buildNoteIndex([none]).numberOf(none)).toBeNull();
  });
});

describe("event dates", () => {
  it("reads a full date, a month and year, or a year, and nothing else", () => {
    expect(readEventDate("Appointed on Feb 23, 2021")).toEqual({
      precision: "day",
      year: 2021,
      month: 2,
      day: 23,
    });
    expect(readEventDate("nommé le 23 février 2021")).toMatchObject({ precision: "day", month: 2 });
    expect(readEventDate("in March 2019")).toEqual({ precision: "month", year: 2019, month: 3 });
    expect(readEventDate("since 2015")).toEqual({ precision: "year", year: 2015 });
    expect(readEventDate("a new plant in Kunshan")).toBeNull();
  });

  it("sorts newest dated first and undated last", () => {
    const entries = ["no date", "in 2019", "Feb 23, 2021", "also none"].map((item) => ({
      item,
      date: readEventDate(item),
    }));
    expect(sortTimeline(entries).map((e) => e.item)).toEqual([
      "Feb 23, 2021",
      "in 2019",
      "no date",
      "also none",
    ]);
  });
});
