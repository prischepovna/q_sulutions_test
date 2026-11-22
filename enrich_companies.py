"""
enrich_companies.py - CLI tool to enrich company records from website Impressum.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from dotenv import load_dotenv

from impressum import (
    CompanyEnrichmentResult,
    CompanyStatus,
    process_company,
)

load_dotenv()


def get_db_connection(retries: int = 3, delay: float = 1.0):
    """Establishes connection to PostgreSQL using environment variables."""
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    dbname = os.environ.get("DB_NAME", "videos")
    user = os.environ.get("DB_USER", "video_user")
    password = os.environ.get("DB_PASSWORD", "video_pass")

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                cursor_factory=RealDictCursor,
                connect_timeout=5,
            )
        except psycopg2.OperationalError as e:
            last_err = e
            if attempt < retries:
                import time
                time.sleep(delay)

    raise last_err or RuntimeError("Failed to connect to database")


def fetch_companies_to_process(
    cur: Any,
    company_name: str | None = None,
    limit: int | None = None,
    status: int | None = None,
) -> list[dict[str, Any]]:
    """Query company records to process based on filter arguments."""
    query = "SELECT id, company_name, web, status FROM companies WHERE 1=1"
    params: list[Any] = []

    if company_name:
        query += " AND company_name = %s"
        params.append(company_name)
    elif status is not None:
        query += " AND status = %s"
        params.append(status)
    else:
        query += " AND (status IS NULL OR status <> 0)"

    query += " ORDER BY id ASC"

    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    cur.execute(query, tuple(params))
    return cur.fetchall()


def update_company_enrichment(cur: Any, company_id: int, res: CompanyEnrichmentResult) -> None:
    """Update PostgreSQL company record with enrichment results."""
    cur.execute(
        """
        UPDATE companies SET
            status = %s,
            impressum_url = %s,
            legal_name = %s,
            postal_address = %s,
            handelsregister = %s,
            vat_number = %s,
            phone = %s,
            email = %s,
            responsible_person = %s,
            raw_json = %s,
            updated_at = NOW()
        WHERE id = %s
        """,
        (
            int(res.status),
            res.impressum_url,
            res.legal_name,
            res.postal_address,
            res.handelsregister,
            res.vat_number,
            res.phone,
            res.email,
            res.responsible_person,
            Json(res.raw_json) if res.raw_json is not None else None,
            company_id,
        ),
    )


def print_company_header(comp_id: int, name: str, web: str | None) -> None:
    print("\n" + "=" * 65)
    print(f"[*] Processing [ID: {comp_id}] {name}")
    print(f"    Website: {web or '(None)'}")
    print("-" * 65)


def print_result_summary(res: CompanyEnrichmentResult) -> None:
    status_name = res.status.name
    status_val = int(res.status)
    print(f"[STATUS: {status_val} ({status_name})]")

    if res.impressum_url:
        print(f"  - Impressum URL:      {res.impressum_url}")

    if res.stats.chars_before > 0:
        s = res.stats
        print(
            f"  - Tokens:             {s.chars_before} chars (~{s.tokens_before} tok) -> "
            f"{s.chars_after} chars (~{s.tokens_after} tok) [Saved: {s.reduction_pct}%]"
        )

    if res.status == CompanyStatus.OK or res.status == CompanyStatus.ADDRESS_INCOMPLETE:
        if res.legal_name:
            print(f"  - Legal Name:         {res.legal_name}")
        if res.postal_address:
            print(f"  - Postal Address:     {res.postal_address}")
        if res.handelsregister:
            print(f"  - Handelsregister:    {res.handelsregister}")
        if res.vat_number:
            print(f"  - VAT Number:         {res.vat_number}")
        if res.phone:
            print(f"  - Phone:              {res.phone}")
        if res.email:
            print(f"  - Email:              {res.email}")
        if res.responsible_person:
            print(f"  - Responsible Person: {res.responsible_person}")

    if res.error_message:
        print(f"  - Note/Error:         {res.error_message}")


def enrich_companies(
    conn: Any,
    company_name: str | None = None,
    limit: int | None = None,
    status: int | None = None,
    api_key: str | None = None,
    model: str | None = None,
    process_fn=process_company,
) -> dict[str, int]:
    """
    Main enrichment loop:
    1. Fetches pending companies.
    2. Runs processing pipeline for each.
    3. Saves results in DB.
    4. Prints progress and final summary statistics.
    """
    with conn.cursor() as cur:
        companies = fetch_companies_to_process(cur, company_name=company_name, limit=limit, status=status)

    if not companies:
        print("No companies found matching the specified criteria.")
        return {}

    print(f"\nFound {len(companies)} company/companies to process.")

    counts: dict[str, int] = {s.name: 0 for s in CompanyStatus}
    total_processed = 0

    for comp in companies:
        comp_id = comp["id"]
        c_name = comp["company_name"]
        web_url = comp.get("web")

        print_company_header(comp_id, c_name, web_url)

        # Run process
        result = process_fn(web_url, company_name=c_name, api_key=api_key, model=model)

        # Update in database
        with conn.cursor() as cur:
            update_company_enrichment(cur, comp_id, result)
        conn.commit()

        print_result_summary(result)
        counts[result.status.name] = counts.get(result.status.name, 0) + 1
        total_processed += 1

    # Print summary table
    print("\n" + "=" * 65)
    print("ENRICHMENT SUMMARY")
    print("=" * 65)
    print(f"Total companies processed: {total_processed}")
    for status_item in CompanyStatus:
        print(f"  - Status {int(status_item)} ({status_item.name}): {counts.get(status_item.name, 0)}")
    print("=" * 65 + "\n")

    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich company records from their Impressum pages using DeepSeek API."
    )
    parser.add_argument(
        "--company",
        dest="company_name",
        type=str,
        default=None,
        help="Process only the specified company by name.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N companies.",
    )
    parser.add_argument(
        "--status",
        type=int,
        default=None,
        help="Process only companies with the specified status code (e.g. 1).",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Warning: DEEPSEEK_API_KEY is not set. DeepSeek calls will fail unless provided.")

    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Database connection error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        enrich_companies(
            conn=conn,
            company_name=args.company_name,
            limit=args.limit,
            status=args.status,
            api_key=api_key,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
