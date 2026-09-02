import { useCallback, useEffect, useRef, useState } from "react";

import type { RuntimeEvent } from "../services/conversationApi";
import type {
  DiagnosticLog,
  DiagnosticsService,
  DiagnosticsStatus,
} from "../services/diagnosticsApi";
import { LatestRequest } from "../services/requestLifecycle";

const POLL_INTERVAL_MS = 1_500;

interface DiagnosticFilters {
  eventConversation: string;
  eventType: string;
  logLevel: string;
  logSearch: string;
}

function formatDateTime(value: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value * 1_000));
}

function providerHealthLabel(state: string | undefined): string {
  if (state === "available") return "可用";
  if (state === "not_checked" || state === undefined) return "未检查";
  return state;
}

function mergeBySequence<T extends { sequence: number }>(
  current: T[],
  incoming: T[],
): T[] {
  const records = new Map(current.map((record) => [record.sequence, record]));
  for (const record of incoming) records.set(record.sequence, record);
  return [...records.values()].sort((left, right) => left.sequence - right.sequence);
}

export function DiagnosticsPage({ service }: { service: DiagnosticsService }) {
  const [status, setStatus] = useState<DiagnosticsStatus | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [logs, setLogs] = useState<DiagnosticLog[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [eventType, setEventType] = useState("");
  const [eventConversation, setEventConversation] = useState("");
  const [logLevel, setLogLevel] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const request = useRef(new LatestRequest());
  const mounted = useRef(false);
  const hasReadyData = useRef(false);
  const eventCursor = useRef(0);
  const logCursor = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const draftFilters = useRef<DiagnosticFilters>({
    eventConversation: "",
    eventType: "",
    logLevel: "",
    logSearch: "",
  });
  const appliedFilters = useRef<DiagnosticFilters>(draftFilters.current);
  draftFilters.current = { eventConversation, eventType, logLevel, logSearch };

  const loadDiagnostics = useCallback((incremental: boolean, manual: boolean) => {
    if (!mounted.current) return;
    if (manual) {
      appliedFilters.current = draftFilters.current;
      setRefreshing(true);
      setAnnouncement("");
    }
    const filters = appliedFilters.current;
    void request.current.run(async (signal) => {
      const [nextStatus, eventPage, logPage] = await Promise.all([
        service.getStatus(signal),
        service.listEvents({
          since: incremental ? eventCursor.current : 0,
          type: filters.eventType,
          conversationId: filters.eventConversation,
        }, signal),
        service.listLogs({
          since: incremental ? logCursor.current : 0,
          level: filters.logLevel,
          search: filters.logSearch,
        }, signal),
      ]);
      return { nextStatus, eventPage, logPage };
    }).then((result) => {
      if (!mounted.current || result.status !== "current") return;
      setStatus(result.value.nextStatus);
      setEvents((current) => incremental
        ? mergeBySequence(current, result.value.eventPage.events)
        : result.value.eventPage.events);
      setLogs((current) => incremental
        ? mergeBySequence(current, result.value.logPage.logs)
        : result.value.logPage.logs);
      eventCursor.current = result.value.eventPage.cursor;
      logCursor.current = result.value.logPage.cursor;
      hasReadyData.current = true;
      setLoadState("ready");
      setRefreshFailed(false);
      setRefreshing(false);
      if (manual) setAnnouncement("诊断数据已更新。");
    }).catch(() => {
      if (!mounted.current) return;
      setRefreshing(false);
      if (hasReadyData.current) {
        setRefreshFailed(true);
      } else {
        setLoadState("error");
      }
    });
  }, [service]);

  useEffect(() => {
    mounted.current = true;
    heading.current?.focus();
    loadDiagnostics(false, false);
    const poll = window.setInterval(() => loadDiagnostics(true, false), POLL_INTERVAL_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(poll);
      request.current.cancel();
    };
  }, [loadDiagnostics]);

  const refresh = () => loadDiagnostics(false, true);

  return (
    <section aria-labelledby="diagnostics-title" className="diagnostics-page">
      <header className="settings-page-intro">
        <span>本地运行事实</span>
        <h2 id="diagnostics-title" ref={heading} tabIndex={-1}>诊断</h2>
        <p>通过后端状态、运行事件和本地日志检查当前服务，不使用人格化表达。</p>
      </header>

      {loadState === "loading" ? (
        <p className="settings-state-inline diagnostics-state" role="status">
          正在加载诊断数据…
        </p>
      ) : loadState === "error" ? (
        <div className="settings-state-inline diagnostics-state" role="alert">
          <p>诊断数据加载失败。</p>
          <button className="quiet-button" onClick={refresh} type="button">重试</button>
        </div>
      ) : (
        <>
          <section aria-labelledby="service-status-title" className="diagnostics-section">
            <header className="settings-section-heading">
              <div><span>当前快照</span><h3 id="service-status-title">服务状态</h3></div>
              <button
                className="quiet-button"
                disabled={refreshing}
                onClick={refresh}
                type="button"
              >
                {refreshing ? "正在刷新…" : "刷新诊断数据"}
              </button>
            </header>
            {refreshFailed ? (
              <p className="diagnostics-update-error" role="alert">
                实时诊断更新暂时不可用，当前仍显示上次成功结果。
              </p>
            ) : null}
            <p className="visually-hidden" role="status">{announcement}</p>
            <dl className="diagnostics-summary">
              <div><dt>后端</dt><dd>{status?.backend.ok ? "正常" : "不可用"}</dd></div>
              <div>
                <dt>模型提供方</dt>
                <dd>{status?.provider.name} · {providerHealthLabel(status?.provider.health?.state)}</dd>
              </div>
              <div><dt>会话</dt><dd>{status?.sessions ?? 0}</dd></div>
              <div><dt>待处理确认</dt><dd>{status?.pendingConfirmations ?? 0}</dd></div>
              <div><dt>工具</dt><dd>{status?.tools ?? 0}</dd></div>
              <div><dt>技能</dt><dd>{status?.skills ?? 0}</dd></div>
            </dl>
          </section>

          <div className="diagnostics-grid">
            <section aria-labelledby="runtime-events-title" className="diagnostics-section">
              <header className="settings-section-heading diagnostics-section-heading">
                <div><span>结构化事实</span><h3 id="runtime-events-title">运行事件</h3></div>
                <span>{events.length}</span>
              </header>
              <div className="diagnostics-filters">
                <label>
                  <span>事件类型</span>
                  <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
                    <option value="">全部事件类型</option>
                    <option value="turn_completed">turn_completed</option>
                    <option value="provider_failed">provider_failed</option>
                    <option value="confirmation_pending">confirmation_pending</option>
                    <option value="confirmation_accepted">confirmation_accepted</option>
                    <option value="confirmation_rejected">confirmation_rejected</option>
                  </select>
                </label>
                <label>
                  <span>会话</span>
                  <input
                    autoComplete="off"
                    value={eventConversation}
                    onChange={(event) => setEventConversation(event.target.value)}
                  />
                </label>
              </div>
              {events.length === 0 ? (
                <p className="settings-state-inline">没有符合条件的运行事件。</p>
              ) : (
                <ol className="diagnostics-list">
                  {events.map((event) => (
                    <li key={event.sequence}>
                      <div className="diagnostics-record-heading">
                        <code>{event.type}</code>
                        <time dateTime={new Date(event.occurredAt * 1_000).toISOString()}>
                          {formatDateTime(event.occurredAt)}
                        </time>
                      </div>
                      <p>{event.conversationId || "Agent Core"}</p>
                      {Object.keys(event.details).length === 0 ? null : (
                        <details>
                          <summary>查看事件详情</summary>
                          <pre>{JSON.stringify(event.details, null, 2)}</pre>
                        </details>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section aria-labelledby="runtime-logs-title" className="diagnostics-section">
              <header className="settings-section-heading diagnostics-section-heading">
                <div><span>本地进程输出</span><h3 id="runtime-logs-title">运行日志</h3></div>
                <span>{logs.length}</span>
              </header>
              <div className="diagnostics-filters">
                <label>
                  <span>最低日志级别</span>
                  <select value={logLevel} onChange={(event) => setLogLevel(event.target.value)}>
                    <option value="">全部级别</option>
                    <option value="WARNING">WARNING</option>
                    <option value="ERROR">ERROR</option>
                    <option value="CRITICAL">CRITICAL</option>
                  </select>
                </label>
                <label>
                  <span>日志搜索</span>
                  <input
                    autoComplete="off"
                    type="search"
                    value={logSearch}
                    onChange={(event) => setLogSearch(event.target.value)}
                  />
                </label>
              </div>
              {logs.length === 0 ? (
                <p className="settings-state-inline">没有符合条件的运行日志。</p>
              ) : (
                <ol className="diagnostics-list">
                  {logs.map((log) => (
                    <li key={log.sequence}>
                      <div className="diagnostics-record-heading">
                        <code>{log.level}</code>
                        <time dateTime={new Date(log.occurredAt * 1_000).toISOString()}>
                          {formatDateTime(log.occurredAt)}
                        </time>
                      </div>
                      <p className="diagnostics-logger">{log.logger}</p>
                      <pre className="diagnostics-log-message">{log.message}</pre>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        </>
      )}
    </section>
  );
}
