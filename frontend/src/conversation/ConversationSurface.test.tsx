import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationSurface, MarkdownContent } from "./ConversationSurface";

describe("conversation content", () => {
  it("renders common Markdown and selectable code as semantic content", () => {
    const markup = renderToStaticMarkup(
      <MarkdownContent
        content={[
          "## Plan",
          "",
          "Use **small steps** and `npm test`.",
          "",
          "- Write the test",
          "- Make it pass",
          "",
          "```ts",
          "const ready = true;",
          "```",
        ].join("\n")}
      />,
    );

    expect(markup).toContain("<h3>Plan</h3>");
    expect(markup).toContain("<strong>small steps</strong>");
    expect(markup).toContain("<code>npm test</code>");
    expect(markup).toContain("<ul>");
    expect(markup).toContain('<code class="language-ts">');
    expect(markup).toContain("const ready = true;");
  });

  it("labels proactive content without turning history into a live region", () => {
    const markup = renderToStaticMarkup(
      <ConversationSurface
        conversationId="main"
        conversationTitle="Afternoon check-in"
        latestLiveEvent={{
          kind: "proactive_chat",
          id: "proactive-1",
          message: { role: "assistant", content: "Tea break?" },
          occurredAt: 100,
        }}
        loadState="ready"
        messages={[{ role: "assistant", content: "Tea break?" }]}
      />,
    );

    expect(markup).toContain('data-source="proactive_chat"');
    expect(markup).toContain("主动聊天");
    expect(markup).not.toContain("aria-live");
  });
});
