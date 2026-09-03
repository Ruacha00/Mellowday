import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { Memory, MemoryService } from "../services/memoryApi";
import {
  MemoryManagementPage,
  MemorySearchCoordinator,
  type MemorySearchSnapshot,
} from "./MemoryManagementPage";

const conciseMemory: Memory = {
  id: "concise",
  content: "I prefer concise replies.",
  kind: "preference",
  provenance: "explicit",
  sourceConversationId: "main",
  createdAt: 10,
  updatedAt: 20,
};

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

describe("Memory Management", () => {
  it("presents Memory as a neutral area separate from Life and Conversation History", () => {
    const service: MemoryService = {
      listMemories: vi.fn(),
      updateMemory: vi.fn(),
      requestDeleteConfirmation: vi.fn(),
      decideDelete: vi.fn(),
    };

    const markup = renderToStaticMarkup(<MemoryManagementPage service={service} />);

    expect(markup).toContain("搜索记忆");
    expect(markup).toContain("任务、提醒、日历事件、笔记和对话历史保留在各自的产品区域");
    expect(markup).not.toMatch(/embedding|similarity|knowledge graph|tag/i);
  });

  it("aborts an obsolete search and lets only the newest result publish", async () => {
    const first = deferred<Memory[]>();
    const second = deferred<Memory[]>();
    const signals: AbortSignal[] = [];
    const service = {
      listMemories: vi.fn((query: string, signal?: AbortSignal) => {
        if (signal !== undefined) {
          signals.push(signal);
        }
        return query === "first" ? first.promise : second.promise;
      }),
    };
    const snapshots: MemorySearchSnapshot[] = [];
    const coordinator = new MemorySearchCoordinator(
      service,
      (snapshot) => snapshots.push(snapshot),
    );

    const firstSearch = coordinator.search("first");
    const secondSearch = coordinator.search("second");
    expect(signals[0].aborted).toBe(true);
    second.resolve([conciseMemory]);
    await secondSearch;
    first.resolve([{ ...conciseMemory, id: "obsolete", content: "obsolete" }]);
    await firstSearch;

    expect(snapshots.at(-1)).toMatchObject({
      appliedQuery: "second",
      loadState: "ready",
      memories: [conciseMemory],
    });
  });

  it("aborts route-scoped search and ignores its late result after disposal", async () => {
    const pending = deferred<Memory[]>();
    let signal: AbortSignal | undefined;
    const snapshots: MemorySearchSnapshot[] = [];
    const coordinator = new MemorySearchCoordinator(
      {
        listMemories: (_query, requestSignal) => {
          signal = requestSignal;
          return pending.promise;
        },
      },
      (snapshot) => snapshots.push(snapshot),
    );

    const search = coordinator.search("");
    const publishedBeforeDispose = snapshots.length;
    coordinator.dispose();
    expect(signal?.aborted).toBe(true);
    pending.resolve([conciseMemory]);
    await search;

    expect(snapshots).toHaveLength(publishedBeforeDispose);
    expect(snapshots.at(-1)?.loadState).toBe("loading");
  });
});
