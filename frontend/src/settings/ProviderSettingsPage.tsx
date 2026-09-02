import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import type {
  ProviderConfiguration,
  ProviderConfigurationInput,
  ProviderService,
} from "../services/providerApi";
import { LatestRequest } from "../services/requestLifecycle";

interface ProviderSettingsPageProps {
  service: ProviderService;
}

export interface ProviderDraft {
  name: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  timeoutSeconds: string;
  maxRetries: string;
}

interface ProviderValidation {
  field: keyof ProviderDraft;
  message: string;
  input?: ProviderConfigurationInput;
}

const emptyDraft: ProviderDraft = {
  name: "",
  baseUrl: "",
  model: "",
  apiKey: "",
  timeoutSeconds: "60",
  maxRetries: "2",
};

export function validateProviderDraft(
  draft: ProviderDraft,
  editing: boolean,
): ProviderValidation {
  const name = draft.name.trim();
  if (name.length === 0) {
    return { field: "name", message: "请输入提供方名称。" };
  }
  const baseUrl = draft.baseUrl.trim();
  if (!/^https?:\/\//u.test(baseUrl)) {
    return { field: "baseUrl", message: "请输入以 http:// 或 https:// 开头的地址。" };
  }
  const model = draft.model.trim();
  if (model.length === 0) {
    return { field: "model", message: "请输入模型名称。" };
  }
  if (!editing && draft.apiKey.length === 0) {
    return { field: "apiKey", message: "新增提供方时必须输入 API 密钥。" };
  }
  const timeoutSeconds = Number(draft.timeoutSeconds);
  if (
    draft.timeoutSeconds.trim().length === 0
    || !Number.isFinite(timeoutSeconds)
    || timeoutSeconds <= 0
  ) {
    return { field: "timeoutSeconds", message: "超时时间必须大于 0。" };
  }
  const maxRetries = Number(draft.maxRetries);
  if (
    draft.maxRetries.trim().length === 0
    || !Number.isInteger(maxRetries)
    || maxRetries < 0
    || maxRetries > 10
  ) {
    return { field: "maxRetries", message: "最大重试次数必须是 0 到 10 的整数。" };
  }
  return {
    field: "name",
    message: "",
    input: {
      name,
      baseUrl,
      model,
      apiKey: draft.apiKey,
      timeoutSeconds,
      maxRetries,
    },
  };
}

function draftFor(provider: ProviderConfiguration): ProviderDraft {
  return {
    name: provider.name,
    baseUrl: provider.baseUrl,
    model: provider.model,
    apiKey: "",
    timeoutSeconds: String(provider.timeoutSeconds),
    maxRetries: String(provider.maxRetries),
  };
}

