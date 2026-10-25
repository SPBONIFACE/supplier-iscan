import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the placeholder page with the product name", () => {
    const html = renderToString(<App />);

    expect(html).toContain("<h1>Supplier iScan</h1>");
  });
});
