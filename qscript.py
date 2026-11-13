import os
import time
import glob
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PATH_TO_VIDEO_FOLDER = "./video"
PATH_TO_DEBUG_FOLDER = "./debug"

# Zoom defaults (written into the sidecar)
VIEWPORT_W, VIEWPORT_H = 1280, 720
VIDEO_FPS = 25
ZOOM_FACTOR = 2.0
RAMP_SEC = 0.5

# DuckDuckGo меняет разметку выдачи, поэтому ищем первый результат по нескольким селекторам
RESULT_SELECTOR = ", ".join([
    'a[data-testid="result-title-a"]',
    'article[data-testid="result"] h2 a',
    'a.result__a',
    '#links h2 a',
])

INJECT_EFFECTS_JS = """
(() => {
    // ── Custom cursor ────────────────────────────────────────────
    const oldCursor = document.getElementById('__custom_svg_cursor');
    if (oldCursor) oldCursor.remove();

    const cursor = document.createElement('div');
    cursor.id = '__custom_svg_cursor';
    cursor.style.position = 'fixed';
    cursor.style.top = '360px'; 
    cursor.style.left = '640px'; 
    cursor.style.width = '36px';
    cursor.style.height = '36px';
    cursor.style.zIndex = '2147483647';
    cursor.style.pointerEvents = 'none';
    cursor.innerHTML = `
        <svg width="36" height="36" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 3L25 15L15 18L10 27L5 3Z" fill="white" stroke="black" stroke-width="2.5" stroke-linejoin="round"/>
        </svg>
    `;
    // жёлтая подсветка вокруг курсора: лежит внутри cursor, поэтому двигается вместе с ним
    const highlight = document.createElement('div');
    highlight.style.position = 'absolute';
    highlight.style.width = '60px';
    highlight.style.height = '60px';
    highlight.style.left = '-24px';   // центр круга совпадает с кончиком стрелки
    highlight.style.top = '-27px';
    highlight.style.borderRadius = '50%';
    highlight.style.backgroundColor = 'rgba(255, 213, 79, 0.6)';
    highlight.style.pointerEvents = 'none';
    highlight.style.zIndex = '-1';   // круг строго ПОД стрелкой
    cursor.insertBefore(highlight, cursor.firstChild);   // под стрелкой, а не поверх неё

    document.documentElement.appendChild(cursor);

    // ── Mouse position tracker ───────────────────────────────────
    window.__mouseX = 640;
    window.__mouseY = 360;

    document.addEventListener('mousemove', (e) => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
        window.__mouseX = e.clientX;
        window.__mouseY = e.clientY;
    }, true);

    // ── Click ripple ─────────────────────────────────────────────
    document.addEventListener('click', (e) => {
        const ripple = document.createElement('div');
        ripple.style.position = 'fixed';
        ripple.style.left = (e.clientX - 20) + 'px';
        ripple.style.top = (e.clientY - 20) + 'px';
        ripple.style.width = '40px';
        ripple.style.height = '40px';
        ripple.style.borderRadius = '50%';
        ripple.style.border = '2px solid rgba(0, 122, 255, 0.9)';
        ripple.style.backgroundColor = 'rgba(0, 122, 255, 0.3)';
        ripple.style.zIndex = '2147483646';
        ripple.style.pointerEvents = 'none';
        ripple.style.animation = '__ripple_anim 0.6s ease-out forwards';

        document.documentElement.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
    }, true);

    const style = document.createElement('style');
    style.textContent = `
        @keyframes __ripple_anim {
            0% { transform: scale(0.4); opacity: 1; }
            100% { transform: scale(1.8); opacity: 0; }
        }
        @keyframes __zoom_ring_pulse {
            0%   { transform: scale(1);   opacity: 0.9; }
            50%  { transform: scale(1.1); opacity: 0.6; }
            100% { transform: scale(1);   opacity: 0.9; }
        }
    `;
    document.head.appendChild(style);

    // ── Callout ──────────────────────────────────────────────────
    window.ShowCallout = (text, bgColor = '#FFFF99', textColor = '#000000', fadeMs = 2000) => {
        const callout = document.createElement('div');
        callout.innerText = text;
        callout.style.position = 'fixed';
        callout.style.bottom = '30px';
        callout.style.right = '30px';
        callout.style.backgroundColor = bgColor;
        callout.style.color = textColor;
        callout.style.padding = '12px 18px';
        callout.style.border = '1px solid #ccc';
        callout.style.borderRadius = '6px';
        callout.style.fontSize = '16pt';
        callout.style.fontFamily = 'sans-serif';
        callout.style.zIndex = '2147483647';
        callout.style.boxShadow = '0px 4px 12px rgba(0,0,0,0.3)';
        callout.style.transition = `opacity ${fadeMs}ms ease-in-out`;
        callout.style.opacity = '0';

        document.documentElement.appendChild(callout);
        setTimeout(() => callout.style.opacity = '1', 50);

        setTimeout(() => {
            callout.style.opacity = '0';
            setTimeout(() => callout.remove(), fadeMs);
        }, fadeMs + 1000);
    };

    // ── Zoom indicator ring ──────────────────────────────────────
    window.__zoomActive = false;
    let zoomRing = null;

    function showZoomRing() {
        if (zoomRing) zoomRing.remove();
        zoomRing = document.createElement('div');
        zoomRing.id = '__zoom_ring';
        zoomRing.style.position = 'fixed';
        zoomRing.style.width = '80px';
        zoomRing.style.height = '80px';
        zoomRing.style.left = (window.__mouseX - 40) + 'px';
        zoomRing.style.top = (window.__mouseY - 40) + 'px';
        zoomRing.style.borderRadius = '50%';
        zoomRing.style.border = '3px solid rgba(255, 60, 60, 0.8)';
        zoomRing.style.backgroundColor = 'rgba(255, 60, 60, 0.15)';
        zoomRing.style.pointerEvents = 'none';
        zoomRing.style.zIndex = '2147483646';
        zoomRing.style.animation = '__zoom_ring_pulse 1s ease-in-out infinite';
        document.documentElement.appendChild(zoomRing);

        // ring follows cursor
        document.addEventListener('mousemove', moveZoomRing, true);
    }

    function moveZoomRing(e) {
        if (zoomRing) {
            zoomRing.style.left = (e.clientX - 40) + 'px';
            zoomRing.style.top = (e.clientY - 40) + 'px';
        }
    }

    function hideZoomRing() {
        document.removeEventListener('mousemove', moveZoomRing, true);
        if (zoomRing) { zoomRing.remove(); zoomRing = null; }
    }

    // ── Zoom toggle (programmatic hook) ──────────────────────────
    // __onZoomEvent is exposed from Python via page.expose_function.
    // It may not be available yet when the init script runs, so we
    // guard every call.  The function is async (returns a Promise)
    // because expose_function callbacks are always async in Playwright.

    window.__zoomAt = (x, y) => {
        window.__zoomActive = !window.__zoomActive;
        const evType = window.__zoomActive ? 'in' : 'out';

        if (window.__zoomActive) {
            showZoomRing();
        } else {
            hideZoomRing();
        }

        // send event to Python
        if (typeof window.__onZoomEvent === 'function') {
            window.__onZoomEvent(JSON.stringify({x: Math.round(x), y: Math.round(y), type: evType}));
        }
    };

    // ── F5 hotkey ────────────────────────────────────────────────
    document.addEventListener('keydown', (e) => {
        if (e.key === 'F5') {
            e.preventDefault();
            e.stopPropagation();
            window.__zoomAt(window.__mouseX, window.__mouseY);
        }
    }, true);
})();
"""


