import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { initI18n } from "../i18n";

// axe probes canvas support; jsdom does not implement it and logs noise.
HTMLCanvasElement.prototype.getContext = () => null;

beforeEach(async () => {
  window.localStorage.clear();
  await initI18n("en");
});

afterEach(() => {
  cleanup();
});
