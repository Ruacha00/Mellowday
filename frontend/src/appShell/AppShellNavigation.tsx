import { lazy, Suspense, type RefObject } from "react";

import type { DesktopWindowControls } from "./desktopCapability";
import {
  lifeDestinations,
  pageDetails,
  placeholderCards,
  primaryDestinations,
  settingsDestinations,
} from "./navigationModel";
import type { AppRoute } from "./routeState";
import type { WideNavigation } from "./wideNavigationState";

const ManagementDetails = lazy(() => import("./ManagementDetails"));

export function DesktopTitleBarControls({
  controls,
}: {
  controls: DesktopWindowControls;
}) {
  return (
    <div aria-label="窗口控制" className="window-controls" role="group">
      <button aria-label="最小化窗口" onClick={() => controls.minimize()} type="button">
        <span aria-hidden="true">—</span>
      </button>
      <button
        aria-label="切换最大化窗口"
        onClick={() => controls.toggleMaximize()}
        type="button"
      >
        <span aria-hidden="true">□</span>
      </button>
      <button aria-label="关闭窗口" onClick={() => controls.close()} type="button">
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}

export function ProductNavigation({
  route,
  wideNavigation,
}: {
  route: AppRoute;
  wideNavigation: WideNavigation;
}) {
  return (
    <nav aria-label="产品区域" className="product-navigation">
      <div className="rail-identity" aria-hidden={wideNavigation === "dock"}>
        <span aria-hidden="true" className="rail-emblem">☁</span>
        <strong>Mellowday</strong>
        <span>慢慢过日子，也好好记得你。</span>
      </div>
      <div className="primary-links">
        {primaryDestinations.map((destination) => (
          <a
            aria-current={route.area === destination.area ? "page" : undefined}
            className="primary-link"
            href={destination.hash}
            key={destination.area}
            title={destination.label}
          >
            <span aria-hidden="true" className="primary-icon">{destination.icon}</span>
            <span className="primary-label">{destination.label}</span>
          </a>
        ))}
      </div>
    </nav>
  );
}

export function PageHeading({
  onOpenRecent,
  recentTriggerRef,
  route,
}: {
  onOpenRecent: () => void;
  recentTriggerRef: RefObject<HTMLButtonElement | null>;
  route: AppRoute;
}) {
  const page = pageDetails(route);
  return (
    <header className="page-heading">
      <div>
        <p className="page-kicker">{page.kicker}</p>
        <h1 tabIndex={-1}>{page.title}</h1>
        <p>{page.note}</p>
      </div>
      {route.area === "conversation" ? (
        <button
          aria-haspopup="dialog"
          className="recent-drawer-trigger"
          onClick={onOpenRecent}
          ref={recentTriggerRef}
          type="button"
        >
          最近对话
        </button>
      ) : null}
    </header>
  );
}

export function ManagementPage({ route }: { route: AppRoute }) {
  const destinations = route.area === "life"
    ? lifeDestinations
    : route.area === "settings"
      ? settingsDestinations
      : [];
  const activeDestination = destinations.find(
    (destination) => destination.hash === route.hash,
  );

  return (
    <section className="management-page">
      {destinations.length > 0 ? (
        <nav
          aria-label={`${route.area === "life" ? "生活" : "设置"}二级导航`}
          className="secondary-navigation"
        >
          {destinations.map((destination) => (
            <a
              aria-current={destination.hash === route.hash ? "page" : undefined}
              href={destination.hash}
              key={destination.hash}
            >
              {destination.label}
            </a>
          ))}
        </nav>
      ) : null}
      <Suspense fallback={<p className="management-loading">正在载入页面内容…</p>}>
        <ManagementDetails
          cards={placeholderCards(route)}
          description={activeDestination?.description ?? pageDetails(route).description}
        />
      </Suspense>
    </section>
  );
}
