import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import type {
  ProactiveChatService,
  ProactiveChatSettings,
} from "../services/proactiveChatApi";
import { LatestRequest } from "../services/requestLifecycle";

interface ProactiveChatSettingsPageProps {
  service: ProactiveChatService;
}

interface ProactiveChatDraft {
  enabled: boolean;
  quietHoursStart: string;
  quietHoursEnd: string;
  cooldownSeconds: string;
  dailyLimit: string;
  proactiveChatStyle: string;
}

function toDraft(settings: ProactiveChatSettings): ProactiveChatDraft {
  return {
    enabled: settings.enabled,
    quietHoursStart: settings.quietHoursStart,
    quietHoursEnd: settings.quietHoursEnd,
    cooldownSeconds: String(settings.cooldownSeconds),
    dailyLimit: String(settings.dailyLimit),
    proactiveChatStyle: settings.proactiveChatStyle,
  };
}

function validTime(value: string): boolean {
  const match = /^(\d{2}):(\d{2})$/u.exec(value);
  return match !== null && Number(match[1]) < 24 && Number(match[2]) < 60;
}

export function validateProactiveChatDraft(draft: ProactiveChatDraft): {
  field: keyof ProactiveChatDraft;
  message: string;
  settings?: ProactiveChatSettings;
} {
  if (!validTime(draft.quietHoursStart)) {
    return { field: "quietHoursStart", message: "请输入有效的安静时段开始时间。" };
  }
  if (!validTime(draft.quietHoursEnd)) {
    return { field: "quietHoursEnd", message: "请输入有效的安静时段结束时间。" };
  }
  const cooldownSeconds = Number(draft.cooldownSeconds);
  if (
    draft.cooldownSeconds.trim().length === 0
    || !Number.isInteger(cooldownSeconds)
    || cooldownSeconds < 0
  ) {
    return { field: "cooldownSeconds", message: "冷却时间必须是非负整数。" };
  }
  const dailyLimit = Number(draft.dailyLimit);
  if (
    draft.dailyLimit.trim().length === 0
    || !Number.isInteger(dailyLimit)
    || dailyLimit < 0
  ) {
    return { field: "dailyLimit", message: "每日上限必须是非负整数。" };
  }
  const proactiveChatStyle = draft.proactiveChatStyle.trim();
  if (proactiveChatStyle.length === 0) {
    return { field: "proactiveChatStyle", message: "请输入主动聊天风格。" };
  }
  return {
    field: "enabled",
    message: "",
    settings: {
      enabled: draft.enabled,
      quietHoursStart: draft.quietHoursStart,
      quietHoursEnd: draft.quietHoursEnd,
      cooldownSeconds,
      dailyLimit,
      proactiveChatStyle,
    },
  };
}

export function ProactiveChatSettingsPage({ service }: ProactiveChatSettingsPageProps) {
  const [draft, setDraft] = useState<ProactiveChatDraft | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const loadRequest = useRef(new LatestRequest());
  const saveController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const form = useRef<HTMLFormElement>(null);

  const loadSettings = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    setNotice("");
    void loadRequest.current
      .run((signal) => service.getSettings(signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setDraft(toDraft(result.value));
          setLoadState("ready");
        }
      })
      .catch(() => {
        if (mounted.current) {
          setLoadState("error");
        }
      });
  }, [service]);

  useEffect(() => {
    mounted.current = true;
    setDraft(null);
    loadSettings(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      saveController.current?.abort();
      saveController.current = null;
    };
  }, [loadSettings]);

  const focusField = (field: keyof ProactiveChatDraft) => {
    const control = form.current?.elements.namedItem(field);
    if (control instanceof HTMLElement) {
      control.focus();
    }
  };

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (draft === null || saving) {
      return;
    }
    const validation = validateProactiveChatDraft(draft);
    if (validation.settings === undefined) {
      setNotice(validation.message);
      focusField(validation.field);
      return;
    }
    const controller = new AbortController();
    saveController.current?.abort();
    saveController.current = controller;
    setSaving(true);
    setNotice("正在保存主动聊天设置…");
    try {
      const saved = await service.updateSettings(validation.settings, controller.signal);
      if (mounted.current && !controller.signal.aborted) {
        setDraft(toDraft(saved));
        setNotice("主动聊天设置已保存。");
      }
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("主动聊天设置保存失败，请重试。");
      }
    } finally {
      if (mounted.current && saveController.current === controller) {
        saveController.current = null;
        setSaving(false);
      }
    }
  };

  if (loadState === "loading") {
    return <p className="settings-state" role="status">正在加载主动聊天设置…</p>;
  }
  if (loadState === "error" || draft === null) {
    return (
      <div className="settings-state" role="alert">
        <p>主动聊天设置加载失败。</p>
        <button className="quiet-button" onClick={() => loadSettings(true)} type="button">
          重试
        </button>
      </div>
    );
  }

  return (
    <section aria-labelledby="proactive-chat-editor-title" className="settings-editor">
      <header>
        <span>受限的陪伴消息</span>
        <h2 id="proactive-chat-editor-title">主动聊天</h2>
        <p>助手只会在允许的时段内发送短消息；评估过程不会创建或修改记忆和生活记录。</p>
      </header>
      <form noValidate onSubmit={(event) => void saveSettings(event)} ref={form}>
        <label className="settings-toggle-field">
          <input
            aria-label="启用主动聊天"
            checked={draft.enabled}
            name="enabled"
            onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
            type="checkbox"
          />
          <span>启用主动聊天</span>
        </label>
        <div className="settings-field-row">
          <label>
            <span>安静时段开始</span>
            <input
              aria-label="安静时段开始"
              name="quietHoursStart"
              onChange={(event) => setDraft({ ...draft, quietHoursStart: event.target.value })}
              type="time"
              value={draft.quietHoursStart}
            />
          </label>
          <label>
            <span>安静时段结束</span>
            <input
              aria-label="安静时段结束"
              name="quietHoursEnd"
              onChange={(event) => setDraft({ ...draft, quietHoursEnd: event.target.value })}
              type="time"
              value={draft.quietHoursEnd}
            />
          </label>
        </div>
        <div className="settings-field-row">
          <label>
            <span>冷却时间（秒）</span>
            <input
              aria-label="冷却时间（秒）"
              min="0"
              name="cooldownSeconds"
              onChange={(event) => setDraft({ ...draft, cooldownSeconds: event.target.value })}
              step="1"
              type="number"
              value={draft.cooldownSeconds}
            />
          </label>
          <label>
            <span>每日上限</span>
            <input
              aria-label="每日上限"
              min="0"
              name="dailyLimit"
              onChange={(event) => setDraft({ ...draft, dailyLimit: event.target.value })}
              step="1"
              type="number"
              value={draft.dailyLimit}
            />
          </label>
        </div>
        <label>
          <span>主动聊天风格</span>
          <textarea
            aria-label="主动聊天风格"
            name="proactiveChatStyle"
            onChange={(event) => setDraft({ ...draft, proactiveChatStyle: event.target.value })}
            rows={3}
            value={draft.proactiveChatStyle}
          />
        </label>
        <button className="primary-button" disabled={saving} type="submit">
          {saving ? "正在保存…" : "保存主动聊天设置"}
        </button>
      </form>
      <p
        aria-label="主动聊天设置状态"
        aria-live="polite"
        className="settings-notice"
        role="status"
      >
        {notice}
      </p>
    </section>
  );
}
