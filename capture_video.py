import csv
import os
import qscript


def main():
    csv_file = "input.csv"

    if not os.path.exists(csv_file):
        print(f"Error: CSV file '{csv_file}' not found.")
        return

    print("Starting processing CSV...")

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";", quotechar='"')

        for row in reader:
            print(f"\nProcessing row for company: {row.get('Company Name')}")
            video_path = qscript.CaptureVideo_Magento(
                url=row.get("URL"),
                company_name=row.get("Company Name"),
                language=row.get("Language"),
                country=row.get("Country"),
                postcode=row.get("Postcode"),
                city=row.get("City"),
                street=row.get("Street"),
                house_no=row.get("HouseNo")
            )

            if video_path:
                print(f"[SUCCESS] Saved video to: {video_path}")
            else:
                print(f"[FAILED] Could not record video for {row.get('Company Name')}")


if __name__ == "__main__":
    main()