export function ProviderSettingsPage({ service }: ProviderSettingsPageProps) {
  const [providers, setProviders] = useState<ProviderConfiguration[] | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [draft, setDraft] = useState<ProviderDraft>(emptyDraft);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const loadRequest = useRef(new LatestRequest());
  const mutationController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const form = useRef<HTMLFormElement>(null);

  const loadProviders = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    setNotice("");
    void loadRequest.current
      .run((signal) => service.listProviders(signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setProviders(result.value);
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
    setProviders(null);
    loadProviders(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      mutationController.current?.abort();
      mutationController.current = null;
    };
  }, [loadProviders]);

  const resetForm = () => {
    setDraft(emptyDraft);
    setEditingId(null);
  };

  const focusField = (field: keyof ProviderDraft) => {
    const control = form.current?.elements.namedItem(field);
    if (control instanceof HTMLElement) {
      control.focus();
    }
  };

  const replaceProvider = (provider: ProviderConfiguration) => {
    setProviders((current) => current?.map((item) => (
      item.id === provider.id ? provider : item
    )) ?? null);
  };

  const beginMutation = (action: string): AbortController | null => {
    if (busyAction !== null) {
      return null;
    }
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusyAction(action);
    return controller;
  };

  const finishMutation = (controller: AbortController) => {
    if (mounted.current && mutationController.current === controller) {
      mutationController.current = null;
      setBusyAction(null);
    }
  };

  const saveProvider = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validation = validateProviderDraft(draft, editingId !== null);
    if (validation.input === undefined) {
      setNotice(validation.message);
      focusField(validation.field);
      return;
    }
    const controller = beginMutation("save");
    if (controller === null) {
      return;
    }
    setNotice("正在保存模型提供方…");
    try {
      const saved = editingId === null
        ? await service.createProvider(validation.input, controller.signal)
        : await service.updateProvider(editingId, validation.input, controller.signal);
      if (!mounted.current || controller.signal.aborted) {
        return;
      }
      setProviders((current) => {
        if (current === null || editingId === null) {
          return [...(current ?? []), saved];
        }
        return current.map((provider) => provider.id === saved.id ? saved : provider);
      });
      resetForm();
      setNotice(`${saved.name} 已保存。`);
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice("模型提供方保存失败，请重试。");
      }
    } finally {
      finishMutation(controller);
    }
  };

  const updateEnablement = async (
    provider: ProviderConfiguration,
    enabled: boolean,
  ) => {
    const controller = beginMutation(`enabled:${provider.id}`);
    if (controller === null) {
      return;
    }
    setNotice(`正在更新 ${provider.name}…`);
    try {
      const updated = await service.setProviderEnabled(
        provider.id,
        enabled,
        controller.signal,
      );
      if (mounted.current && !controller.signal.aborted) {
        replaceProvider(updated);
        setNotice(`${provider.name} 已${updated.enabled ? "启用" : "停用"}。`);
      }
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice(`${provider.name} 更新失败。`);
      }
    } finally {
      finishMutation(controller);
    }
  };

  const selectProvider = async (provider: ProviderConfiguration) => {
    const controller = beginMutation(`select:${provider.id}`);
    if (controller === null) {
      return;
    }
    setNotice(`正在选择 ${provider.name}…`);
    try {
      const selected = await service.selectProvider(provider.id, controller.signal);
      if (mounted.current && !controller.signal.aborted) {
        setProviders((current) => current?.map((item) => ({
          ...item,
          selected: item.id === selected.id ? selected.selected : false,
        })) ?? null);
        setNotice(`${provider.name} 已设为当前提供方。`);
      }
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice(`${provider.name} 无法设为当前提供方。`);
      }
    } finally {
      finishMutation(controller);
    }
  };

  const validateProvider = async (provider: ProviderConfiguration) => {
    const controller = beginMutation(`validate:${provider.id}`);
    if (controller === null) {
      return;
    }
    setNotice(`正在验证 ${provider.name}…`);
    try {
      const result = await service.validateProvider(provider.id, controller.signal);
      if (mounted.current && !controller.signal.aborted) {
        setNotice(result.valid
          ? `${provider.name} 验证通过。`
          : `${provider.name} 验证失败：${result.failure?.code ?? "unknown"}。`);
      }
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice(`${provider.name} 暂时无法验证。`);
      }
    } finally {
      finishMutation(controller);
    }
  };

  if (loadState === "loading") {
    return <p className="settings-state" role="status">正在加载模型提供方…</p>;
  }
  if (loadState === "error" || providers === null) {
    return (
      <div className="settings-state" role="alert">
        <p>模型提供方加载失败。</p>
        <button className="quiet-button" onClick={() => loadProviders(true)} type="button">
          重试
        </button>
      </div>
    );
  }

  return (
    <section aria-labelledby="provider-editor-title" className="provider-settings-page">
      <section className="settings-editor provider-editor">
        <header>
          <span>可替换的模型接入</span>
          <h2 id="provider-editor-title">模型提供方</h2>
          <p>API 密钥只在此处输入；已保存的密钥仅以遮罩显示，编辑时留空可保留原密钥。</p>
        </header>
        <form noValidate onSubmit={(event) => void saveProvider(event)} ref={form}>
          <div className="settings-field-row">
            <label>
              <span>提供方名称</span>
              <input
                aria-label="提供方名称"
                autoComplete="off"
                name="name"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                value={draft.name}
              />
            </label>
            <label>
              <span>基础地址</span>
              <input
                aria-label="基础地址"
                autoComplete="off"
                name="baseUrl"
                onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })}
                type="url"
                value={draft.baseUrl}
              />
            </label>
          </div>
          <div className="settings-field-row">
            <label>
              <span>模型</span>
              <input
                aria-label="模型"
                autoComplete="off"
                name="model"
                onChange={(event) => setDraft({ ...draft, model: event.target.value })}
                value={draft.model}
              />
            </label>
            <label>
              <span>API 密钥</span>
              <input
                aria-label="API 密钥"
                autoComplete="new-password"
                name="apiKey"
                onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })}
                type="password"
                value={draft.apiKey}
              />
              {editingId === null ? null : <small>留空可保留已保存的密钥。</small>}
            </label>
          </div>
          <div className="settings-field-row">
            <label>
              <span>超时时间（秒）</span>
              <input
                aria-label="超时时间（秒）"
                min="0.001"
                name="timeoutSeconds"
                onChange={(event) => setDraft({ ...draft, timeoutSeconds: event.target.value })}
                step="any"
                type="number"
                value={draft.timeoutSeconds}
              />
            </label>
            <label>
              <span>最大重试次数</span>
              <input
                aria-label="最大重试次数"
                max="10"
                min="0"
                name="maxRetries"
                onChange={(event) => setDraft({ ...draft, maxRetries: event.target.value })}
                step="1"
                type="number"
                value={draft.maxRetries}
              />
            </label>
          </div>
          <div className="provider-form-actions">
            <button className="primary-button" disabled={busyAction !== null} type="submit">
              {busyAction === "save"
                ? "正在保存…"
                : editingId === null
                  ? "添加提供方"
                  : "保存提供方"}
            </button>
            {editingId === null ? null : (
              <button
                className="quiet-button"
                disabled={busyAction !== null}
                onClick={resetForm}
                type="button"
              >
                取消编辑
              </button>
            )}
          </div>
        </form>
      </section>

      <section aria-labelledby="provider-list-title" className="provider-list-section">
        <header className="provider-section-heading">
          <div>
            <span>本地配置</span>
            <h2 id="provider-list-title">已配置的提供方</h2>
          </div>
          <span>{providers.length}</span>
        </header>
        {providers.length === 0 ? (
          <p className="management-empty">尚未配置模型提供方。</p>
        ) : (
          <div className="provider-card-list">
            {providers.map((provider) => (
              <article className="provider-card" key={provider.id}>
                <header>
                  <div>
                    <h3>{provider.name}</h3>
                    <p>{provider.model} · {provider.baseUrl}</p>
                  </div>
                  <span>{provider.selected ? "当前使用" : "未选择"}</span>
                </header>
                <dl>
                  <div><dt>密钥</dt><dd>{provider.apiKey || "未设置"}</dd></div>
                  <div><dt>超时</dt><dd>{provider.timeoutSeconds} 秒</dd></div>
                  <div><dt>重试</dt><dd>{provider.maxRetries}</dd></div>
                </dl>
                <label className="settings-toggle-field provider-enablement">
                  <input
                    aria-label={`${provider.enabled ? "停用" : "启用"} ${provider.name}`}
                    checked={provider.enabled}
                    disabled={busyAction !== null}
                    onChange={(event) => void updateEnablement(provider, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{provider.enabled ? "已启用" : "已停用"}</span>
                </label>
                <div className="provider-actions">
                  <button
                    aria-label={`编辑 ${provider.name}`}
                    className="quiet-button"
                    disabled={busyAction !== null}
                    onClick={() => {
                      setEditingId(provider.id);
                      setDraft(draftFor(provider));
                      setNotice("");
                      window.requestAnimationFrame(() => focusField("name"));
                    }}
                    type="button"
                  >
                    编辑
                  </button>
                  <button
                    aria-label={`验证 ${provider.name}`}
                    className="quiet-button"
                    disabled={busyAction !== null}
                    onClick={() => void validateProvider(provider)}
                    type="button"
                  >
                    验证
                  </button>
                  {provider.selected ? null : (
                    <button
                      aria-label={`选择 ${provider.name}`}
                      className="quiet-button"
                      disabled={busyAction !== null || !provider.enabled}
                      onClick={() => void selectProvider(provider)}
                      type="button"
                    >
                      设为当前
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <p
        aria-label="模型提供方状态"
        aria-live="polite"
        className="settings-notice provider-notice"
        role="status"
      >
        {notice}
      </p>
    </section>
  );
}
