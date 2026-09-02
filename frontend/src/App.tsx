import { lazy, Suspense } from "react";

const MigrationDetails = lazy(() => import("./MigrationDetails"));

export function App() {
  return (
    <main className="migration-shell">
      <section aria-labelledby="migration-title" className="migration-card">
        <p className="eyebrow">Temporary migration entry</p>
        <h1 id="migration-title">Mellowday React migration</h1>
        <p>
          The production React and TypeScript toolchain is connected. The
          existing Conversation Surface remains available at the main entry.
        </p>
        <Suspense fallback={<p>Loading migration details…</p>}>
          <MigrationDetails />
        </Suspense>
      </section>
    </main>
  );
}
