# AdsPower + PartnerBoost 批量开链接工具

python generate_urls.py --date 2026-04-25 --run-main

## 项目介绍

这个项目用于把 PartnerBoost 订单转成推广链接，并通过 AdsPower 指纹浏览器批量打开。

项目支持两种方式：

- 自动方式：输入一个日期，脚本自动获取该日期的订单、查询推广链接、写入 `config.py`、运行 `main.py`，并生成执行报告。
- 手动方式：你直接在 `config.py` 的 `TARGET_URLS` 里填写推广链接，然后运行 `main.py`。

本地会维护一份品牌链接库 `brand_links.json`。以后遇到同一个 `bid`，会优先使用本地保存的 `link`，本地没有时才调用 PartnerBoost API 获取。

## 如何操作

先安装依赖：

```bash
pip install -r requirements.txt
```

编辑 `config.py`，确认这些配置：

```bash
copy config.example.py config.py
```

```python
USER_ID = "your_adspower_user_id"
API_KEY = "your_adspower_api_key"
PB_TOKEN = "your_partnerboost_token"
TAB_COUNT_PER_URL = 20
```

### 自动操作

推荐用一条命令跑完整流程：

```bash
python generate_urls.py --date 2026-04-26 --run-main
```

这条命令会自动完成：

1. 获取 `2026-04-26` 的 PartnerBoost 订单。
2. 根据每笔订单的 `bid/brand_id` 查询推广链接。
3. 更新 `tmp_order_bids.json`，方便查看订单和链接结果。
4. 自动写入 `config.py` 的 `TARGET_URLS`。
5. 自动运行 `main.py`，通过 AdsPower 批量打开链接。
6. 生成执行报告。

如果只想检查某天订单 bid，不查询链接、不修改 `config.py`：

```bash
python generate_urls.py --date 2026-04-26 --bids-only
```

如果只想生成链接并写入 `config.py`，但不运行 `main.py`：

```bash
python generate_urls.py --date 2026-04-26 --yes
```

执行结果文件：

```text
tmp_order_bids.json
tmp_run_report.json
tmp_run_report_summary.txt
run_reports/
```

`tmp_order_bids.json` 用于查看订单和链接结果。正常查到链接时：

```json
{
  "bid": "136533",
  "merchant_name": "VEVOR",
  "order_id": "C291M-xxxx",
  "link_status": "resolved",
  "link": "https://pboost.me/EKMSwYk",
  "link_error": ""
}
```

如果某个 bid 不支持生成链接：

```json
{
  "link_status": "failed",
  "link": "",
  "link_error": "Bid does not support brand link tracking."
}
```

`tmp_run_report_summary.txt` 是最近一次执行的中文摘要，优先看这个文件。

`tmp_run_report.json` 是最近一次 `main.py` 的详细 JSON 报告，`run_reports/` 会保存历史报告。

### 手动操作

手动把链接写入 `config.py`：

```python
TARGET_URLS = [
    "https://pboost.me/xxxx",  # Brand A
    "https://pboost.me/yyyy",  # Brand B
]
```

然后运行：

```bash
python main.py
```

### 维护本地链接库

整理本地品牌链接库：

```bash
python generate_urls.py --refresh-local-links
```

`brand_links.json` 只需要保留这种结构：

```json
{
  "136533": {
    "bid": "136533",
    "brand_name": "VEVOR",
    "link": "https://pboost.me/EKMSwYk"
  }
}
```
