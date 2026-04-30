"""
Generate TARGET_URLS from PartnerBoost transactions.

This script fetches transactions, resolves each transaction's brand_id to a
storefront short link, previews the result, then optionally writes TARGET_URLS
in config.py and runs the AdsPower opener.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pb_client import PartnerBoostError, fetch_transactions, get_storefront_link

try:
    from config import (
        PB_API_BASE_URL,
        PB_BRAND_LINK_CACHE_FILE,
        PB_LINK_UID,
        PB_ORDER_BIDS_OUTPUT_FILE,
        PB_TOKEN,
        PB_TRANSACTION_PAGE_LIMIT,
        PB_TRANSACTION_STATUS,
    )
except ImportError as exc:
    raise SystemExit(f"Failed to import config.py: {exc}") from exc


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.py"


@dataclass
class ResolvedTarget:
    index: int
    order_id: str
    brand_id: str
    merchant_name: str
    status: str
    link: str
    link_source: str = ""


@dataclass
class LinkFailure:
    index: int
    order_id: str
    brand_id: str
    merchant_name: str
    status: str
    error: str
    link_source: str = "failed"


@dataclass
class ResolveStats:
    cache_hits: int = 0
    cache_misses: int = 0
    failures: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate config.py TARGET_URLS from PartnerBoost orders."
    )
    parser.add_argument("--date", help="Single transaction date: YYYY-MM-DD")
    parser.add_argument("--begin-date", help="Transaction begin date: YYYY-MM-DD")
    parser.add_argument("--end-date", help="Transaction end date: YYYY-MM-DD")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Write config.py without asking after preview.",
    )
    parser.add_argument(
        "--bids-output",
        help="Write fetched order bids to this JSON file for checking.",
    )
    parser.add_argument(
        "--bids-only",
        action="store_true",
        help="Only fetch orders and write the bids output file.",
    )
    parser.add_argument(
        "--refresh-local-links",
        action="store_true",
        help="Normalize the local brand link cache and exit.",
    )
    parser.add_argument(
        "--run-main",
        action="store_true",
        help="Write config.py and run main.py after resolving links.",
    )
    args = parser.parse_args()
    if args.date and (args.begin_date or args.end_date):
        raise SystemExit("Use either --date or --begin-date/--end-date, not both.")
    if args.bids_only and args.run_main:
        raise SystemExit("--bids-only cannot be used with --run-main.")
    return args


def prompt_date(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def validate_date_range(begin_date: str, end_date: str) -> None:
    try:
        begin = datetime.strptime(begin_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit("Date must use YYYY-MM-DD format.") from exc

    if end < begin:
        raise SystemExit("end_date cannot be earlier than begin_date.")
    if (end - begin).days > 62:
        raise SystemExit("PartnerBoost query time span cannot exceed 62 days.")


def get_date_range(args: argparse.Namespace) -> tuple[str, str]:
    if args.date:
        begin_date = args.date
        end_date = args.date
    else:
        begin_date = args.begin_date or prompt_date("Begin date (YYYY-MM-DD)")
        end_date = args.end_date or prompt_date("End date (YYYY-MM-DD)", begin_date)
    validate_date_range(begin_date, end_date)
    return begin_date, end_date


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise SystemExit(f"Cache file must contain a JSON object: {path}")
    return data


def save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cache_path() -> Path:
    path = Path(PB_BRAND_LINK_CACHE_FILE)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def output_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def brand_id_from_transaction(transaction: dict[str, Any]) -> str:
    return str(transaction.get("brand_id") or transaction.get("mid") or "").strip()


def write_order_bids_file(
    *,
    transactions: list[dict[str, Any]],
    begin_date: str,
    end_date: str,
    path: Path,
    targets: list[ResolvedTarget] | None = None,
    failures: list[LinkFailure] | None = None,
    stats: ResolveStats | None = None,
) -> None:
    targets_by_index = {target.index: target for target in targets or []}
    failures_by_index = {failure.index: failure for failure in failures or []}
    orders = []
    bids = []
    for index, transaction in enumerate(transactions, start=1):
        brand_id = brand_id_from_transaction(transaction)
        target = targets_by_index.get(index)
        failure = failures_by_index.get(index)

        if target:
            link_status = "resolved"
            link_source = target.link_source or "unknown"
            link = target.link
            link_error = ""
        elif failure:
            link_status = "failed"
            link_source = failure.link_source or "failed"
            link = ""
            link_error = failure.error
        else:
            link_status = "not_resolved"
            link_source = "not_resolved"
            link = ""
            link_error = ""

        bids.append(brand_id)
        orders.append(
            {
                "index": index,
                "bid": brand_id,
                "brand_id": brand_id,
                "merchant_name": transaction.get("merchant_name") or "",
                "order_id": transaction.get("order_id") or "",
                "status": transaction.get("status") or "",
                "order_time": transaction.get("order_time") or "",
                "link_status": link_status,
                "link_source": link_source,
                "link": link,
                "link_error": link_error,
            }
        )

    local_cache_orders = sum(1 for target in targets or [] if target.link_source == "local_cache")
    api_orders = sum(1 for target in targets or [] if target.link_source == "api")
    payload = {
        "begin_date": begin_date,
        "end_date": end_date,
        "total_orders": len(transactions),
        "resolved_links": len(targets or []),
        "failed_links": len(failures or []),
        "link_resolution": {
            "local_cache_orders": local_cache_orders,
            "api_orders": api_orders,
            "api_lookups": stats.cache_misses if stats else 0,
            "cache_hits": stats.cache_hits if stats else 0,
            "skipped_orders": stats.failures if stats else 0,
        },
        "bids": bids,
        "unique_bids": sorted({bid for bid in bids if bid}),
        "orders": orders,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def link_from_cache_entry(entry: dict[str, Any]) -> str:
    return str(
        entry.get("link")
        or entry.get("storefront_short_link")
        or entry.get("storefront_link")
        or ""
    )


def normalize_cache_item(brand_id: str, item: dict[str, Any]) -> dict[str, Any]:
    link = str(
        item.get("link")
        or item.get("storefront_short_link")
        or item.get("storefront_link")
        or ""
    )
    return {
        "bid": str(item.get("bid") or brand_id),
        "brand_name": item.get("brand_name") or "",
        "link": link,
    }


def normalize_local_link_cache(cache: dict[str, dict[str, Any]]) -> int:
    changed = 0
    for brand_id, entry in list(cache.items()):
        if not isinstance(entry, dict):
            continue
        before = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        link = link_from_cache_entry(entry)
        entry["bid"] = str(entry.get("bid") or brand_id)
        entry.setdefault("brand_name", "")
        entry["link"] = link
        for stale_key in ("storefront_link", "storefront_short_link", "link_id", "updated_at"):
            entry.pop(stale_key, None)
        after = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        if after != before:
            changed += 1
    return changed


def upsert_local_brand_link(
    cache: dict[str, dict[str, Any]],
    *,
    brand_id: str,
    brand_name: str,
    link: str,
) -> None:
    entry = cache.setdefault(brand_id, {})
    entry["bid"] = str(entry.get("bid") or brand_id)
    if brand_name:
        entry["brand_name"] = brand_name
    else:
        entry.setdefault("brand_name", "")
    entry["link"] = link
    for stale_key in ("storefront_link", "storefront_short_link", "link_id", "updated_at"):
        entry.pop(stale_key, None)


def resolve_targets(
    transactions: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
) -> tuple[list[ResolvedTarget], ResolveStats, list[LinkFailure]]:
    targets: list[ResolvedTarget] = []
    failures: list[LinkFailure] = []
    stats = ResolveStats()
    failed_brand_errors: dict[str, str] = {}

    for index, transaction in enumerate(transactions, start=1):
        brand_id = brand_id_from_transaction(transaction)
        merchant_name = str(transaction.get("merchant_name") or "").strip()
        order_id = str(transaction.get("order_id") or "").strip()
        order_status = str(transaction.get("status") or "").strip()

        if not brand_id:
            stats.failures += 1
            error = "missing brand_id"
            failures.append(
                LinkFailure(
                    index=index,
                    order_id=order_id,
                    brand_id=brand_id,
                    merchant_name=merchant_name,
                    status=order_status,
                    error=error,
                )
            )
            print(f"SKIP order={order_id or '-'}: {error}")
            continue

        if brand_id in failed_brand_errors:
            stats.failures += 1
            error = f"previous link lookup failed: {failed_brand_errors[brand_id]}"
            failures.append(
                LinkFailure(
                    index=index,
                    order_id=order_id,
                    brand_id=brand_id,
                    merchant_name=merchant_name,
                    status=order_status,
                    error=error,
                )
            )
            print(
                f"SKIP order={order_id or '-'} brand_id={brand_id}: "
                "previous link lookup failed"
            )
            continue

        entry = cache.get(brand_id)
        if entry and link_from_cache_entry(entry):
            stats.cache_hits += 1
            link_source = "local_cache"
        else:
            stats.cache_misses += 1
            try:
                item = get_storefront_link(
                    base_url=PB_API_BASE_URL,
                    token=PB_TOKEN,
                    brand_id=brand_id,
                    uid=PB_LINK_UID,
                )
            except PartnerBoostError as exc:
                error = str(exc)
                failed_brand_errors[brand_id] = error
                stats.failures += 1
                failures.append(
                    LinkFailure(
                        index=index,
                        order_id=order_id,
                        brand_id=brand_id,
                        merchant_name=merchant_name,
                        status=order_status,
                        error=error,
                    )
                )
                print(f"SKIP order={order_id or '-'} brand_id={brand_id}: {error}")
                continue
            entry = normalize_cache_item(brand_id, item)
            cache[brand_id] = entry
            link_source = "api"

        link = link_from_cache_entry(entry)
        if not link:
            stats.failures += 1
            error = "empty link"
            failures.append(
                LinkFailure(
                    index=index,
                    order_id=order_id,
                    brand_id=brand_id,
                    merchant_name=merchant_name,
                    status=order_status,
                    error=error,
                )
            )
            print(f"SKIP order={order_id or '-'} brand_id={brand_id}: {error}")
            continue

        targets.append(
            ResolvedTarget(
                index=index,
                order_id=order_id,
                brand_id=brand_id,
                merchant_name=merchant_name,
                status=order_status,
                link=link,
                link_source=link_source,
            )
        )
        upsert_local_brand_link(
            cache,
            brand_id=brand_id,
            brand_name=merchant_name,
            link=link,
        )

    return targets, stats, failures


def find_target_urls_assignment(tree: ast.AST) -> ast.Assign | ast.AnnAssign | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TARGET_URLS":
                    return node
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "TARGET_URLS":
                return node
    return None


def inline_comment(value: str) -> str:
    comment = " ".join(str(value).replace("#", "").split())
    return comment or "unknown brand"


def update_config_target_urls(config_path: Path, targets: list[ResolvedTarget]) -> None:
    source = config_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    node = find_target_urls_assignment(tree)
    if node is None or node.end_lineno is None:
        raise SystemExit("Could not find TARGET_URLS assignment in config.py.")

    lines = source.splitlines(keepends=True)
    replacement = ["TARGET_URLS = [\n"]
    for target in targets:
        brand_name = inline_comment(target.merchant_name or target.brand_id)
        replacement.append(
            f"    {json.dumps(target.link, ensure_ascii=False)},  # {brand_name}\n"
        )
    replacement.append("]\n")

    start = node.lineno - 1
    end = node.end_lineno
    lines[start:end] = replacement
    config_path.write_text("".join(lines), encoding="utf-8")


def print_preview(targets: list[ResolvedTarget], stats: ResolveStats) -> None:
    print("\nResolved target URLs")
    print("-" * 80)
    for index, target in enumerate(targets, start=1):
        brand = target.merchant_name or "-"
        order_id = target.order_id or "-"
        status = target.status or "-"
        print(
            f"{index:>3}. brand_id={target.brand_id} | "
            f"brand={brand} | order={order_id} | status={status}"
        )
        print(f"     {target.link}")

    print("-" * 80)
    print(f"Orders with links: {len(targets)}")
    print(f"Cache hits: {stats.cache_hits}")
    print(f"API lookups: {stats.cache_misses}")
    print(f"Skipped orders: {stats.failures}")


def confirm_write(args: argparse.Namespace) -> bool:
    if args.run_main:
        return True
    if args.yes:
        return True
    answer = input("\nWrite these links to config.py TARGET_URLS? [y/N]: ").strip()
    return answer.lower() in {"y", "yes"}


def run_main_script() -> None:
    print("\nRunning AdsPower opener: python main.py")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py")],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(f"main.py failed with exit code {result.returncode}.")


def main() -> None:
    args = parse_args()

    if args.refresh_local_links:
        cache_file = cache_path()
        cache = load_cache(cache_file)
        changed = normalize_local_link_cache(cache)
        save_cache(cache_file, cache)
        print(f"Local brand link cache normalized: {cache_file}")
        print(f"Updated entries: {changed}")
        return

    begin_date, end_date = get_date_range(args)

    if not PB_TOKEN:
        raise SystemExit("PB_TOKEN is empty. Set it in config.py before running.")

    print(f"\nFetching PartnerBoost orders: {begin_date} to {end_date}")
    transactions = fetch_transactions(
        base_url=PB_API_BASE_URL,
        token=PB_TOKEN,
        begin_date=begin_date,
        end_date=end_date,
        status=PB_TRANSACTION_STATUS,
        limit=PB_TRANSACTION_PAGE_LIMIT,
    )
    print(f"Fetched orders: {len(transactions)}")

    bids_file = output_path(args.bids_output or PB_ORDER_BIDS_OUTPUT_FILE)
    write_order_bids_file(
        transactions=transactions,
        begin_date=begin_date,
        end_date=end_date,
        path=bids_file,
    )
    print(f"Order bids written to: {bids_file}")

    if args.bids_only:
        print("Bids-only mode enabled. Link lookup and config.py update skipped.")
        return

    cache_file = cache_path()
    cache = load_cache(cache_file)
    targets, stats, failures = resolve_targets(transactions, cache)
    save_cache(cache_file, cache)
    write_order_bids_file(
        transactions=transactions,
        begin_date=begin_date,
        end_date=end_date,
        path=bids_file,
        targets=targets,
        failures=failures,
        stats=stats,
    )
    print(f"Order links written to: {bids_file}")

    if not targets:
        raise SystemExit("No target URLs were resolved. config.py was not changed.")

    print_preview(targets, stats)
    if confirm_write(args):
        update_config_target_urls(CONFIG_PATH, targets)
        print(f"\nUpdated TARGET_URLS in {CONFIG_PATH.name}.")
        if args.run_main:
            run_main_script()
        else:
            print("Review the list, then run: python main.py")
    else:
        print("\nconfig.py was not changed.")


if __name__ == "__main__":
    main()
