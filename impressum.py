"""
impressum.py - Impressum discovery, token optimization, and DeepSeek extraction.
"""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


class CompanyStatus(IntEnum):
    OK = 0
    NO_IMPRESSUM_LINK_FOUND = 1
    PARSING_FAILED = 2
    ADDRESS_INCOMPLETE = 3
    ERROR = 4
    NO_WEBSITE = 5

    # Alias
    NO_IMPRESSUM_LINK = 1


class UnparseableLLMResponseError(Exception):
    """Raised when DeepSeek returned an unparseable or blank response even after retries."""
    pass


# Anchor patterns
HEAD_ANCHOR_PATTERNS = [
    re.compile(r"(?i)\bangaben\s+gem[äa]ß\s+§\s*5\s*(?:tmg|ddg)\b"),
    re.compile(r"(?i)\binformationen\s+nach\s+§\s*5\s*ecg\b"),
    re.compile(r"(?i)\bname\s+und\s+anschrift\b"),
    re.compile(r"(?i)\b(?:dienste)?anbieter(?:kennzeichnung)?\b"),
    re.compile(r"(?i)\bimpressum\b"),
    re.compile(r"(?i)\bimprint\b"),
    re.compile(r"(?i)\blegal\s+notice\b"),
]

TAIL_ANCHOR_PATTERNS = [
    re.compile(r"(?i)(?:USt-?(?:IdNr|ID)\.?|Umsatzsteuer-Identifikationsnummer|VAT\s*ID)?[:\.\s]*(DE\s?[0-9]{9})\b"),
    re.compile(r"(?i)(?:Handelsregister|Amtsgericht|Registergericht|Registernummer|HRB|HRA)\s*[:\.\s]*(?:HRB|HRA)?\s*[0-9]+"),
    re.compile(r"(?i)(?:Geschäftsführer|Vertreten\s+durch|Inhaber|Gesellschafter|Vorstand|Verantwortlich\s+für\s+den\s+Inhalt|Managing\s+Director)"),
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    re.compile(r"(?i)(?:tel(?:efon)?|phone|mobil|fax)?[:\.\s]*(?:\+49|0049|0)[1-9][0-9\s\-\/\(\)]{5,}[0-9]"),
]

IMPRESSUM_LINK_TERMS = [
    "impressum",
    "imprint",
    "rechtliche hinweise",
    "legal notice",
    "kontakt & impressum",
    "kontakt und impressum",
    "anbieterkennzeichnung",
]

MAX_TEXT_CHARS = 8000
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class TokenStats:
    chars_before: int = 0
    chars_after: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    reduction_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "reduction_pct": self.reduction_pct,
        }


@dataclass
class CompanyEnrichmentResult:
    status: CompanyStatus
    impressum_url: str | None = None
    legal_name: str | None = None
    postal_address: str | None = None
    handelsregister: str | None = None
    vat_number: str | None = None
    phone: str | None = None
    email: str | None = None
    responsible_person: str | None = None
    raw_json: dict[str, Any] | None = None
    stats: TokenStats = field(default_factory=TokenStats)
    error_message: str | None = None


def normalize_url(url: str | None) -> str | None:
    """Ensure URL has scheme (https:// by default) and trimmed whitespace."""
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
    return url


