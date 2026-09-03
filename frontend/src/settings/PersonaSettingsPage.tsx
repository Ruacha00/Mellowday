import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import type { Persona, PersonaService } from "../services/personaApi";
import { LatestRequest } from "../services/requestLifecycle";

interface PersonaSettingsPageProps {
  service: PersonaService;
}

const personaFields: Array<{
  key: keyof Persona;
  label: string;
  rows?: number;
}> = [
  { key: "name", label: "名称" },
  { key: "identity", label: "身份", rows: 2 },
  { key: "character", label: "性格", rows: 2 },
  { key: "speakingStyle", label: "表达方式", rows: 2 },
  { key: "relationshipFraming", label: "关系定位", rows: 2 },
  { key: "conversationalBoundaries", label: "对话边界", rows: 3 },
  { key: "proactiveChatStyle", label: "主动聊天风格", rows: 2 },
];

export function validatePersona(persona: Persona): {
  field: keyof Persona;
  message: string;
} | null {
  const emptyField = personaFields.find(({ key }) => persona[key].trim().length === 0);
  return emptyField === undefined
    ? null
    : { field: emptyField.key, message: `请输入${emptyField.label}。` };
}

export function PersonaSettingsPage({ service }: PersonaSettingsPageProps) {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const loadRequest = useRef(new LatestRequest());
  const saveController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const form = useRef<HTMLFormElement>(null);

  const loadPersona = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    setNotice("");
    void loadRequest.current
      .run((signal) => service.getPersona(signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setPersona(result.value);
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
    setPersona(null);
    loadPersona(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      saveController.current?.abort();
      saveController.current = null;
    };
  }, [loadPersona]);

  const focusField = (field: keyof Persona) => {
    const control = form.current?.elements.namedItem(field);
    if (control instanceof HTMLElement) {
      control.focus();
    }
  };

  const savePersona = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (persona === null || saving) {
      return;
    }
    const validation = validatePersona(persona);
    if (validation !== null) {
      setNotice(validation.message);
      focusField(validation.field);
      return;
    }
    const normalized = Object.fromEntries(
      Object.entries(persona).map(([key, value]) => [key, value.trim()]),
    ) as unknown as Persona;
    const controller = new AbortController();
    saveController.current?.abort();
    saveController.current = controller;
    setSaving(true);
    setNotice("正在保存人格设定…");
    try {
      const saved = await service.updatePersona(normalized, controller.signal);
      if (mounted.current && !controller.signal.aborted) {
        setPersona(saved);
        setNotice("人格设定已保存。");
      }
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("人格设定保存失败，请重试。");
      }
    } finally {
      if (mounted.current && saveController.current === controller) {
        saveController.current = null;
        setSaving(false);
      }
    }
  };

  if (loadState === "loading") {
    return <p className="settings-state" role="status">正在加载人格设定…</p>;
  }
  if (loadState === "error" || persona === null) {
    return (
      <div className="settings-state" role="alert">
        <p>人格设定加载失败。</p>
        <button className="quiet-button" onClick={() => loadPersona(true)} type="button">
          重试
        </button>
      </div>
    );
  }

  return (
    <section aria-labelledby="persona-editor-title" className="settings-editor">
      <header>
        <span>聊天身份</span>
        <h2 id="persona-editor-title">人格设定</h2>
        <p>这些内容只影响聊天表达，不影响设置、记录、权限、日志和诊断中的文字。</p>
      </header>
      <form noValidate onSubmit={(event) => void savePersona(event)} ref={form}>
        {personaFields.map(({ key, label, rows }) => (
          <label key={key}>
            <span>{label}</span>
            {rows === undefined ? (
              <input
                aria-label={label}
                autoComplete="off"
                name={key}
                onChange={(event) => setPersona({ ...persona, [key]: event.target.value })}
                type="text"
                value={persona[key]}
              />
            ) : (
              <textarea
                aria-label={label}
                name={key}
                onChange={(event) => setPersona({ ...persona, [key]: event.target.value })}
                rows={rows}
                value={persona[key]}
              />
            )}
          </label>
        ))}
        <button className="primary-button" disabled={saving} type="submit">
          {saving ? "正在保存…" : "保存人格设定"}
        </button>
      </form>
      <p
        aria-label="人格设定状态"
        aria-live="polite"
        className="settings-notice"
        role="status"
      >
        {notice}
      </p>
    </section>
  );
}
