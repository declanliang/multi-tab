"""
AdsPower multi-tab opener.
Main script; configure values in config.py.
"""

import io
import ast
import json
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from config import (
    API_BASE_URL,
    API_KEY,
    BROWSER_CONNECT_RETRY_COUNT,
    BROWSER_CONNECT_RETRY_WAIT,
    BROWSER_START_RETRY_COUNT,
    BROWSER_START_RETRY_WAIT,
    BROWSER_STARTUP_WAIT,
    BROWSER_STOP_RETRY_COUNT,
    BROWSER_STOP_RETRY_WAIT,
    EXECUTION_REPORT_FILE,
    EXECUTION_REPORT_HISTORY_DIR,
    EXECUTION_REPORT_SUMMARY_FILE,
    FORCE_CLOSE_BROWSER,
    PB_BRAND_LINK_CACHE_FILE,
    PB_ORDER_BIDS_OUTPUT_FILE,
    TAB_COUNT_PER_URL,
    TARGET_URLS,
    USER_ID,
    WAIT_TIME_BETWEEN_TABS,
)


if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.py"
LAST_BROWSER_ERROR = ""


def now_iso():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def project_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def build_headers():
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


def read_json_file(path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"   WARN: failed to read {path.name}: {str(exc)[:120]}")
    return {}


def find_target_urls_assignment(tree):
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


def load_target_url_comments():
    """Read inline comments after TARGET_URLS items, e.g. # VEVOR."""
    try:
        source = CONFIG_PATH.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        node = find_target_urls_assignment(tree)
        if node is None or node.end_lineno is None:
            return {}

        comments_by_url = {}
        lines = source.splitlines()
        for line in lines[node.lineno - 1 : node.end_lineno]:
            match = re.search(r"['\"](https?://[^'\"]+)['\"]", line)
            if not match:
                continue
            url = match.group(1)
            comment = ""
            if "#" in line:
                comment = line.split("#", 1)[1].strip()
            comments_by_url.setdefault(url, []).append(comment)
        return comments_by_url
    except Exception as exc:
        print(f"   WARN: failed to read TARGET_URLS comments: {str(exc)[:120]}")
        return {}


def load_brand_link_cache():
    path = project_path(PB_BRAND_LINK_CACHE_FILE)
    payload = read_json_file(path)
    return payload if isinstance(payload, dict) else {}


def infer_link_resolution(payload):
    recorded = payload.get("link_resolution")
    if isinstance(recorded, dict):
        return {
            "local_cache_orders": int(recorded.get("local_cache_orders") or 0),
            "api_orders": int(recorded.get("api_orders") or 0),
            "api_lookups": int(recorded.get("api_lookups") or 0),
            "cache_hits": int(recorded.get("cache_hits") or 0),
            "skipped_orders": int(recorded.get("skipped_orders") or 0),
            "unknown_source_orders": int(recorded.get("unknown_source_orders") or 0),
        }

    brand_cache = load_brand_link_cache()
    local_cache_orders = 0
    unknown_source_orders = 0
    failed_orders = 0
    for order in payload.get("orders") or []:
        link_status = str(order.get("link_status") or "")
        link = str(order.get("link") or "")
        bid = str(order.get("bid") or order.get("brand_id") or "")
        if link_status == "failed":
            failed_orders += 1
            continue
        if not link:
            continue
        cached_link = str((brand_cache.get(bid) or {}).get("link") or "")
        if cached_link == link:
            local_cache_orders += 1
        else:
            unknown_source_orders += 1

    return {
        "local_cache_orders": local_cache_orders,
        "api_orders": 0,
        "api_lookups": 0,
        "cache_hits": local_cache_orders,
        "skipped_orders": failed_orders,
        "unknown_source_orders": unknown_source_orders,
    }


