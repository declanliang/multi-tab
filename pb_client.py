"""
PartnerBoost API client helpers.
"""

from __future__ import annotations

import time
from typing import Any

import requests


class PartnerBoostError(RuntimeError):
    """Raised when PartnerBoost returns an error response."""


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _check_status(payload: dict[str, Any], context: str) -> None:
    status = payload.get("status") or {}
    code = _as_int(status.get("code"), default=-1)
    if code != 0:
        msg = status.get("msg") or "unknown error"
        raise PartnerBoostError(f"{context} failed: code={code}, msg={msg}")


def fetch_transactions(
    *,
    base_url: str,
    token: str,
    begin_date: str,
    end_date: str,
    status: str = "All",
    limit: int = 2000,
    request_delay: float = 0.2,
) -> list[dict[str, Any]]:
    """Fetch all transaction pages for a transaction date range."""
    session = requests.Session()
    endpoint = f"{base_url.rstrip('/')}/api.php"
    page = 1
    total_page = 1
    transactions: list[dict[str, Any]] = []

    while page <= total_page:
        params = {
            "mod": "medium",
            "op": "transaction",
            "token": token,
            "begin_date": begin_date,
            "end_date": end_date,
            "type": "json",
            "status": status,
            "page": page,
            "limit": limit,
        }
        response = session.get(endpoint, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        _check_status(payload, f"fetch transactions page {page}")

        data = payload.get("data") or {}
        items = data.get("list") or []
        if isinstance(items, dict):
            items = [items]
        transactions.extend(items)

        total_page = max(_as_int(data.get("total_page"), default=1), 1)
        page += 1
        if page <= total_page:
            time.sleep(request_delay)

    return transactions


def get_storefront_link(
    *,
    base_url: str,
    token: str,
    brand_id: str,
    uid: str = "",
) -> dict[str, Any]:
    """Generate one storefront tracking link by brand ID."""
    endpoint = f"{base_url.rstrip('/')}/api/datafeed/get_fba_brand_link"
    payload: dict[str, str] = {
        "token": token,
        "bids": str(brand_id),
    }
    if uid:
        payload["uid"] = uid

    response = requests.post(endpoint, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    _check_status(result, f"get storefront link for brand_id={brand_id}")

    data = result.get("data") or []
    if isinstance(data, dict):
        data = [data]

    for item in data:
        if str(item.get("bid")) == str(brand_id):
            return item

    error_list = result.get("error_list") or []
    for item in error_list:
        if str(item.get("bid")) == str(brand_id):
            message = item.get("message") or "unknown error"
            brand_name = item.get("brand_name") or ""
            raise PartnerBoostError(
                f"brand_id={brand_id} {brand_name} link error: {message}"
            )

    if data:
        return data[0]

    raise PartnerBoostError(f"no storefront link returned for brand_id={brand_id}")
