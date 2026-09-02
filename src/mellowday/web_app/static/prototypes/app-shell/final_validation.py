"""One-off browser evidence collector for the final AppShell prototype validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright


BASE_URL = "http://127.0.0.1:8000/static/prototypes/app-shell/index.html"
OUTPUT = Path("docs/prototype/screenshots/app-shell-final")
RESULTS: dict[str, Any] = {"checks": [], "scenarios": []}


def check(contract: str, passed: bool, evidence: Any) -> None:
    RESULTS["checks"].append({"contract": contract, "pass": bool(passed), "evidence": evidence})


def attach_observers(page: Page) -> dict[str, list[Any]]:
    observed: dict[str, list[Any]] = {"console_errors": [], "page_errors": [], "requests": [], "bad_responses": []}
    page.on("console", lambda message: observed["console_errors"].append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: observed["page_errors"].append(str(error)))
    page.on("request", lambda request: observed["requests"].append({"method": request.method, "url": request.url}))
    page.on(
        "response",
        lambda response: observed["bad_responses"].append({"status": response.status, "url": response.url})
        if response.status >= 400
        else None,
    )
    return observed


def open_page(
    browser: Browser,
    width: int,
    height: int,
    dpr: int = 1,
    theme: str = "sky",
    route: str = "/conversation",
) -> tuple[Any, Page, dict[str, list[Any]]]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=dpr,
        reduced_motion="reduce",
        color_scheme="dark" if theme == "night" else "light",
    )
    page = context.new_page()
    observed = attach_observers(page)
    page.goto(f"{BASE_URL}?variant=A&theme={theme}#{route}", wait_until="networkidle")
    page.wait_for_function("document.querySelector('#messages')?.getAttribute('aria-busy') === 'false'")
    return context, page, observed


def geometry(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const rect = (selector) => {
            const node = document.querySelector(selector);
            if (!node || node.hidden) return null;
            const box = node.getBoundingClientRect();
            return {x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom};
          };
          return {
            viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio},
            rail: rect('.primary-rail'),
            workspace: rect('#conversation-workspace'),
            composer: rect('#composer'),
            topNavigation: document.documentElement.dataset.rail === 'narrow',
            railMode: document.documentElement.dataset.rail,
            primaryNames: [...document.querySelectorAll('[data-route]')].map((node) => ({
              text: node.textContent.trim(), title: node.title, current: node.getAttribute('aria-current'), visible: node.getClientRects().length > 0,
            })),
            overflow: {bodyX: document.documentElement.scrollWidth - innerWidth, bodyY: document.documentElement.scrollHeight - innerHeight},
          };
        }"""
    )


def contrast_metrics(page: Page) -> dict[str, float]:
    return page.evaluate(
        """() => {
          const parse = (value) => {
            if (value.startsWith('#')) {
              const compact = value.slice(1);
              const hex = compact.length === 3 ? [...compact].map((digit) => digit + digit).join('') : compact;
              return {r: parseInt(hex.slice(0, 2), 16), g: parseInt(hex.slice(2, 4), 16), b: parseInt(hex.slice(4, 6), 16), a: 1};
            }
            const values = value.match(/[\\d.]+/g).map(Number);
            if (value.startsWith('rgb')) return {r: values[0], g: values[1], b: values[2], a: values[3] ?? 1};
            const [hue, saturationPercent, lightnessPercent] = values;
            const saturation = saturationPercent / 100;
            const lightness = lightnessPercent / 100;
            const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
            const segment = hue / 60;
            const intermediate = chroma * (1 - Math.abs(segment % 2 - 1));
            const channels = segment < 1 ? [chroma, intermediate, 0]
              : segment < 2 ? [intermediate, chroma, 0]
              : segment < 3 ? [0, chroma, intermediate]
              : segment < 4 ? [0, intermediate, chroma]
              : segment < 5 ? [intermediate, 0, chroma]
              : [chroma, 0, intermediate];
            const offset = lightness - chroma / 2;
            return {r: (channels[0] + offset) * 255, g: (channels[1] + offset) * 255, b: (channels[2] + offset) * 255, a: values[3] ?? 1};
          };
          const vars = getComputedStyle(document.documentElement);
          const token = (name) => parse(vars.getPropertyValue(name).trim());
          const composite = (front, back) => ({
            r: front.r * front.a + back.r * (1 - front.a),
            g: front.g * front.a + back.g * (1 - front.a),
            b: front.b * front.a + back.b * (1 - front.a),
            a: 1,
          });
          const lum = (color) => {
            const channel = (value) => {
              value /= 255;
              return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
            };
            return .2126 * channel(color.r) + .7152 * channel(color.g) + .0722 * channel(color.b);
          };
          const ratio = (left, right) => {
            const a = lum(left), b = lum(right);
            return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
          };
          const background = token('--bg');
          const surface = composite(token('--surface-strong'), background);
          const result = {
            inkOnSurface: ratio(token('--ink'), surface),
            mutedOnSurface: ratio(token('--ink-muted'), surface),
            accentStrongOnSurface: ratio(token('--accent-strong'), surface),
            focusOnSurface: ratio(token('--accent'), surface),
            onAccentStrong: ratio(token('--on-accent'), token('--accent-strong')),
          };
          return result;
        }"""
    )


