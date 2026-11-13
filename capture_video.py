import csv
import os
import argparse
from playwright.sync_api import sync_playwright
import qscript


def main():
    parser = argparse.ArgumentParser(description="Capture video script with server upload and preview.")
    parser.add_argument("--server", type=str, help="URL of the web service (e.g., http://127.0.0.1:8000)")
    parser.add_argument("--zoom", action="store_true", help="Trigger programmatic zoom during recording via window.__zoomAt")
    parser.add_argument("--view-seconds", type=int, default=0,
                        help="Seconds to keep browser open for preview (>0 or 0 for Enter)")
    args = parser.parse_args()

    csv_file = "input.csv"

    if not os.path.exists(csv_file):
        print(f"Error: CSV file '{csv_file}' not found.")
        return

    video_client = None
    if args.server:
        import video_client  # lazy: requests is only needed with --server

    print("Starting processing CSV...")

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";", quotechar='"')

        for row in reader:
            company_name = row.get('Company Name')
            print(f"\nProcessing row for company: {company_name}")

            video_path, sidecar_path = qscript.CaptureVideo_Magento(
                url=row.get("URL"),
                company_name=company_name,
                language=row.get("Language"),
                country=row.get("Country"),
                postcode=row.get("Postcode"),
                city=row.get("City"),
                street=row.get("Street"),
                house_no=row.get("HouseNo"),
                trigger_zoom=args.zoom
            )

            if video_path:
                print(f"[SUCCESS] Saved video to: {video_path}")
                if sidecar_path:
                    print(f"[SUCCESS] Zoom sidecar: {sidecar_path}")

                if args.server:
                    try:
                        print(f"[UPLOAD] Uploading video to server: {args.server}...")
                        video_url = video_client.UploadVideo(
                            args.server, video_path, company_name,
                            sidecar_path=sidecar_path)
                        print(f"[UPLOAD SUCCESS] Video URL: {video_url}")

                        print("[PREVIEW] Opening Chromium for preview...")
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=False)
                            page = browser.new_page()
                            page.goto(video_url)

                            if args.view_seconds > 0:
                                page.wait_for_timeout(args.view_seconds * 1000)
                            else:
                                input("Press Enter to close the browser preview...")

                            browser.close()
                    except Exception as e:
                        print(f"[ERROR] Failed to upload or preview video for {company_name}: {e}")
            else:
                print(f"[FAILED] Could not record video for {company_name}")


if __name__ == "__main__":
    main()
