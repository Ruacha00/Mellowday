export interface DesktopWindowControls {
  close(): void;
  minimize(): void;
  toggleMaximize(): void;
}

declare global {
  interface Window {
    mellowdayDesktop?: {
      windowControls?: DesktopWindowControls;
    };
  }
}

export function getDesktopWindowControls(): DesktopWindowControls | null {
  const controls = window.mellowdayDesktop?.windowControls;
  return controls !== undefined &&
    typeof controls.minimize === "function" &&
    typeof controls.toggleMaximize === "function" &&
    typeof controls.close === "function"
    ? controls
    : null;
}