def screenshot(page: Page, filename: str) -> None:
    page.screenshot(path=str(OUTPUT / filename), full_page=True, animations="disabled")


def record_scenario(name: str, screenshot_name: str, observed: dict[str, list[Any]], details: dict[str, Any]) -> None:
    RESULTS["scenarios"].append(
        {
            "name": name,
            "screenshot": screenshot_name,
            "console_errors": observed["console_errors"],
            "page_errors": observed["page_errors"],
            "bad_responses": observed["bad_responses"],
            "non_get_requests": [request for request in observed["requests"] if request["method"] not in {"GET", "OPTIONS"}],
            "details": details,
        }
    )


def validate_viewport_matrix(browser: Browser) -> None:
    for width, height in [(1440, 900), (1200, 780), (881, 780), (880, 780), (521, 860), (520, 640)]:
        context, page, observed = open_page(browser, width, height)
        data = geometry(page)
        filename = f"sky-{width}x{height}-dpr1.png"
        screenshot(page, filename)
        desktop = width > 880
        operable = (
            data["composer"] is not None
            and data["composer"]["bottom"] <= height
            and data["overflow"]["bodyX"] <= 0
            and all(item["visible"] for item in data["primaryNames"])
        )
        check(f"viewport-{width}x{height}-boundary", data["topNavigation"] is (not desktop), data)
        check(f"viewport-{width}x{height}-operable", operable, data)
        check(f"viewport-{width}x{height}-console", not observed["console_errors"] and not observed["page_errors"], observed)
        check(f"viewport-{width}x{height}-network", not observed["bad_responses"], observed["bad_responses"])
        if width == 1440:
            semantics = page.evaluate(
                """() => {
                  const titlebar = document.querySelector('.window-bar');
                  const navigation = document.querySelector('.primary-nav');
                  const main = document.querySelector('#main-content');
                  const composer = document.querySelector('#composer');
                  const motif = document.querySelector('.theme-art__motif');
                  return {
                    readingOrder: Boolean(titlebar.compareDocumentPosition(navigation) & Node.DOCUMENT_POSITION_FOLLOWING)
                      && Boolean(navigation.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING)
                      && main.contains(composer),
                    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
                    motifAnimationSeconds: motif ? parseFloat(getComputedStyle(motif).animationDuration) : 0,
                  };
                }"""
            )
            check("document-reading-order", semantics["readingOrder"], semantics)
            check("prefers-reduced-motion-contract", semantics["reducedMotion"] and semantics["motifAnimationSeconds"] <= 0.001, semantics)
        record_scenario(f"sky {width}x{height} DPR1", filename, observed, data)
        context.close()


