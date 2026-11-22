"""
tests/test_impressum.py - Comprehensive unit tests for impressum.py
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from impressum import (
    CompanyStatus,
    TokenStats,
    normalize_url,
    find_impressum_link,
    extract_clean_text,
    optimize_impressum_text,
    format_postal_address,
    validate_extraction,
    call_deepseek_extraction,
    process_company,
)


class TestNormalizeUrl:
    def test_empty_or_none(self):
        assert normalize_url(None) is None
        assert normalize_url("") is None
        assert normalize_url("   ") is None

    def test_adds_https_scheme_when_missing(self):
        assert normalize_url("nutrimmun.de") == "https://nutrimmun.de"
        assert normalize_url("www.baroloandchampagne.com") == "https://www.baroloandchampagne.com"

    def test_preserves_existing_scheme(self):
        assert normalize_url("http://nutrimmun.de") == "http://nutrimmun.de"
        assert normalize_url("https://baroloandchampagne.com/de/") == "https://baroloandchampagne.com/de/"

    def test_trims_whitespace(self):
        assert normalize_url("  https://example.com/  ") == "https://example.com/"


class TestFindImpressumLink:
    def test_finds_german_impressum(self):
        html = '<nav><a href="/">Home</a><a href="/impressum.html">Impressum</a></nav>'
        link = find_impressum_link("https://example.de", html)
        assert link == "https://example.de/impressum.html"

    def test_finds_english_imprint(self):
        html = '<div><footer><a href="/legal/imprint">Imprint</a></footer></div>'
        link = find_impressum_link("https://example.com", html)
        assert link == "https://example.com/legal/imprint"

    def test_finds_rechtliche_hinweise(self):
        html = '<div><a href="/rechtliches/">Rechtliche Hinweise</a></div>'
        link = find_impressum_link("https://example.org", html)
        assert link == "https://example.org/rechtliches/"

    def test_finds_by_href_keyword(self):
        html = '<div><a href="/about/impressum">Legal Info</a></div>'
        link = find_impressum_link("https://example.com", html)
        assert link == "https://example.com/about/impressum"

    def test_ignores_non_http_schemes(self):
        html = '<a href="mailto:info@example.com">Impressum</a>'
        assert find_impressum_link("https://example.com", html) is None

        html_hash = '<a href="#impressum">Impressum</a>'
        assert find_impressum_link("https://example.com", html_hash) is None

    def test_returns_none_when_no_link(self):
        html = '<nav><a href="/products">Products</a><a href="/contact">Contact Us</a></nav>'
        assert find_impressum_link("https://example.com", html) is None


class TestExtractCleanText:
    def test_removes_scripts_styles_nav_footer(self):
        html = """
        <html>
          <head>
            <style>body { color: red; }</style>
            <script>console.log('secret');</script>
          </head>
          <body>
            <header><h1>Site Header</h1></header>
            <nav><a href="#">Nav item</a></nav>
            <main>
              <p>Impressum</p>
              <p>Musterfirma GmbH</p>
            </main>
            <footer><p>Copyright 2026</p></footer>
            <noscript>Enable JS</noscript>
          </body>
        </html>
        """
        text = extract_clean_text(html)
        assert "color: red" not in text
        assert "console.log" not in text
        assert "Site Header" not in text
        assert "Nav item" not in text
        assert "Copyright 2026" not in text
        assert "Impressum" in text
        assert "Musterfirma GmbH" in text

    def test_handles_empty_html(self):
        assert extract_clean_text("") == ""
        assert extract_clean_text(None) == ""

    def test_deobfuscates_cloudflare_email(self):
        # enc for 'info@nutrimmun.de' with key 0x6e
        html = '<p>Contact: <span class="__cf_email__" data-cfemail="6e070008012e001b1a1c0703031b00400a0b">[email&#160;protected]</span></p>'
        text = extract_clean_text(html)
        assert "info@nutrimmun.de" in text
        assert "[email" not in text


class TestTokenOptimization:
    def test_sandwich_cutting_with_anchors(self):
        filler_before = "Welcome to our store! " * 50
        legal_head = "Impressum\nAngaben gemäß § 5 TMG:\n"
        company_body = "Muster GmbH\nMusterstraße 12\n10115 Berlin\n"
        legal_tail = "Geschäftsführer: Max Mustermann\nHandelsregister: Amtsgericht Berlin HRB 123456\nUSt-IdNr.: DE123456789\nE-Mail: info@muster.de\nTelefon: +49 30 1234567\n"
        filler_after = "Check out our latest blog posts! " * 50

        full_text = f"{filler_before}\n{legal_head}{company_body}{legal_tail}\n{filler_after}"
        optimized, stats = optimize_impressum_text(full_text)

        # Head anchor should be preserved
        assert "Angaben gemäß § 5 TMG" in optimized
        assert "Musterstraße 12" in optimized
        assert "DE123456789" in optimized
        # Chars after should be significantly less than chars before
        assert stats.chars_after < stats.chars_before
        assert stats.reduction_pct > 0
        assert stats.tokens_after <= stats.tokens_before

    def test_respects_max_chars(self):
        huge_text = "Impressum " + ("Mustertext " * 2000) + "DE123456789"
        optimized, stats = optimize_impressum_text(huge_text, max_chars=500)
        assert len(optimized) <= 500
        assert stats.chars_after <= 500

    def test_handles_text_without_anchors(self):
        simple_text = "This is a random page without legal anchors."
        optimized, stats = optimize_impressum_text(simple_text)
        assert optimized == simple_text
        assert stats.chars_before == len(simple_text)
        assert stats.chars_after == len(simple_text)


class TestFormatPostalAddress:
    def test_formats_complete_address(self):
        data = {
            "street": "Hauptstraße",
            "house_no": "42",
            "postcode": "10115",
            "city": "Berlin",
            "country": "Germany",
        }
        res = format_postal_address(data)
        assert res == "Hauptstraße 42, 10115 Berlin, Germany"

    def test_formats_partial_address(self):
        data = {
            "street": "Ludgeriplatz",
            "house_no": "2",
            "postcode": "48153",
            "city": "Münster",
        }
        res = format_postal_address(data)
        assert res == "Ludgeriplatz 2, 48153 Münster"

    def test_handles_empty(self):
        assert format_postal_address(None) is None
        assert format_postal_address({}) is None


class TestValidateExtraction:
    def test_status_ok_all_address_fields_present(self):
        data = {
            "legal_name": "nutrimmun GmbH",
            "postal_address": {
                "street": "Ludgeriplatz",
                "house_no": "2",
                "postcode": "48153",
                "city": "Münster",
                "country": "DE",
            },
            "handelsregister": "HRB 2652",
            "vat_number": "DE126116348",
            "phone": "+49 251 123456",
            "email": "info@nutrimmun.de",
            "responsible_person": "Dr. Muster",
        }
        status, err = validate_extraction(data)
        assert status == CompanyStatus.OK
        assert err is None

    def test_status_address_incomplete_missing_house_no(self):
        data = {
            "legal_name": "Test GmbH",
            "postal_address": {
                "street": "Musterstraße",
                "house_no": "",  # Missing!
                "postcode": "10115",
                "city": "Berlin",
            },
            "phone": "030 123456",
        }
        status, err = validate_extraction(data)
        assert status == CompanyStatus.ADDRESS_INCOMPLETE
        assert "house_no" in err

    def test_status_address_incomplete_missing_postcode(self):
        data = {
            "legal_name": "Test GmbH",
            "postal_address": {
                "street": "Musterstraße",
                "house_no": "10",
                "postcode": None,  # Missing!
                "city": "Berlin",
            },
        }
        status, err = validate_extraction(data)
        assert status == CompanyStatus.ADDRESS_INCOMPLETE
        assert "postcode" in err

    def test_status_parsing_failed_empty_response(self):
        assert validate_extraction({})[0] == CompanyStatus.PARSING_FAILED
        all_null = {
            "legal_name": None,
            "postal_address": {"street": None, "house_no": None, "postcode": None, "city": None},
            "vat_number": None,
            "phone": None,
        }
        status, _ = validate_extraction(all_null)
        assert status == CompanyStatus.PARSING_FAILED


class TestCallDeepseekExtraction:
    @patch("impressum.requests.post")
    def test_successful_api_call(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "legal_name": "nutrimmun GmbH",
                            "postal_address": {
                                "street": "Ludgeriplatz",
                                "house_no": "2",
                                "postcode": "48153",
                                "city": "Münster",
                                "country": "DE",
                            },
                            "vat_number": "DE126116348",
                            "phone": "+49 251 12345",
                            "email": "info@nutrimmun.de",
                        })
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        res = call_deepseek_extraction("dummy impressum text", api_key="sk-test-12345")
        assert res["legal_name"] == "nutrimmun GmbH"
        assert res["postal_address"]["city"] == "Münster"

        # Verify payload contains response_format json_object
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["response_format"] == {"type": "json_object"}
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-test-12345"

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is not set"):
            call_deepseek_extraction("text", api_key=None)


class TestProcessCompanyPipeline:
    def test_empty_website_yields_status_5(self):
        res = process_company("")
        assert res.status == CompanyStatus.NO_WEBSITE
        res_none = process_company(None)
        assert res_none.status == CompanyStatus.NO_WEBSITE

    @patch("impressum.fetch_url")
    def test_homepage_network_error_yields_status_4(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection refused")
        res = process_company("http://unreachable-domain.xyz")
        assert res.status == CompanyStatus.ERROR
        assert "Failed to fetch homepage" in res.error_message

    @patch("impressum.fetch_url")
    def test_no_impressum_link_yields_status_1(self, mock_fetch):
        mock_fetch.return_value = (200, "<html><body><h1>Hello World</h1></body></html>")
        res = process_company("http://example.com")
        assert res.status == CompanyStatus.NO_IMPRESSUM_LINK

    @patch("impressum.fetch_url")
    def test_impressum_fetch_error_yields_status_4(self, mock_fetch):
        mock_fetch.side_effect = [
            (200, '<html><body><a href="/impressum">Impressum</a></body></html>'),
            Exception("404 Not Found"),
        ]
        res = process_company("http://example.com")
        assert res.status == CompanyStatus.ERROR
        assert res.impressum_url == "http://example.com/impressum"

    @patch("impressum.fetch_url")
    def test_complete_extraction_yields_status_0(self, mock_fetch):
        home_html = '<html><body><a href="/impressum">Impressum</a></body></html>'
        imp_html = """
        <html><body>
          <h1>Impressum</h1>
          <p>nutrimmun GmbH</p>
          <p>Ludgeriplatz 2</p>
          <p>48153 Münster</p>
          <p>USt-IdNr: DE126116348</p>
          <p>E-Mail: info@nutrimmun.de</p>
          <p>Telefon: +49 251 12345</p>
          <p>HRB 2652</p>
        </body></html>
        """
        mock_fetch.side_effect = [(200, home_html), (200, imp_html)]

        mock_deepseek_fn = MagicMock(return_value={
            "legal_name": "nutrimmun GmbH",
            "postal_address": {
                "street": "Ludgeriplatz",
                "house_no": "2",
                "postcode": "48153",
                "city": "Münster",
                "country": "DE",
            },
            "handelsregister": "HRB 2652",
            "vat_number": "DE126116348",
            "phone": "+49 251 12345",
            "email": "info@nutrimmun.de",
            "responsible_person": "Geschäftsführer",
        })

        res = process_company(
            "http://nutrimmun.de",
            api_key="sk-test",
            deepseek_fn=mock_deepseek_fn,
        )

        assert res.status == CompanyStatus.OK
        assert res.impressum_url == "http://nutrimmun.de/impressum"
        assert res.legal_name == "nutrimmun GmbH"
        assert res.vat_number == "DE126116348"
        assert res.postal_address == "Ludgeriplatz 2, 48153 Münster, DE"
        assert res.stats.chars_after > 0
