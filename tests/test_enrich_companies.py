"""
tests/test_enrich_companies.py - Unit tests for enrich_companies.py CLI tool.
"""

from unittest.mock import MagicMock, patch
import pytest

from impressum import (
    CompanyEnrichmentResult,
    CompanyStatus,
    TokenStats,
)
from enrich_companies import (
    parse_args,
    fetch_companies_to_process,
    update_company_enrichment,
    enrich_companies,
)


class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.company_name is None
        assert args.limit is None
        assert args.status is None

    def test_custom_args(self):
        args = parse_args(["--company", "nutrimmun GmbH", "--limit", "5", "--status", "1"])
        assert args.company_name == "nutrimmun GmbH"
        assert args.limit == 5
        assert args.status == 1


class TestFetchCompanies:
    def test_default_query_filters_pending_or_non_zero(self):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [{"id": 1, "company_name": "TestCorp", "web": "http://test.com", "status": None}]

        res = fetch_companies_to_process(mock_cur)
        query = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]

        assert "status IS NULL OR status <> 0" in query
        assert "ORDER BY id ASC" in query
        assert len(params) == 0
        assert len(res) == 1

    def test_filter_by_company(self):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []

        fetch_companies_to_process(mock_cur, company_name="nutrimmun GmbH")
        query = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]

        assert "company_name = %s" in query
        assert params == ("nutrimmun GmbH",)

    def test_filter_by_status(self):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []

        fetch_companies_to_process(mock_cur, status=1)
        query = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]

        assert "status = %s" in query
        assert params == (1,)

    def test_limit(self):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []

        fetch_companies_to_process(mock_cur, limit=3)
        query = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]

        assert "LIMIT %s" in query
        assert 3 in params


class TestUpdateCompanyEnrichment:
    def test_update_record(self):
        mock_cur = MagicMock()
        result = CompanyEnrichmentResult(
            status=CompanyStatus.OK,
            impressum_url="http://nutrimmun.de/impressum",
            legal_name="nutrimmun GmbH",
            postal_address="Ludgeriplatz 2, 48153 Münster",
            handelsregister="HRB 2652",
            vat_number="DE126116348",
            phone="+49 251 12345",
            email="info@nutrimmun.de",
            responsible_person="Geschäftsführer",
            raw_json={"legal_name": "nutrimmun GmbH"},
            stats=TokenStats(chars_before=1000, chars_after=500, tokens_before=250, tokens_after=125, reduction_pct=50.0),
        )

        update_company_enrichment(mock_cur, company_id=42, res=result)

        assert mock_cur.execute.called
        query = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]

        assert "UPDATE companies SET" in query
        assert "status = %s" in query
        assert "WHERE id = %s" in query
        assert params[0] == 0  # status int
        assert params[1] == "http://nutrimmun.de/impressum"
        assert params[2] == "nutrimmun GmbH"
        assert params[-1] == 42  # company_id


class TestEnrichCompaniesLoop:
    def test_enrich_multiple_companies(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchall.return_value = [
            {"id": 1, "company_name": "nutrimmun GmbH", "web": "http://nutrimmun.de", "status": None},
            {"id": 2, "company_name": "NoWebCorp", "web": None, "status": None},
        ]

        # Fake process_fn
        def mock_process(web_url, company_name=None, api_key=None, model=None):
            if not web_url:
                return CompanyEnrichmentResult(status=CompanyStatus.NO_WEBSITE)
            return CompanyEnrichmentResult(
                status=CompanyStatus.OK,
                impressum_url="http://nutrimmun.de/impressum",
                legal_name="nutrimmun GmbH",
                postal_address="Ludgeriplatz 2, 48153 Münster",
                vat_number="DE126116348",
                stats=TokenStats(chars_before=2000, chars_after=800, tokens_before=500, tokens_after=200, reduction_pct=60.0),
            )

        counts = enrich_companies(
            conn=mock_conn,
            process_fn=mock_process,
        )

        assert counts["OK"] == 1
        assert counts["NO_WEBSITE"] == 1
        assert mock_conn.commit.call_count == 2

    def test_enrich_empty_list(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        counts = enrich_companies(conn=mock_conn)
        assert counts == {}