def find_impressum_link(base_url: str, html_content: str) -> str | None:
    """
    Search HTML for a link pointing to the Impressum/Imprint page.
    Matches text, href, title, and aria-label.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, "html.parser")
    candidates: list[tuple[int, str]] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        text = a.get_text(separator=" ", strip=True).lower()
        title = (a.get("title") or "").lower()
        aria = (a.get("aria-label") or "").lower()
        href_lower = href.lower()

        # Priority scoring: text match is best, href match is second
        for term in IMPRESSUM_LINK_TERMS:
            if term in text or term in aria or term in title:
                full_url = urljoin(base_url, href)
                candidates.append((1, full_url))
                break
            elif term in href_lower:
                full_url = urljoin(base_url, href)
                candidates.append((2, full_url))
                break

    if not candidates:
        return None

    # Sort by best priority (lowest score)
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def extract_clean_text(html_content: str) -> str:
    """
    Remove boilerplate tags (scripts, styles, nav, footer, header, svg, iframe),
    deobfuscate protected emails, and extract readable text content.
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    # Deobfuscate Cloudflare email protection tags
    for el in soup.find_all(attrs={"data-cfemail": True}):
        enc = el["data-cfemail"]
        try:
            r = int(enc[:2], 16)
            dec = "".join(chr(int(enc[i : i + 2], 16) ^ r) for i in range(2, len(enc), 2))
            el.replace_with(dec)
        except Exception:
            pass

    # Remove non-content tags
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Filter boilerplate lines (§5.1)
    filtered_lines = []
    boilerplate_line_re = re.compile(r"(?i)^(?:cookie(?:-|\s+)?(?:banner|settings|einstellungen|hinweis)|wir\s+verwenden\s+cookies|alle\s+rechte\s+vorbehalten|all\s+rights\s+reserved|©\s*\d{4})")
    for line in text.splitlines():
        line_s = line.strip()
        if not line_s or boilerplate_line_re.search(line_s):
            continue
        filtered_lines.append(line_s)
    text = "\n".join(filtered_lines)
    # Collapse 3+ newlines to 2 newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def optimize_impressum_text(raw_text: str, max_chars: int = MAX_TEXT_CHARS) -> tuple[str, TokenStats]:
    """
    Applies Token Optimization ('sandwich cutting'):
    1. If text is under max_chars threshold, send unchanged (§5).
    2. Finds first head anchor (e.g. 'Angaben gemäß § 5 TMG', 'Impressum').
    3. Finds last tail anchor (e.g. phone, VAT DE..., Handelsregister, email).
    4. Slices text: [head - 100 : tail + 400].
    5. Limits to max_chars.
    6. Calculates before/after token counts and reduction percentage.
    """
    chars_before = len(raw_text)
    tokens_before = max(0, chars_before // 4)

    if not raw_text:
        return "", TokenStats(chars_before=0, chars_after=0, tokens_before=0, tokens_after=0, reduction_pct=0.0)

    # §5: If visible text is under threshold, send it unchanged
    if chars_before <= max_chars:
        return raw_text, TokenStats(
            chars_before=chars_before,
            chars_after=chars_before,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            reduction_pct=0.0,
        )

    # 1. Locate head anchor
    head_start = None
    for pattern in HEAD_ANCHOR_PATTERNS:
        match = pattern.search(raw_text)
        if match:
            pos = match.start()
            if head_start is None or pos < head_start:
                head_start = pos

    if head_start is not None:
        start_idx = max(0, head_start - 100)
    else:
        start_idx = 0

    # 2. Locate last tail anchor at or after start_idx
    search_region = raw_text[start_idx:]
    last_tail_end = None
    for pattern in TAIL_ANCHOR_PATTERNS:
        for match in pattern.finditer(search_region):
            pos = match.end()
            if last_tail_end is None or pos > last_tail_end:
                last_tail_end = pos

    if last_tail_end is not None:
        end_idx = min(len(raw_text), start_idx + last_tail_end + 400)
    else:
        end_idx = min(len(raw_text), start_idx + max_chars)

    optimized = raw_text[start_idx:end_idx].strip()

    # 3. Verification & fallback (§5.5)
    has_head = any(p.search(optimized) for p in HEAD_ANCHOR_PATTERNS)
    has_strong_signal = any(p.search(optimized) for p in TAIL_ANCHOR_PATTERNS)
    if not (has_head and has_strong_signal):
        if len(raw_text) <= max_chars:
            optimized = raw_text.strip()
        else:
            half = max_chars // 2
            optimized = (raw_text[:half] + "\n\n" + raw_text[-half:]).strip()

    # Hard cap at max_chars
    if len(optimized) > max_chars:
        optimized = optimized[:max_chars].strip()

    chars_after = len(optimized)
    tokens_after = max(0, chars_after // 4)
    reduction_pct = round((1.0 - (chars_after / max(chars_before, 1))) * 100.0, 1) if chars_before > 0 else 0.0

    stats = TokenStats(
        chars_before=chars_before,
        chars_after=chars_after,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        reduction_pct=max(0.0, reduction_pct),
    )
    return optimized, stats


DEEPSEEK_SYSTEM_PROMPT = """You extract legally required company information ("Impressum" / "Imprint") from German-language website text.
Return ONLY a valid JSON object (no markdown fences, no commentary) that parses with json.loads. The JSON must have exactly these keys:
{
 "company_name": "<string or null>",
 "postal_address": {
 "street": "<string or null>",
 "house_no": "<string or null>",
 "postcode": "<string or null>",
 "city": "<string or null>",
 "country": "<string or null>"
 },
 "handelsregister": "<string or null>",
 "vat_number": "<string or null>",
 "phone": "<string or null>",
 "email": "<string or null>",
 "responsible_person": "<string or null>"
}
Rules:
- Extract ONLY information actually present in the text; use null when absent.
- Do not invent or guess values.
- phone: keep the international format when possible (e.g. +49 ...).
- vat_number: German VAT ids look like DE followed by 9 digits.
- email: lowercase.
- responsible_person: the named person or role legally responsible for the content (e.g. Geschaeftsfuehrer, Vorstand, "inhaltlich verantwortlich").
- Output valid JSON only."""


def call_deepseek_extraction(
    optimized_text: str,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
    max_retries: int = 3,
    api_url: str = "https://api.deepseek.com/chat/completions",
) -> dict[str, Any]:
    """
    Sends the optimized impressum text to DeepSeek API in JSON mode with retry on blank/invalid JSON.
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY is not set or provided")

    selected_model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Extract the Impressum data from the text below and return JSON:\n\n{optimized_text}",
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 1024,
        "temperature": 0.0,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    import time
    last_err = None
    is_response_parse_error = False

    for attempt in range(max_retries):
        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()

            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            if not content or not content.strip():
                is_response_parse_error = True
                raise ValueError("DeepSeek returned blank content")

            data = json.loads(content)
            return data
        except json.JSONDecodeError as e:
            last_err = e
            is_response_parse_error = True
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))

    if is_response_parse_error:
        raise UnparseableLLMResponseError(f"DeepSeek response could not be parsed: {last_err}")
    raise last_err or RuntimeError("DeepSeek extraction failed after retries")


def format_postal_address(address_dict: dict[str, Any] | None) -> str | None:
    """Format structured postal address dictionary into a single readable string."""
    if not address_dict or not isinstance(address_dict, dict):
        return None
    street = (address_dict.get("street") or "").strip()
    house_no = (address_dict.get("house_no") or "").strip()
    postcode = (address_dict.get("postcode") or "").strip()
    city = (address_dict.get("city") or "").strip()
    country = (address_dict.get("country") or "").strip()

    street_part = f"{street} {house_no}".strip()
    city_part = f"{postcode} {city}".strip()
    parts = [p for p in (street_part, city_part, country) if p]
    return ", ".join(parts) if parts else None


def validate_extraction(raw_data: dict[str, Any]) -> tuple[CompanyStatus, str | None]:
    """
    Validates parsed extraction data:
    - Status 2 (PARSING_FAILED): empty or all fields null/empty.
    - Status 0 (OK): all 4 address components (street, house_no, postcode, city) present.
    - Status 3 (ADDRESS_INCOMPLETE): address is missing one or more required components.
    """
    if not raw_data:
        return CompanyStatus.PARSING_FAILED, "DeepSeek returned empty response"

    company_name = raw_data.get("company_name") or raw_data.get("legal_name")
    phone = raw_data.get("phone")
    email = raw_data.get("email")
    vat = raw_data.get("vat_number")
    register = raw_data.get("handelsregister")
    person = raw_data.get("responsible_person")
    address = raw_data.get("postal_address") or {}

    has_any_field = any(
        bool(v and str(v).strip())
        for v in (company_name, phone, email, vat, register, person)
    ) or (any(bool(v and str(v).strip()) for v in address.values()) if isinstance(address, dict) else False)

    if not has_any_field:
        return CompanyStatus.PARSING_FAILED, "No fields could be extracted"

    # Check 4 mandatory address components
    if isinstance(address, dict):
        street = (address.get("street") or "").strip()
        house_no = (address.get("house_no") or "").strip()
        postcode = (address.get("postcode") or "").strip()
        city = (address.get("city") or "").strip()

        if street and house_no and postcode and city:
            return CompanyStatus.OK, None
        else:
            missing = [k for k, val in [("street", street), ("house_no", house_no), ("postcode", postcode), ("city", city)] if not val]
            return CompanyStatus.ADDRESS_INCOMPLETE, f"Missing required address fields: {', '.join(missing)}"

    return CompanyStatus.ADDRESS_INCOMPLETE, "Postal address missing or not a dict"


def fetch_url(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Fetch URL with timeout and User-Agent."""
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.status_code, resp.text


def process_company(
    web_url: str | None,
    company_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    deepseek_fn=call_deepseek_extraction,
) -> CompanyEnrichmentResult:
    """
    Full pipeline to process a company website:
    1. Check website presence -> Status 5 if empty.
    2. Normalize URL and fetch homepage -> Status 4 if network error.
    3. Find Impressum link -> Status 1 if not found.
    4. Fetch Impressum page -> Status 4 if error.
    5. Clean text and apply Token Optimization.
    6. Call DeepSeek -> Status 4 if API error.
    7. Validate extraction -> Status 0, 2, or 3.
    """
    normalized = normalize_url(web_url)
    if not normalized:
        return CompanyEnrichmentResult(
            status=CompanyStatus.NO_WEBSITE,
            error_message="Website URL is blank or empty",
        )

    # Fetch homepage
    try:
        code, home_html = fetch_url(normalized)
        if code >= 400:
            return CompanyEnrichmentResult(
                status=CompanyStatus.ERROR,
                error_message=f"Homepage returned HTTP {code}",
            )
    except Exception as e:
        return CompanyEnrichmentResult(
            status=CompanyStatus.ERROR,
            error_message=f"Failed to fetch homepage: {e}",
        )

    # Find impressum link
    impressum_url = find_impressum_link(normalized, home_html)
    if not impressum_url:
        return CompanyEnrichmentResult(
            status=CompanyStatus.NO_IMPRESSUM_LINK,
            error_message=f"No Impressum or Imprint link found on homepage: {normalized}",
        )

    # Fetch impressum page
    try:
        code, imp_html = fetch_url(impressum_url)
        if code >= 400:
            return CompanyEnrichmentResult(
                status=CompanyStatus.ERROR,
                impressum_url=impressum_url,
                error_message=f"Impressum page returned HTTP {code}",
            )
    except Exception as e:
        return CompanyEnrichmentResult(
            status=CompanyStatus.ERROR,
            impressum_url=impressum_url,
            error_message=f"Failed to fetch impressum: {e}",
        )

    # Clean and optimize text
    clean_text = extract_clean_text(imp_html)
    optimized_text, stats = optimize_impressum_text(clean_text)

    # DeepSeek extraction
    try:
        raw_json = deepseek_fn(optimized_text, api_key=api_key, model=model)
    except UnparseableLLMResponseError as e:
        return CompanyEnrichmentResult(
            status=CompanyStatus.PARSING_FAILED,
            impressum_url=impressum_url,
            stats=stats,
            error_message=f"DeepSeek returned unparseable response: {e}",
        )
    except Exception as e:
        return CompanyEnrichmentResult(
            status=CompanyStatus.ERROR,
            impressum_url=impressum_url,
            stats=stats,
            error_message=f"DeepSeek extraction failed: {e}",
        )

    # Validate and determine final status
    status, err_msg = validate_extraction(raw_json)
    postal_addr_str = format_postal_address(raw_json.get("postal_address"))

    extracted_legal_name = raw_json.get("company_name") or raw_json.get("legal_name") or company_name
    extracted_email = (raw_json.get("email") or "").strip().lower() or None

    return CompanyEnrichmentResult(
        status=status,
        impressum_url=impressum_url,
        legal_name=extracted_legal_name,
        postal_address=postal_addr_str,
        handelsregister=raw_json.get("handelsregister"),
        vat_number=raw_json.get("vat_number"),
        phone=raw_json.get("phone"),
        email=extracted_email,
        responsible_person=raw_json.get("responsible_person"),
        raw_json=raw_json,
        stats=stats,
        error_message=err_msg,
    )
