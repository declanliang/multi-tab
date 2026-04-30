"""
Example configuration for AdsPower multi-tab opener.
Copy this file to config.py. Credentials are read from .env.
"""

import os

from dotenv import load_dotenv


load_dotenv()

# ==================== AdsPower API ====================
API_BASE_URL = os.getenv("ADSPOWER_API_BASE_URL", "http://localhost:50325")
USER_ID = os.getenv("ADSPOWER_USER_ID", "")
API_KEY = os.getenv("ADSPOWER_API_KEY", "")

# ==================== PartnerBoost API ====================
PB_API_BASE_URL = os.getenv("PB_API_BASE_URL", "https://app.partnerboost.com")
PB_TOKEN = os.getenv("PB_TOKEN", "")

# Transaction API settings. Status "All" keeps every order status.
PB_TRANSACTION_STATUS = "All"
PB_TRANSACTION_PAGE_LIMIT = 2000

# Storefront link API settings. Keep uid empty if you do not need it.
PB_LINK_UID = os.getenv("PB_LINK_UID", "")

# Local brand_id -> storefront link cache.
PB_BRAND_LINK_CACHE_FILE = "brand_links.json"

# Temporary output for checking fetched order bids during testing.
PB_ORDER_BIDS_OUTPUT_FILE = "tmp_order_bids.json"

# Execution report files written by main.py.
EXECUTION_REPORT_FILE = "tmp_run_report.json"
EXECUTION_REPORT_SUMMARY_FILE = "tmp_run_report_summary.txt"
EXECUTION_REPORT_HISTORY_DIR = "run_reports"

# ==================== Task Settings ====================
# Manual URLs, or URLs written by generate_urls.py after your confirmation.
TARGET_URLS = []

# Open count for each URL.
TAB_COUNT_PER_URL = 10

# Delay between opening tabs (seconds).
WAIT_TIME_BETWEEN_TABS = 1

# ==================== Advanced ====================
# Force-close existing AdsPower browser before processing first URL.
FORCE_CLOSE_BROWSER = True

# Wait time after browser startup (seconds).
BROWSER_STARTUP_WAIT = 3

# Retry settings for AdsPower browser lifecycle.
BROWSER_STOP_RETRY_COUNT = 3
BROWSER_STOP_RETRY_WAIT = 5
BROWSER_START_RETRY_COUNT = 3
BROWSER_START_RETRY_WAIT = 5
BROWSER_CONNECT_RETRY_COUNT = 3
BROWSER_CONNECT_RETRY_WAIT = 3