def load_order_link_context():
    path = project_path(PB_ORDER_BIDS_OUTPUT_FILE)
    payload = read_json_file(path)
    orders_by_link = {}
    failed_orders = []
    for order in payload.get("orders") or []:
        link = str(order.get("link") or "").strip()
        if str(order.get("link_status") or "") == "failed":
            failed_orders.append(
                {
                    "index": order.get("index"),
                    "bid": str(order.get("bid") or order.get("brand_id") or ""),
                    "brand_name": str(order.get("merchant_name") or ""),
                    "order_id": str(order.get("order_id") or ""),
                    "order_status": str(order.get("status") or ""),
                    "link_error": str(order.get("link_error") or ""),
                }
            )
        if not link:
            continue
        orders_by_link.setdefault(link, []).append(order)

    source = {
        "file": str(path),
        "begin_date": payload.get("begin_date") or "",
        "end_date": payload.get("end_date") or "",
        "total_orders": payload.get("total_orders") or 0,
        "resolved_links": payload.get("resolved_links") or 0,
        "failed_links": payload.get("failed_links") or 0,
        "failed_orders": failed_orders,
        "link_resolution": infer_link_resolution(payload),
    }
    return orders_by_link, source


def build_target_contexts(urls):
    orders_by_link, order_source = load_order_link_context()
    comments_by_url = load_target_url_comments()
    contexts = []
    matched_orders = 0

    for url in urls:
        order = None
        if orders_by_link.get(url):
            order = orders_by_link[url].pop(0)
            matched_orders += 1

        comment = ""
        if comments_by_url.get(url):
            comment = comments_by_url[url].pop(0)

        contexts.append(
            {
                "url": url,
                "bid": str((order or {}).get("bid") or (order or {}).get("brand_id") or ""),
                "brand_name": str((order or {}).get("merchant_name") or comment or ""),
                "order_id": str((order or {}).get("order_id") or ""),
                "order_status": str((order or {}).get("status") or ""),
            }
        )

    order_source["matched_orders"] = matched_orders
    return contexts, order_source


def build_report_shell(urls, target_contexts, order_source, started_at):
    if order_source.get("matched_orders"):
        begin_date = order_source.get("begin_date") or ""
        end_date = order_source.get("end_date") or ""
    else:
        begin_date = ""
        end_date = ""
    if begin_date and end_date and begin_date == end_date:
        business_date = begin_date
    elif begin_date or end_date:
        business_date = f"{begin_date} to {end_date}".strip()
    else:
        business_date = ""

    return {
        "started_at": started_at,
        "completed_at": "",
        "business_date": business_date,
        "success": False,
        "order_source": order_source,
        "settings": {
            "target_url_count": len(urls),
            "tabs_per_url": TAB_COUNT_PER_URL,
            "wait_time_between_tabs": WAIT_TIME_BETWEEN_TABS,
        },
        "targets": target_contexts,
        "batches": [],
        "summary": {},
    }


def summarize_report(report):
    batches = report["batches"]
    by_brand = {}
    for batch in batches:
        key = (
            batch.get("bid") or "",
            batch.get("brand_name") or "Unknown",
            batch.get("url") or "",
        )
        item = by_brand.setdefault(
            key,
            {
                "bid": batch.get("bid") or "",
                "brand_name": batch.get("brand_name") or "Unknown",
                "batches": 0,
                "requested_tabs": 0,
                "opened_tabs": 0,
                "failed_tabs": 0,
            },
        )
        item["batches"] += 1
        item["requested_tabs"] += int(batch.get("requested_tabs") or 0)
        item["opened_tabs"] += int(batch.get("opened_tabs") or 0)
        item["failed_tabs"] += int(batch.get("failed_tabs") or 0)

    report["summary"] = {
        "target_url_count": len(batches),
        "successful_batches": sum(1 for batch in batches if batch.get("success")),
        "failed_batches": sum(1 for batch in batches if not batch.get("success")),
        "requested_tabs_total": sum(int(batch.get("requested_tabs") or 0) for batch in batches),
        "opened_tabs_total": sum(int(batch.get("opened_tabs") or 0) for batch in batches),
        "failed_tabs_total": sum(int(batch.get("failed_tabs") or 0) for batch in batches),
        "link_resolution": report.get("order_source", {}).get("link_resolution") or {},
        "failed_link_orders": report.get("order_source", {}).get("failed_orders") or [],
        "brands": list(by_brand.values()),
    }
    return report


def readable_result(success):
    return "全部成功" if success else "部分失败"


