import { createRouter, createWebHashHistory } from "vue-router";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/conversation" },
    {
      path: "/conversation",
      component: () => import("../conversation/ConversationPage.vue"),
    },
    { path: "/today", redirect: "/conversation" },
    { path: "/life", redirect: "/settings/tasks" },
    { path: "/memory", redirect: "/settings/memory" },
    ...Object.entries({
      tasks: "todos",
      notes: "notes",
      memory: "memories",
    }).map(([path, kind]) => ({
      path: `/settings/${path}`,
      component: () => import("../records/RecordsPage.vue"),
      props: { kind },
    })),
    { path: "/life/tasks", redirect: "/settings/tasks" },
    { path: "/life/notes", redirect: "/settings/notes" },
    { path: "/life/calendar", redirect: "/conversation?calendar=1" },
    { path: "/life/reminders", redirect: "/conversation?calendar=1" },
    { path: "/settings", redirect: "/settings/persona" },
    {
      path: "/settings/persona",
      component: () => import("../settings/PersonaPage.vue"),
    },
    {
      path: "/settings/appearance",
      component: () => import("../settings/AppearancePage.vue"),
    },
    {
      path: "/settings/providers",
      component: () => import("../settings/ModelSettingsPage.vue"),
    },
    {
      path: "/settings/skills",
      component: () => import("../skills/SkillsPage.vue"),
    },
    {
      path: "/settings/history",
      component: () => import("../history/HistoryPage.vue"),
    },
    {
      path: "/settings/diagnostics",
      component: () => import("../settings/DiagnosticsPage.vue"),
    },
    { path: "/:pathMatch(.*)*", redirect: "/conversation" },
  ],
});
