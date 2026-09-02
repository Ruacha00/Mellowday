import { describe, expect, it, vi } from "vitest";

import { HttpTaskService } from "./taskApi";

const apiTask = {
  id: "task-1",
  title: "Submit report",
  details: "Attach charts",
  completed: false,
  deadline: "2026-09-04",
  created_at: 100,
  updated_at: 200,
  completed_at: null,
};

const confirmation = {
  id: "confirmation-1",
  binding: {
    user_id: "local-user",
    conversation_id: "settings",
    tool: "task_delete",
    arguments: { task_id: "task-1" },
    initiating_context: [],
  },
  created_at: 300,
  expires_at: 400,
};

describe("HTTP Task service", () => {
  it("converts task fields and forwards cancellation to list requests", async () => {
    const controller = new AbortController();
    const fetchRequest = vi.fn(async () => Response.json({ tasks: [apiTask] }));
    const service = new HttpTaskService(fetchRequest);

    await expect(service.listTasks(controller.signal)).resolves.toEqual([
      {
        id: "task-1",
        title: "Submit report",
        details: "Attach charts",
        completed: false,
        deadline: "2026-09-04",
        createdAt: 100,
        updatedAt: 200,
        completedAt: null,
      },
    ]);
    expect(fetchRequest).toHaveBeenCalledWith("/api/settings/tasks", {
      signal: controller.signal,
    });
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
      return Response.json({ task: apiTask });
    });
    const service = new HttpTaskService(fetchRequest);
    const draft = {
      title: "Submit report",
      details: "Attach charts",
      deadline: "2026-09-04",
    };

    await service.createTask(draft);
    await service.updateTask("task-1", draft);
    await service.setCompleted("task-1", true);
    await service.setCompleted("task-1", false);
    const pending = await service.requestDeleteConfirmation("task-1");
    await service.decideDelete("task-1", pending, "accept");

    expect(requests.map(({ url, init }) => [url, init?.method ?? "GET"])).toEqual([
      ["/api/settings/tasks", "POST"],
      ["/api/settings/tasks/task-1", "PATCH"],
      ["/api/settings/tasks/task-1/complete", "POST"],
      ["/api/settings/tasks/task-1/reopen", "POST"],
      ["/api/settings/tasks/task-1/delete-confirmation", "POST"],
      ["/api/settings/tasks/task-1", "DELETE"],
    ]);
    expect(JSON.parse(String(requests.at(-1)?.init?.body))).toEqual({
      confirmation_id: "confirmation-1",
      binding: confirmation.binding,
      decision: "accept",
    });
  });

  it("reports HTTP failures without replacing their status", async () => {
    const service = new HttpTaskService(async () => new Response(null, { status: 503 }));

    await expect(service.listTasks()).rejects.toMatchObject({ status: 503 });
  });
});