def build_readable_summary_data(report):
    order_source = report.get("order_source") or {}
    summary = report.get("summary") or {}
    brands = summary.get("brands") or []
    link_resolution = summary.get("link_resolution") or {}
    return {
        "订单日期": report.get("business_date") or "未知",
        "运行时间": f"{report.get('started_at') or ''} ~ {report.get('completed_at') or ''}",
        "整体结果": readable_result(bool(report.get("success"))),
        "订单总数": int(order_source.get("total_orders") or 0),
        "品牌数量": len(brands),
        "链接获取成功": int(order_source.get("resolved_links") or 0),
        "链接获取失败": int(order_source.get("failed_links") or 0),
        "本地缓存获取订单数": int(link_resolution.get("local_cache_orders") or 0),
        "API获取订单数": int(link_resolution.get("api_orders") or 0),
        "API请求次数": int(link_resolution.get("api_lookups") or 0),
        "来源未知订单数": int(link_resolution.get("unknown_source_orders") or 0),
        "指纹浏览器链接批次数": int(summary.get("target_url_count") or 0),
        "成功批次": int(summary.get("successful_batches") or 0),
        "失败批次": int(summary.get("failed_batches") or 0),
        "计划打开网页数": int(summary.get("requested_tabs_total") or 0),
        "实际成功打开网页数": int(summary.get("opened_tabs_total") or 0),
        "打开失败网页数": int(summary.get("failed_tabs_total") or 0),
    }


def build_text_report(report):
    data = build_readable_summary_data(report)
    summary = report.get("summary") or {}
    failed_link_orders = summary.get("failed_link_orders") or []
    failed_batches = [batch for batch in report.get("batches") or [] if not batch.get("success")]

    lines = [
        "执行结果报告",
        "=" * 60,
        f"订单日期: {data['订单日期']}",
        f"运行时间: {data['运行时间']}",
        f"整体结果: {data['整体结果']}",
        "",
        "订单与链接",
        "-" * 60,
        f"订单总数: {data['订单总数']}",
        f"品牌数量: {data['品牌数量']}",
        f"链接获取成功: {data['链接获取成功']}",
        f"链接获取失败: {data['链接获取失败']}",
        f"本地缓存获取订单数: {data['本地缓存获取订单数']}",
        f"API获取订单数: {data['API获取订单数']}",
        f"API请求次数: {data['API请求次数']}",
    ]
    if data["来源未知订单数"]:
        lines.append(f"来源未知订单数: {data['来源未知订单数']}")

    lines.extend(
        [
            "",
            "指纹浏览器执行",
            "-" * 60,
            f"链接批次数: {data['指纹浏览器链接批次数']}",
            f"成功批次: {data['成功批次']}",
            f"失败批次: {data['失败批次']}",
            f"计划打开网页数: {data['计划打开网页数']}",
            f"实际成功打开网页数: {data['实际成功打开网页数']}",
            f"打开失败网页数: {data['打开失败网页数']}",
            "",
            "品牌明细",
            "-" * 60,
        ]
    )

    for item in summary.get("brands") or []:
        lines.append(
            f"- {item.get('brand_name') or 'Unknown'} "
            f"(bid={item.get('bid') or '-'}) | "
            f"订单/批次: {item.get('batches') or 0} | "
            f"计划: {item.get('requested_tabs') or 0} | "
            f"成功打开: {item.get('opened_tabs') or 0} | "
            f"失败: {item.get('failed_tabs') or 0}"
        )

    lines.extend(["", "链接获取失败明细", "-" * 60])
    if failed_link_orders:
        for order in failed_link_orders:
            lines.append(
                f"- {order.get('brand_name') or 'Unknown'} "
                f"(bid={order.get('bid') or '-'}) | "
                f"订单: {order.get('order_id') or '-'} | "
                f"原因: {order.get('link_error') or '-'}"
            )
    else:
        lines.append("- 无")

    lines.extend(["", "指纹浏览器失败明细", "-" * 60])
    if failed_batches:
        for batch in failed_batches:
            lines.append(
                f"- 第 {batch.get('index')} 批 | "
                f"{batch.get('brand_name') or 'Unknown'} "
                f"(bid={batch.get('bid') or '-'}) | "
                f"订单: {batch.get('order_id') or '-'} | "
                f"计划: {batch.get('requested_tabs') or 0} | "
                f"成功: {batch.get('opened_tabs') or 0} | "
                f"失败: {batch.get('failed_tabs') or 0} | "
                f"原因: {batch.get('error') or '-'}"
            )
            for error in batch.get("errors") or []:
                lines.append(
                    f"  - tab {error.get('tab_index')}: {error.get('error') or '-'}"
                )
    else:
        lines.append("- 无")

    return "\n".join(lines) + "\n"


