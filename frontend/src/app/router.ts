import { createRouter, createWebHashHistory } from "vue-router";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/conversation" },
    {
      path: "/conversation",
      component: () => import("../conversation/ConversationPage.vue"),
    },
    { path: "/today", component: () => import("../today/TodayPage.vue") },
    { path: "/life", redirect: "/life/tasks" },
    ...Object.entries({
      tasks: "todos",
      calendar: "calendar",
      reminders: "reminders",
      notes: "notes",
    }).map(([path, kind]) => ({
      path: `/life/${path}`,
      component: () => import("../records/RecordsPage.vue"),
      props: { kind },
    })),
    {
      path: "/memory",
      component: () => import("../records/RecordsPage.vue"),
      props: { kind: "memories" },
    },
    { path: "/settings", redirect: "/settings/appearance" },
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
