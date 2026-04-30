"""
Example configuration for AdsPower multi-tab opener.
Copy this file to config.py and fill in your local credentials.
"""

# ==================== AdsPower API ====================
API_BASE_URL = "http://localhost:50325"
USER_ID = "your_adspower_user_id"
API_KEY = ""

# ==================== PartnerBoost API ====================
PB_API_BASE_URL = "https://app.partnerboost.com"
PB_TOKEN = ""

# Transaction API settings. Status "All" keeps every order status.
PB_TRANSACTION_STATUS = "All"
PB_TRANSACTION_PAGE_LIMIT = 2000

# Storefront link API settings. Keep uid empty if you do not need it.
PB_LINK_UID = ""

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