def write_execution_report(report):
    report["completed_at"] = now_iso()
    summarize_report(report)
    report["readable_summary"] = build_readable_summary_data(report)
    text_report = build_text_report(report)

    latest_path = project_path(EXECUTION_REPORT_FILE)
    latest_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    latest_summary_path = project_path(EXECUTION_REPORT_SUMMARY_FILE)
    latest_summary_path.write_text(text_report, encoding="utf-8")

    history_dir = project_path(EXECUTION_REPORT_HISTORY_DIR)
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_part = report.get("business_date") or "manual"
    date_part = re.sub(r"[^0-9A-Za-z_-]+", "_", date_part).strip("_") or "manual"
    history_path = history_dir / f"run_report_{date_part}_{stamp}.json"
    history_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    history_summary_path = history_dir / f"run_report_{date_part}_{stamp}.txt"
    history_summary_path.write_text(text_report, encoding="utf-8")

    print(f"\nExecution report written: {latest_path}")
    print(f"Execution summary written: {latest_summary_path}")
    print(f"Execution report archived: {history_path}")
    print(f"Execution summary archived: {history_summary_path}")


def refresh_latest_report_order_source():
    report_path = project_path(EXECUTION_REPORT_FILE)
    report = read_json_file(report_path)
    if not report:
        print(f"No execution report found: {report_path}")
        return

    _, order_source = load_order_link_context()
    previous = report.get("order_source") or {}
    order_source["matched_orders"] = previous.get("matched_orders", 0)
    report["order_source"] = order_source
    summarize_report(report)
    report["readable_summary"] = build_readable_summary_data(report)
    text_report = build_text_report(report)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    project_path(EXECUTION_REPORT_SUMMARY_FILE).write_text(text_report, encoding="utf-8")
    print(f"Execution report refreshed: {report_path}")


def stop_browser_if_running(force=False, title="Closing browser if running"):
    """Stop AdsPower browser instance by user_id."""
    global LAST_BROWSER_ERROR
    if not force and not FORCE_CLOSE_BROWSER:
        return True

    print(f"\n{title}...")
    close_url = f"{API_BASE_URL}/api/v1/browser/stop"
    params = {"user_id": USER_ID}

    for attempt in range(1, BROWSER_STOP_RETRY_COUNT + 1):
        try:
            response = requests.get(
                close_url,
                params=params,
                headers=build_headers(),
                timeout=10,
            )
            result = response.json()
            msg = result.get("msg", "unknown response")

            if result.get("code") == 0:
                LAST_BROWSER_ERROR = ""
                print("   OK: browser stopped")
                time.sleep(BROWSER_STOP_RETRY_WAIT)
                return True

            if "not open" in str(msg).lower():
                LAST_BROWSER_ERROR = ""
                print(f"   OK: browser already closed ({msg})")
                time.sleep(1)
                return True

            LAST_BROWSER_ERROR = f"stop failed: {msg}"
            print(f"   WARN: {LAST_BROWSER_ERROR}")
        except Exception as exc:
            LAST_BROWSER_ERROR = f"failed to stop browser: {str(exc)[:120]}"
            print(f"   WARN: {LAST_BROWSER_ERROR}")

        if attempt < BROWSER_STOP_RETRY_COUNT:
            print(f"   Retry stop in {BROWSER_STOP_RETRY_WAIT}s ({attempt}/{BROWSER_STOP_RETRY_COUNT})")
            time.sleep(BROWSER_STOP_RETRY_WAIT)

    return False


