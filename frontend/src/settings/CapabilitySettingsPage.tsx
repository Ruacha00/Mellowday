import { useCallback, useEffect, useRef, useState } from "react";

import type {
  Capabilities,
  CapabilityService,
  SkillCapability,
} from "../services/capabilityApi";
import { LatestRequest } from "../services/requestLifecycle";

interface CapabilitySettingsPageProps {
  service: CapabilityService;
}

function replaceSkill(
  capabilities: Capabilities,
  updated: SkillCapability,
): Capabilities {
  return {
    ...capabilities,
    skills: capabilities.skills.map((skill) => (
      skill.name === updated.name ? updated : skill
    )),
  };
}

export function CapabilitySettingsPage({ service }: CapabilitySettingsPageProps) {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [busySkill, setBusySkill] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const loadRequest = useRef(new LatestRequest());
  const mutationController = useRef<AbortController | null>(null);
  const mounted = useRef(false);

  const loadCapabilities = useCallback((showLoading: boolean) => {
    if (!mounted.current) {
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    setNotice("");
    void loadRequest.current
      .run((signal) => service.getCapabilities(signal))
      .then((result) => {
        if (mounted.current && result.status === "current") {
          setCapabilities(result.value);
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
    setCapabilities(null);
    loadCapabilities(true);
    return () => {
      mounted.current = false;
      loadRequest.current.cancel();
      mutationController.current?.abort();
      mutationController.current = null;
    };
  }, [loadCapabilities]);

  const setSkillEnabled = async (skill: SkillCapability, enabled: boolean) => {
    if (busySkill !== null) {
      return;
    }
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    setBusySkill(skill.name);
    setNotice(`正在更新 ${skill.name}…`);
    try {
      const updated = await service.setSkillEnabled(
        skill.name,
        enabled,
        controller.signal,
      );
      if (mounted.current && !controller.signal.aborted) {
        setCapabilities((current) => current === null
          ? current
          : replaceSkill(current, updated));
        setNotice(`${skill.name} 已${updated.enabled ? "启用" : "停用"}。`);
      }
    } catch {
      if (mounted.current && !controller.signal.aborted) {
        setNotice(`${skill.name} 更新失败。`);
      }
    } finally {
      if (mounted.current && mutationController.current === controller) {
        mutationController.current = null;
        setBusySkill(null);
      }
    }
  };

  if (loadState === "loading") {
    return <p className="settings-state" role="status">正在加载能力…</p>;
  }
  if (loadState === "error" || capabilities === null) {
    return (
      <div className="settings-state" role="alert">
        <p>能力加载失败。</p>
        <button className="quiet-button" onClick={() => loadCapabilities(true)} type="button">
          重试
        </button>
      </div>
    );
  }

  return (
    <section aria-labelledby="capabilities-title" className="capabilities-page">
      <header className="capabilities-intro">
        <span>独立于模型凭据</span>
        <h2 id="capabilities-title">能力</h2>
        <p>工具元数据和技能状态来自本地后端；这里不显示或保存模型提供方凭据。</p>
      </header>
      <div className="capability-columns">
        <section aria-labelledby="tools-title" className="capability-section">
          <header className="capability-section-heading">
            <h2 id="tools-title">工具</h2>
            <span>{capabilities.tools.length}</span>
          </header>
          {capabilities.tools.length === 0 ? (
            <p className="management-empty">没有已注册的工具。</p>
          ) : (
            <div className="capability-list">
              {capabilities.tools.map((tool) => (
                <article className="capability-card" key={tool.name}>
                  <h3><code>{tool.name}</code></h3>
                  <p>{tool.description}</p>
                  <dl>
                    <div><dt>副作用</dt><dd>{tool.sideEffect}</dd></div>
                    <div><dt>风险</dt><dd>{tool.risk}</dd></div>
                    <div>
                      <dt>权限</dt>
                      <dd>{tool.permissionRequirements.join(", ") || "无"}</dd>
                    </div>
                  </dl>
                  <details>
                    <summary>输入结构</summary>
                    <pre>{JSON.stringify(tool.inputSchema, null, 2)}</pre>
                  </details>
                </article>
              ))}
            </div>
          )}
        </section>
        <section aria-labelledby="skills-title" className="capability-section">
          <header className="capability-section-heading">
            <h2 id="skills-title">技能</h2>
            <span>{capabilities.skills.length}</span>
          </header>
          {capabilities.skills.length === 0 ? (
            <p className="management-empty">没有已注册的技能。</p>
          ) : (
            <div className="capability-list">
              {capabilities.skills.map((skill) => (
                <article className="capability-card skill-card" key={skill.name}>
                  <div>
                    <h3><code>{skill.name}</code></h3>
                    <p>{skill.description}</p>
                  </div>
                  <label className="settings-toggle-field">
                    <input
                      aria-label={`${skill.enabled ? "停用" : "启用"} ${skill.name} 技能`}
                      checked={skill.enabled}
                      disabled={busySkill !== null}
                      onChange={(event) => void setSkillEnabled(skill, event.target.checked)}
                      type="checkbox"
                    />
                    <span>{skill.enabled ? "已启用" : "已停用"}</span>
                  </label>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      <p
        aria-label="能力状态"
        aria-live="polite"
        className="settings-notice"
        role="status"
      >
        {notice}
      </p>
    </section>
  );
}
