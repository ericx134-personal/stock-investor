from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen


Transport = Callable[[str, dict[str, str]], dict]


def _request_json(url: str, headers: dict[str, str]) -> dict:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_company_facts(
    cik: str, user_agent: str, transport: Transport = _request_json
) -> dict:
    """Fetch one company's standardized XBRL facts from the official SEC API."""
    if not user_agent.strip() or "@" not in user_agent:
        raise ValueError("SEC user agent must identify the app and include an email")
    if not cik.isdigit():
        raise ValueError("CIK must contain only digits")
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    return transport(
        url,
        {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        },
    )


def fetch_ticker_ciks(
    user_agent: str, transport: Transport = _request_json
) -> dict[str, str]:
    """Fetch the SEC's official ticker-to-CIK mapping."""
    if not user_agent.strip() or "@" not in user_agent:
        raise ValueError("SEC user agent must identify the app and include an email")
    payload = transport(
        "https://www.sec.gov/files/company_tickers.json",
        {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    return {
        item["ticker"].upper(): str(item["cik_str"]).zfill(10)
        for item in payload.values()
    }


def fetch_submissions(
    cik: str, user_agent: str, transport: Transport = _request_json
) -> dict:
    """Fetch a company's recent filing history from the official SEC API."""
    if not user_agent.strip() or "@" not in user_agent:
        raise ValueError("SEC user agent must identify the app and include an email")
    if not cik.isdigit():
        raise ValueError("CIK must contain only digits")
    url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
    return transport(
        url,
        {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
