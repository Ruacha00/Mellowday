import { describe, expect, it, vi } from "vitest";

import { HttpNoteService } from "./noteApi";

const apiNote = {
  id: "note-1",
  title: "Trip ideas",
  content: "Visit Kyoto and Nara",
  created_at: 100,
  updated_at: 200,
};

const confirmation = {
  id: "confirmation-1",
  binding: {
    user_id: "local-user",
    conversation_id: "settings",
    tool: "note_delete",
    arguments: { note_id: "note-1" },
    initiating_context: [],
  },
  created_at: 300,
  expires_at: 400,
};

describe("HTTP Note service", () => {
  it("converts note fields, encodes searches, and forwards read cancellation", async () => {
    const controller = new AbortController();
    const fetchRequest = vi.fn(async (input: RequestInfo | URL) =>
      Response.json(String(input).includes("note-1")
        ? { note: apiNote }
        : { notes: [apiNote] }),
    );
    const service = new HttpNoteService(fetchRequest);

    await expect(service.listNotes(" 京都 & 奈良 ", controller.signal)).resolves
      .toEqual([{
        id: "note-1",
        title: "Trip ideas",
        content: "Visit Kyoto and Nara",
        createdAt: 100,
        updatedAt: 200,
      }]);
    await expect(service.getNote("note-1", controller.signal)).resolves
      .toMatchObject({ id: "note-1", title: "Trip ideas" });
    expect(fetchRequest).toHaveBeenNthCalledWith(
      1,
      "/api/settings/notes?q=%E4%BA%AC%E9%83%BD%20%26%20%E5%A5%88%E8%89%AF",
      { signal: controller.signal },
    );
    expect(fetchRequest).toHaveBeenNthCalledWith(
      2,
      "/api/settings/notes/note-1",
      { signal: controller.signal },
    );
  });

  it("uses the existing mutation paths and preserves delete confirmation binding", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetchRequest = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith("/delete-confirmation")) {
        return Response.json({ confirmation });
      }
      if (init?.method === "DELETE") {
        return Response.json({ ok: true, decision: "accept" });
      }
      return Response.json({ note: apiNote });
    });
    const service = new HttpNoteService(fetchRequest);
    const draft = { title: "Trip ideas", content: "Visit Kyoto and Nara" };

    await service.createNote(draft);
    await service.updateNote("note-1", draft);
    const pending = await service.requestDeleteConfirmation("note-1");
    await service.decideDelete("note-1", pending, "accept");

    expect(requests.map(({ url, init }) => [url, init?.method ?? "GET"])).toEqual([
      ["/api/settings/notes", "POST"],
      ["/api/settings/notes/note-1", "PATCH"],
      ["/api/settings/notes/note-1/delete-confirmation", "POST"],
      ["/api/settings/notes/note-1", "DELETE"],
    ]);
    expect(JSON.parse(String(requests.at(-1)?.init?.body))).toEqual({
      confirmation_id: "confirmation-1",
      binding: confirmation.binding,
      decision: "accept",
    });
  });

  it("reports HTTP failures without replacing their status", async () => {
    const service = new HttpNoteService(
      async () => new Response(null, { status: 503 }),
    );

    await expect(service.listNotes()).rejects.toMatchObject({ status: 503 });
  });
});