def start_browser():
    global LAST_BROWSER_ERROR
    print("\nStarting browser...")
    start_url = f"{API_BASE_URL}/api/v1/browser/start"
    params = {
        "user_id": USER_ID,
        "open_tabs": 0,
        "ip_tab": 0,
        "headless": 0,
    }

    for attempt in range(1, BROWSER_START_RETRY_COUNT + 1):
        try:
            response = requests.get(
                start_url,
                params=params,
                headers=build_headers(),
                timeout=30,
            )
            result = response.json()

            if result.get("code") != 0:
                LAST_BROWSER_ERROR = f"start failed: {result.get('msg', 'unknown error')}"
                print(f"   ERROR: {LAST_BROWSER_ERROR}")
            else:
                data = result["data"]
                selenium_address = data["ws"]["selenium"]
                webdriver_path = data["webdriver"]

                LAST_BROWSER_ERROR = ""
                print("   OK: browser started")
                print(f"   - Debug port: {data.get('debug_port')}")
                return selenium_address, webdriver_path
        except Exception as exc:
            LAST_BROWSER_ERROR = f"start exception: {str(exc)[:120]}"
            print(f"   ERROR: {LAST_BROWSER_ERROR}")

        if attempt < BROWSER_START_RETRY_COUNT:
            print(f"   Retry start in {BROWSER_START_RETRY_WAIT}s ({attempt}/{BROWSER_START_RETRY_COUNT})")
            time.sleep(BROWSER_START_RETRY_WAIT)

    return None


def connect_to_browser(selenium_address, webdriver_path):
    global LAST_BROWSER_ERROR
    print("\nWaiting browser startup...")
    time.sleep(BROWSER_STARTUP_WAIT)

    print("Connecting to browser...")
    for attempt in range(1, BROWSER_CONNECT_RETRY_COUNT + 1):
        try:
            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", selenium_address)
            service = Service(executable_path=webdriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)

            initial_tabs = len(driver.window_handles)
            LAST_BROWSER_ERROR = ""
            print("   OK: connected")
            print(f"   - Initial tabs: {initial_tabs}")
            return driver, initial_tabs
        except Exception as exc:
            LAST_BROWSER_ERROR = f"connect failed: {str(exc)[:120]}"
            print(f"   ERROR: {LAST_BROWSER_ERROR}")

        if attempt < BROWSER_CONNECT_RETRY_COUNT:
            print(f"   Retry connect in {BROWSER_CONNECT_RETRY_WAIT}s ({attempt}/{BROWSER_CONNECT_RETRY_COUNT})")
            time.sleep(BROWSER_CONNECT_RETRY_WAIT)

    return None, 0


def clean_old_tabs(driver):
    """Keep only first tab before opening new ones."""
    try:
        handles = driver.window_handles
        if len(handles) <= 1:
            print("   Only 1 tab, no cleanup needed")
            return True

        print(f"   Cleaning old tabs: {len(handles) - 1} to close")
        keep_handle = handles[0]

        for idx, handle in enumerate(handles[1:], start=1):
            try:
                driver.switch_to.window(handle)
                driver.close()
                if idx % 5 == 0:
                    print(f"     Closed {idx}/{len(handles) - 1}")
            except Exception:
                pass

        driver.switch_to.window(keep_handle)
        print("   OK: cleanup completed")
        return True
    except Exception as exc:
        print(f"   WARN: cleanup failed: {str(exc)[:120]}")
        return True


def open_tabs(driver, initial_tabs, target_url, tab_count):
    print("\nCleaning tabs before opening target URL...")
    clean_old_tabs(driver)

    print(f"\nOpening tabs for: {target_url}")
    print(f"   - Count: {tab_count}")
    result = {
        "requested_tabs": tab_count,
        "opened_tabs": 0,
        "failed_tabs": 0,
        "initial_tabs": initial_tabs,
        "final_tabs": 0,
        "success": False,
        "errors": [],
    }

    try:
        for i in range(tab_count):
            print(f"   [{i + 1}/{tab_count}] opening...")
            try:
                driver.switch_to.new_window("tab")
                driver.get(target_url)
                result["opened_tabs"] += 1
                print("       OK")
            except Exception as exc:
                error = str(exc)[:120]
                result["failed_tabs"] += 1
                result["errors"].append({"tab_index": i + 1, "error": error})
                print(f"       ERROR: {error}")

            if i < tab_count - 1:
                time.sleep(WAIT_TIME_BETWEEN_TABS)

        final_tabs = len(driver.window_handles)
        result["final_tabs"] = final_tabs
        result["success"] = result["failed_tabs"] == 0
        print("\n   URL batch completed")
        print(f"   - Initial tabs: {initial_tabs}")
        print("   - Tabs after cleanup: 1")
        print(f"   - Added tabs: {result['opened_tabs']}")
        print(f"   - Failed tabs: {result['failed_tabs']}")
        print(f"   - Final tabs: {final_tabs}")
        return result
    except Exception as exc:
        result["failed_tabs"] = max(result["failed_tabs"], tab_count - result["opened_tabs"])
        result["errors"].append({"tab_index": None, "error": str(exc)[:120]})
        print(f"\n   ERROR: opening tabs failed: {exc}")
        traceback.print_exc()
        return result