def CaptureVideo_Magento(url, company_name, language, country, postcode, city, street, house_no, trigger_zoom=False):
    """Record a browser automation video and return (video_path, sidecar_path | None).

    The sidecar (.zoom.json) is written only when at least one zoom event
    was captured during the session.
    """
    os.makedirs(PATH_TO_VIDEO_FOLDER, exist_ok=True)

    initial_files = set(os.listdir(PATH_TO_VIDEO_FOLDER))

    # Zoom event accumulator
    zoom_events = []
    t0 = None   # set right after context creation

    def _on_zoom_event(payload_json):
        """Callback invoked from JS via page.expose_function."""
        ev = json.loads(payload_json)
        ev["t"] = round(time.time() - t0, 3)
        zoom_events.append(ev)
        kind = ev["type"]
        print(f"[ZOOM] {kind} at ({ev['x']}, {ev['y']}) t={ev['t']:.3f}s")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        context = browser.new_context(
            record_video_dir=PATH_TO_VIDEO_FOLDER,
            record_video_size={"width": VIEWPORT_W, "height": VIEWPORT_H},
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H}
        )
        t0 = time.time()   # ← reference point for event timestamps

        context.add_init_script(INJECT_EFFECTS_JS)

        page = context.new_page()

        # Expose Python callback so JS __zoomAt can send events back
        page.expose_function("__onZoomEvent", _on_zoom_event)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)

            page.evaluate(INJECT_EFFECTS_JS)

            page.evaluate("""
                if (window.ShowCallout) {
                    window.ShowCallout('Searching for Magento developer...', '#FFFF99', '#000000', 1500);
                }
            """)

            search_box = page.wait_for_selector('textarea[name="q"]')
            box = search_box.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=40)

            page.wait_for_timeout(300)
            search_box.click()

            if trigger_zoom:
                page.evaluate("window.__zoomAt && window.__zoomAt(window.__mouseX, window.__mouseY)")

            query = f"Magento developer in {city}"
            for char in query:
                page.keyboard.type(char, delay=120)

            page.keyboard.press("Enter")

            if trigger_zoom:
                page.evaluate("window.__zoomAt && window.__zoomAt(window.__mouseX, window.__mouseY)")

            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            first_result = None
            try:
                first_result = page.wait_for_selector(RESULT_SELECTOR, timeout=30000)
            except PlaywrightTimeoutError:
                # Капча, страница согласия или другая разметка: не роняем запись,
                # сохраняем скриншот для отладки и просто завершаем ролик.
                os.makedirs(PATH_TO_DEBUG_FOLDER, exist_ok=True)
                shot = os.path.join(PATH_TO_DEBUG_FOLDER, f"{company_name}_no_results.png")
                page.screenshot(path=shot)
                print(f"[WARN] Search results not found for {company_name}; screenshot: {shot}")

            if first_result:
                res_box = first_result.bounding_box()
                if res_box:
                    page.mouse.move(res_box["x"] + res_box["width"] / 2, res_box["y"] + res_box["height"] / 2, steps=30)
                page.wait_for_timeout(500)
                first_result.click()

            page.wait_for_timeout(2000)

        except Exception as e:
            print(f"Error during automation for {company_name}: {e}")
            context.close()
            browser.close()
            return None, None

        context.close()
        browser.close()

    final_files = set(os.listdir(PATH_TO_VIDEO_FOLDER))
    new_files = [f for f in (final_files - initial_files) if f.endswith(".webm")]

    if not new_files:
        webm_files = glob.glob(os.path.join(PATH_TO_VIDEO_FOLDER, "*.webm"))
        if not webm_files:
            return None, None
        latest_file = max(webm_files, key=os.path.getctime)
    else:
        latest_file = os.path.join(PATH_TO_VIDEO_FOLDER, new_files[0])

    target_path = os.path.join(PATH_TO_VIDEO_FOLDER, f"{company_name}.webm")
    if os.path.exists(target_path):
        os.remove(target_path)

    os.rename(latest_file, target_path)

    sidecar_path = None
    if zoom_events:
        sidecar_path = os.path.join(
            PATH_TO_VIDEO_FOLDER, f"{company_name}.zoom.json")
        sidecar_data = {
            "viewport": {"width": VIEWPORT_W, "height": VIEWPORT_H},
            "fps": VIDEO_FPS,
            "zoom_factor": ZOOM_FACTOR,
            "ramp_sec": RAMP_SEC,
            "events": zoom_events,
        }
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(sidecar_data, f, indent=2)
        print(f"[ZOOM] Sidecar written: {sidecar_path}  ({len(zoom_events)} events)")
        sidecar_path = os.path.abspath(sidecar_path)

    return os.path.abspath(target_path), sidecar_path
