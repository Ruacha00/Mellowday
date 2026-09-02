import { useCallback, useEffect, useRef, useState } from "react";

import type { AuditService } from "../services/auditApi";
import type { RuntimeEvent } from "../services/conversationApi";
import { LatestRequest } from "../services/requestLifecycle";

function formatDateTime(value: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value * 1_000));
}

function recordContext(record: RuntimeEvent): string {
  const tool = record.details.tool;
  if (typeof tool === "string" && tool.length > 0) return tool;
  return record.conversationId ?? "Agent Core";
}

export function OperationRecordsPage({ service }: { service: AuditService }) {
  const [records, setRecords] = useState<RuntimeEvent[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const request = useRef(new LatestRequest());
  const mounted = useRef(false);

  const loadRecords = useCallback(() => {
    if (!mounted.current) return;
    setLoadState("loading");
    void request.current.run((signal) => service.listRecords(signal))
      .then((result) => {
        if (!mounted.current || result.status !== "current") return;
        setRecords([...result.value].reverse());
        setLoadState("ready");
      })
      .catch(() => {
        if (mounted.current) setLoadState("error");
      });
  }, [service]);

  useEffect(() => {
    mounted.current = true;
    loadRecords();
    return () => {
      mounted.current = false;
      request.current.cancel();
    };
  }, [loadRecords]);

  return (
    <section aria-labelledby="operation-records-title" className="operation-records-page">
      <header className="settings-page-intro">
        <span>本地审计事实</span>
        <h2 id="operation-records-title">操作记录</h2>
        <p>按后端记录展示动作、确认、失败与可用撤销信息；不会补写工具内部过程。</p>
      </header>
      <section aria-labelledby="operation-list-title" className="operation-list-section">
        <header className="settings-section-heading">
          <div><span>最近记录</span><h3 id="operation-list-title">审计事件</h3></div>
          <div className="settings-heading-actions">
            <span>{records.length}</span>
            <button className="quiet-button" onClick={loadRecords} type="button">刷新</button>
          </div>
        </header>
        {loadState === "loading" ? (
          <p className="settings-state-inline" role="status">正在加载操作记录…</p>
        ) : loadState === "error" ? (
          <div className="settings-state-inline" role="alert">
            <p>操作记录加载失败。</p>
            <button className="quiet-button" onClick={loadRecords} type="button">重试</button>
          </div>
        ) : records.length === 0 ? (
          <p className="settings-state-inline">还没有操作记录。</p>
        ) : (
          <ol className="operation-list">
            {records.map((record) => (
              <li className="operation-record" key={`${record.sequence}-${record.type}`}>
                <div className="operation-record-heading">
                  <code>{record.type}</code>
                  <time dateTime={new Date(record.occurredAt * 1_000).toISOString()}>
                    {formatDateTime(record.occurredAt)}
                  </time>
                </div>
                <p>{recordContext(record)}</p>
                {Object.keys(record.details).length === 0 ? null : (
                  <details>
                    <summary>查看记录详情</summary>
                    <pre>{JSON.stringify(record.details, null, 2)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </section>
  );
}
