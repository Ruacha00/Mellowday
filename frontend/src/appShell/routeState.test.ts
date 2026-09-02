import { describe, expect, it } from "vitest";

import { canonicalizeHash } from "./routeState";

describe("AppShell hash routes", () => {
  it.each([
    ["", "#/conversation", "conversation"],
    ["#/life", "#/life/tasks", "life"],
    ["#/settings", "#/settings/appearance", "settings"],
    ["#/life/calendar", "#/life/calendar", "life"],
    ["#/settings/diagnostics", "#/settings/diagnostics", "settings"],
    ["#/not-a-product-area", "#/conversation", "conversation"],
  ])(
    "normalizes %s to the canonical route %s",
    (requestedHash, canonicalHash, area) => {
      expect(canonicalizeHash(requestedHash)).toMatchObject({
        hash: canonicalHash,
        area,
      });
    },
  );
});