def validate_rail_and_routes(browser: Browser) -> None:
    context, page, observed = open_page(browser, 1440, 900)
    before = geometry(page)
    page.locator("#rail-collapse").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(80)
    dock = geometry(page)
    page.locator('[data-route="life"]').focus()
    filename = "sky-1440x900-dpr1-dock-tooltip.png"
    screenshot(page, filename)
    names_ok = all(item["text"] and item["title"] for item in dock["primaryNames"])
    check("rail-default-244", abs(before["rail"]["width"] - 244) <= 1, before)
    check("rail-explicit-dock-82", abs(dock["rail"]["width"] - 82) <= 1, dock)
    check("dock-accessible-names-state-tooltips", names_ok and sum(item["current"] == "page" for item in dock["primaryNames"]) == 1, dock["primaryNames"])
    check("dock-preserves-workspace-width", abs(before["workspace"]["width"] - dock["workspace"]["width"]) <= 1, {"before": before, "dock": dock})
    check("dock-preserves-composer-and-recents", dock["composer"] is not None and page.locator("#conversation-drawer-trigger").is_visible(), dock)

    page.set_viewport_size({"width": 880, "height": 780})
    page.wait_for_timeout(100)
    narrow = geometry(page)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(100)
    restored = geometry(page)
    check("dock-hidden-at-880", narrow["railMode"] == "narrow" and narrow["topNavigation"], narrow)
    check("dock-restored-after-wide-return", restored["railMode"] == "dock" and abs(restored["rail"]["width"] - 82) <= 1, restored)

    page.locator("#rail-collapse").focus()
    page.keyboard.press("Enter")
    page.locator('[data-route="life"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === '#/life/tasks' && document.querySelectorAll('#secondary-nav a').length === 4")
    page.wait_for_function("document.activeElement === document.querySelector('#page-title')")
    life_focus = page.evaluate("document.activeElement === document.querySelector('#page-title')")
    life_secondary = page.locator("#secondary-nav a").all_text_contents()
    life_filename = "sky-1200x780-dpr1-life-tasks.png"
    page.set_viewport_size({"width": 1200, "height": 780})
    page.wait_for_timeout(2500)
    screenshot(page, life_filename)
    check("life-default-tasks-horizontal-subnav", life_secondary[:4] == ["任务", "提醒", "日历", "笔记"] and life_focus, {"items": life_secondary, "focus": life_focus, "hash": page.url})
    page.locator('a[href="#/life/reminders"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === '#/life/reminders' && document.activeElement === document.querySelector('#page-title')")
    check("keyboard-secondary-navigation", page.url.endswith("#/life/reminders"), page.url)

    page.locator('[data-route="settings"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === '#/settings/appearance' && document.querySelectorAll('#secondary-nav a').length === 8")
    settings_secondary = page.locator("#secondary-nav a").all_text_contents()
    screenshot(page, "sky-1200x780-dpr1-settings-appearance.png")
    check("settings-default-appearance-horizontal-subnav", settings_secondary[0] == "外观" and len(settings_secondary) == 8, {"items": settings_secondary, "hash": page.url})
    page.locator('a[href="#/settings/diagnostics"]').focus()
    page.keyboard.press("Enter")
    page.go_back(wait_until="networkidle")
    check("hash-route-browser-back", page.url.endswith("#/settings/appearance"), page.url)
    check("primary-navigation-only-five", page.locator(".primary-nav [data-route]").count() == 5, page.locator(".primary-nav [data-route]").all_text_contents())
    record_scenario("rail dock and routes", filename, observed, {"before": before, "dock": dock, "narrow": narrow, "restored": restored})
    context.close()


def validate_popover_drawer_and_input(browser: Browser) -> None:
    context, page, observed = open_page(browser, 520, 640)
    page.locator("#theme-trigger").focus()
    page.keyboard.press("Enter")
    popover = page.locator("#theme-popover")
    popover_box = popover.bounding_box()
    filename = "sky-520x640-dpr1-appearance-popover.png"
    screenshot(page, filename)
    check("appearance-named-nonmodal-dialog", popover.get_attribute("role") == "dialog" and popover.get_attribute("aria-modal") == "false" and page.locator("#theme-title").inner_text() == "外观", popover_box)
    check("appearance-nearly-full-width-at-520", popover_box is not None and popover_box["width"] >= 480 and popover_box["x"] >= 12, popover_box)
    page.keyboard.press("Escape")
    check("appearance-escape-focus-return", popover.is_hidden() and page.evaluate("document.activeElement === document.querySelector('#theme-trigger')"), None)
    page.locator("#theme-trigger").click()
    page.mouse.click(4, 300)
    check("appearance-outside-click-focus-return", popover.is_hidden() and page.evaluate("document.activeElement === document.querySelector('#theme-trigger')"), None)

    input_box = page.locator("#message-input")
    input_box.focus()
    initial_variant = page.locator("html").get_attribute("data-variant")
    page.keyboard.press("ArrowRight")
    check("input-arrow-not-hijacked", page.locator("html").get_attribute("data-variant") == initial_variant, initial_variant)
    input_box.fill("拼音组合")
    before_count = page.locator("#messages > li").count()
    page.evaluate(
        """() => document.querySelector('#message-input').dispatchEvent(
          new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', isComposing: true, bubbles: true, cancelable: true})
        )"""
    )
    check("ime-composition-enter-not-sent", page.locator("#messages > li").count() == before_count and input_box.input_value() == "拼音组合", None)
    page.keyboard.press("Enter")
    page.wait_for_timeout(50)
    live_region = page.evaluate(
        """() => ({
          transcriptLive: document.querySelector('#messages').getAttribute('aria-live'),
          announcerLive: document.querySelector('#message-announcer').getAttribute('aria-live'),
          announcement: document.querySelector('#message-announcer').textContent,
        })"""
    )
    check("composer-enter-memory-only", page.locator("#messages > li").count() == before_count + 1 and not [item for item in observed["requests"] if item["method"] not in {"GET", "OPTIONS"}], observed["requests"])
    check("restrained-live-region", live_region["transcriptLive"] is None and live_region["announcerLive"] == "polite" and 0 < len(live_region["announcement"]) < 80, live_region)
    record_scenario("appearance and composer", filename, observed, {"popover": popover_box})
    context.close()

    context, page, observed = open_page(browser, 880, 780)
    trigger = page.locator("#conversation-drawer-trigger")
    trigger.focus()
    page.keyboard.press("Enter")
    drawer = page.locator("#conversation-drawer")
    filename = "sky-880x780-dpr1-modal-drawer.png"
    screenshot(page, filename)
    check("drawer-named-modal-and-background-inert", drawer.get_attribute("aria-modal") == "true" and page.evaluate("document.querySelector('#app-shell').inert"), None)
    drawer_item_box = page.locator("#drawer-conversations .recent-item").first.bounding_box()
    check("drawer-recent-items-remain-compact", drawer_item_box is not None and drawer_item_box["height"] <= 96, drawer_item_box)
    page.keyboard.press("Shift+Tab")
    wrapped_to_last = page.evaluate("document.activeElement === [...document.querySelectorAll('#conversation-drawer button')].at(-1)")
    page.keyboard.press("Tab")
    wrapped_to_first = page.evaluate("document.activeElement === document.querySelector('#conversation-drawer-close')")
    check("drawer-focus-trap", wrapped_to_last and wrapped_to_first, {"last": wrapped_to_last, "first": wrapped_to_first})
    page.keyboard.press("Escape")
    check("drawer-escape-focus-return", drawer.is_hidden() and page.evaluate("document.activeElement === document.querySelector('#conversation-drawer-trigger')"), None)
    trigger.focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    check("drawer-close-button-focus-return", drawer.is_hidden() and page.evaluate("document.activeElement === document.querySelector('#conversation-drawer-trigger')"), None)
    record_scenario("modal drawer", filename, observed, geometry(page))
    context.close()


def validate_themes_dpr_and_accessibility(browser: Browser) -> None:
    for theme in ["sky", "sakura", "mint", "night"]:
        context, page, observed = open_page(browser, 1200, 780, dpr=2, theme=theme)
        art = page.evaluate(
            """() => ({
              artCount: document.querySelectorAll('.theme-art').length,
              corner: (() => { const image = document.querySelector('.theme-art__corner'); return image ? {src: image.src, naturalWidth: image.naturalWidth, clientWidth: image.clientWidth, pointerEvents: getComputedStyle(image.parentElement).pointerEvents, ariaHidden: image.parentElement.getAttribute('aria-hidden')} : null; })(),
              emblem: (() => { const image = document.querySelector('.emblem-slot img'); return image ? {src: image.src, naturalWidth: image.naturalWidth, clientWidth: image.clientWidth} : null; })(),
              scroll: {x: document.documentElement.scrollWidth - innerWidth, y: document.documentElement.scrollHeight - innerHeight},
            })"""
        )
        contrast = contrast_metrics(page)
        required_assets = [f"{theme}-corner.webp", f"{theme}-emblem.webp"]
        asset_urls = [item["url"] for item in observed["requests"]]
        assets_ok = all(any(required in url for url in asset_urls) for required in required_assets)
        decoration_ok = art["artCount"] == 1 and art["corner"]["ariaHidden"] == "true" and art["corner"]["pointerEvents"] == "none" and art["scroll"]["x"] <= 0
        resolution_ok = art["corner"]["naturalWidth"] >= art["corner"]["clientWidth"] * 2 and art["emblem"]["naturalWidth"] >= art["emblem"]["clientWidth"] * 2
        check(f"theme-{theme}-matched-assets-dpr2", assets_ok, {"required": required_assets, "urls": asset_urls, "art": art})
        check(f"theme-{theme}-decoration-contract", decoration_ok, art)
        check(f"theme-{theme}-candidate-resolution-dpr2", resolution_ok, art)
        check(f"theme-{theme}-text-contrast", min(contrast["inkOnSurface"], contrast["mutedOnSurface"], contrast["accentStrongOnSurface"], contrast["onAccentStrong"]) >= 4.5, contrast)
        check(f"theme-{theme}-focus-contrast", contrast["focusOnSurface"] >= 3.0, contrast)
        filename = f"{theme}-1200x780-dpr2.png"
        screenshot(page, filename)
        record_scenario(f"{theme} 1200x780 DPR2", filename, observed, {"art": art, "contrast": contrast})
        context.close()

    for width, height in [(1440, 900), (881, 780), (880, 780), (521, 860), (520, 640)]:
        context, page, observed = open_page(browser, width, height, dpr=2, theme="sky")
        if width == 1440:
            page.locator("#rail-collapse").click()
        if width == 520:
            page.locator("#theme-trigger").click()
        filename = f"sky-{width}x{height}-dpr2.png"
        screenshot(page, filename)
        check(f"dpr2-{width}x{height}-console-network", not observed["console_errors"] and not observed["page_errors"] and not observed["bad_responses"], observed)
        record_scenario(f"sky {width}x{height} DPR2", filename, observed, geometry(page))
        context.close()

    context, page, observed = open_page(browser, 520, 640, dpr=2, theme="minimal")
    minimal = page.evaluate(
        """() => ({
          artCount: document.querySelectorAll('.theme-art, .emblem-slot img').length,
          background: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),
          scrollX: document.documentElement.scrollWidth - innerWidth,
        })"""
    )
    decoration_requests = [item for item in observed["requests"] if "/assets/" in item["url"]]
    filename = "minimal-520x640-dpr2.png"
    screenshot(page, filename)
    check("minimal-no-decoration-dom-or-requests", minimal["artCount"] == 0 and not decoration_requests, {"dom": minimal, "requests": decoration_requests})
    check("minimal-narrow-no-horizontal-overflow", minimal["scrollX"] <= 0, minimal)
    page.locator("#theme-trigger").click()
    slider = page.locator("#brightness-input")
    slider.fill("88")
    low_contrast = contrast_metrics(page)
    slider.fill("100")
    high_contrast = contrast_metrics(page)
    check("minimal-brightness-boundary-contrast", low_contrast["focusOnSurface"] >= 3.0 and min(low_contrast["inkOnSurface"], low_contrast["mutedOnSurface"], low_contrast["accentStrongOnSurface"], low_contrast["onAccentStrong"]) >= 4.5 and min(high_contrast["inkOnSurface"], high_contrast["mutedOnSurface"], high_contrast["accentStrongOnSurface"], high_contrast["onAccentStrong"]) >= 4.5, {"88": low_contrast, "100": high_contrast})
    record_scenario("minimal 520x640 DPR2", filename, observed, {"minimal": minimal, "contrast88": low_contrast, "contrast100": high_contrast})
    context.close()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        validate_viewport_matrix(browser)
        validate_rail_and_routes(browser)
        validate_popover_drawer_and_input(browser)
        validate_themes_dpr_and_accessibility(browser)
        browser.close()

    output_file = OUTPUT / "final-validation-results.json"
    output_file.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [item for item in RESULTS["checks"] if not item["pass"]]
    print(json.dumps({"checks": len(RESULTS["checks"]), "failed": len(failed), "failures": failed}, ensure_ascii=True, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
