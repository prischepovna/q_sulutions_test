import os
import time
import glob
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PATH_TO_VIDEO_FOLDER = "./video"
PATH_TO_DEBUG_FOLDER = "./debug"

# DuckDuckGo меняет разметку выдачи, поэтому ищем первый результат по нескольким селекторам
RESULT_SELECTOR = ", ".join([
    'a[data-testid="result-title-a"]',
    'article[data-testid="result"] h2 a',
    'a.result__a',
    '#links h2 a',
])

INJECT_EFFECTS_JS = """
(() => {
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

    document.addEventListener('mousemove', (e) => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
    }, true);


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
    `;
    document.head.appendChild(style);


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
})();
"""


def CaptureVideo_Magento(url, company_name, language, country, postcode, city, street, house_no):
    os.makedirs(PATH_TO_VIDEO_FOLDER, exist_ok=True)

    initial_files = set(os.listdir(PATH_TO_VIDEO_FOLDER))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        context = browser.new_context(
            record_video_dir=PATH_TO_VIDEO_FOLDER,
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720}
        )

        context.add_init_script(INJECT_EFFECTS_JS)

        page = context.new_page()

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

            query = f"Magento developer in {city}"
            for char in query:
                page.keyboard.type(char, delay=120)

            page.keyboard.press("Enter")

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
            return None

        context.close()
        browser.close()

    final_files = set(os.listdir(PATH_TO_VIDEO_FOLDER))
    new_files = [f for f in (final_files - initial_files) if f.endswith(".webm")]

    if not new_files:
        webm_files = glob.glob(os.path.join(PATH_TO_VIDEO_FOLDER, "*.webm"))
        if not webm_files:
            return None
        latest_file = max(webm_files, key=os.path.getctime)
    else:
        latest_file = os.path.join(PATH_TO_VIDEO_FOLDER, new_files[0])

    target_path = os.path.join(PATH_TO_VIDEO_FOLDER, f"{company_name}.webm")
    if os.path.exists(target_path):
        os.remove(target_path)

    os.rename(latest_file, target_path)

    return os.path.abspath(target_path)