def normalize_urls(urls):
    cleaned = []
    for url in urls:
        u = str(url).strip()
        if u:
            cleaned.append(u)
    return cleaned


def main():
    started_at = now_iso()
    print("=" * 60)
    print("AdsPower Multi-URL Tab Opener")
    print("=" * 60)

    urls = normalize_urls(TARGET_URLS)
    if not urls:
        print("\nERROR: TARGET_URLS is empty. Please set at least one URL in config.py")
        return

    print(f"\nConfigured URLs: {len(urls)}")
    print(f"Tabs per URL: {TAB_COUNT_PER_URL}")

    target_contexts, order_source = build_target_contexts(urls)
    report = build_report_shell(urls, target_contexts, order_source, started_at)
    all_success = True

    for idx, context in enumerate(target_contexts, start=1):
        url = context["url"]
        batch_report = {
            "index": idx,
            "url": url,
            "bid": context.get("bid") or "",
            "brand_name": context.get("brand_name") or "",
            "order_id": context.get("order_id") or "",
            "order_status": context.get("order_status") or "",
            "started_at": now_iso(),
            "completed_at": "",
            "requested_tabs": TAB_COUNT_PER_URL,
            "opened_tabs": 0,
            "failed_tabs": TAB_COUNT_PER_URL,
            "initial_tabs": 0,
            "final_tabs": 0,
            "success": False,
            "error": "",
            "errors": [],
        }

        print("\n" + "-" * 60)
        print(f"Processing URL {idx}/{len(urls)}: {url}")
        if batch_report["brand_name"]:
            print(f"Brand: {batch_report['brand_name']}")
        print("-" * 60)

        if idx == 1:
            cleanup_ok = stop_browser_if_running(force=False, title="Pre-run cleanup")
        else:
            cleanup_ok = stop_browser_if_running(force=True, title="Closing previous browser window")

        if not cleanup_ok:
            all_success = False
            batch_report["error"] = LAST_BROWSER_ERROR or "browser stop failed before start"
            batch_report["completed_at"] = now_iso()
            report["batches"].append(batch_report)
            continue

        browser_info = start_browser()
        if not browser_info:
            all_success = False
            batch_report["error"] = LAST_BROWSER_ERROR or "browser start failed"
            batch_report["completed_at"] = now_iso()
            report["batches"].append(batch_report)
            continue

        selenium_address, webdriver_path = browser_info
        driver, initial_tabs = connect_to_browser(selenium_address, webdriver_path)
        if not driver:
            all_success = False
            batch_report["initial_tabs"] = initial_tabs
            batch_report["error"] = LAST_BROWSER_ERROR or "webdriver connect failed"
            batch_report["completed_at"] = now_iso()
            report["batches"].append(batch_report)
            continue

        open_result = open_tabs(driver, initial_tabs, url, TAB_COUNT_PER_URL)
        batch_report.update(open_result)
        batch_report["completed_at"] = now_iso()
        if not open_result["success"]:
            batch_report["error"] = "one or more tabs failed"
        report["batches"].append(batch_report)
        all_success = all_success and open_result["success"]

        try:
            driver.quit()
            print("\nDisconnected webdriver session")
        except Exception:
            pass

    report["success"] = all_success
    write_execution_report(report)

    print("\n" + "=" * 60)
    if all_success:
        print("All URL batches completed")
    else:
        print("Completed with partial failures")
    print("=" * 60)
    print("\nNote: each URL was processed in a separate browser window/session.")


if __name__ == "__main__":
    try:
        if "--refresh-report" in sys.argv:
            refresh_latest_report_order_source()
        else:
            main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
