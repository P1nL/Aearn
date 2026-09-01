import { describe, expect, it } from "vitest";

import { parsePreviewHostEvent } from "./previewHostApi";

function eventFixture() {
  return {
    hostId: "host-1",
    nonce: "a".repeat(64),
    scope: {
      artifactId: "artifact-1",
      sourceArtifactId: "artifact-source",
      sessionId: "session-1",
      artifactVersion: 2,
      languageId: "html_css",
    },
    generation: 3,
    sequence: 4,
    event: { kind: "console", level: "warn", message: "bounded" },
  };
}

describe("Preview host event boundary", () => {
  it("accepts the exact bounded bridge union", () => {
    expect(parsePreviewHostEvent(eventFixture())).toMatchObject({
      hostId: "host-1",
      generation: 3,
      event: { kind: "console", level: "warn", message: "bounded" },
    });
  });

  it("rejects extra fields, bad nonce, unknown events and oversized logs", () => {
    const variants = [
      { ...eventFixture(), extra: true },
      { ...eventFixture(), nonce: "not-a-nonce" },
      { ...eventFixture(), event: { kind: "future_event" } },
      { ...eventFixture(), event: { kind: "console", level: "log", message: "x".repeat(1_025) } },
      { ...eventFixture(), scope: { ...eventFixture().scope, extra: true } },
    ];
    for (const value of variants) expect(parsePreviewHostEvent(value)).toBeNull();
  });
});
