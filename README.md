# AdsPower + PartnerBoost 批量开链接工具

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

首次使用时复制配置模板：

```bash
copy config.example.py config.py
copy .env.example .env
```

把账号和 token 填到 `.env`：

```text
ADSPOWER_API_BASE_URL=http://localhost:50325
ADSPOWER_USER_ID=your_adspower_user_id
ADSPOWER_USER_IDS=env_id_1,env_id_2,env_id_3
ADSPOWER_API_KEY=your_adspower_api_key

PB_API_BASE_URL=https://app.partnerboost.com
PB_TOKEN=your_partnerboost_token
PB_LINK_UID=
```

`config.py` 只保留业务配置，例如：

```python
TAB_COUNT_PER_URL = 10
WAIT_TIME_BETWEEN_TABS = 1
TARGET_URLS = []
```

如果只使用一个 AdsPower 环境，可以只填 `ADSPOWER_USER_ID`。如果要并行使用多个环境，填写 `ADSPOWER_USER_IDS`，多个环境 ID 用英文逗号分隔。脚本会把订单链接按轮询方式平均分配到多个环境，例如 10 个链接、3 个环境会分成 4/3/3。

### 自动操作

推荐用一条命令跑完整流程：

```bash
python generate_urls.py --date 2026-04-25 --run-main
```

这条命令会自动完成：

1. 获取指定日期的 PartnerBoost 订单。
2. 根据每笔订单的 `bid/brand_id` 查询推广链接。
3. 更新 `tmp_order_bids.json`，方便查看订单和链接结果。
4. 自动写入 `config.py` 的 `TARGET_URLS`。
5. 自动运行 `main.py`，通过 AdsPower 批量打开链接。
6. 生成执行报告。

如果只想检查某天订单 bid，不查询链接、不修改 `config.py`：

```bash
python generate_urls.py --date 2026-04-25 --bids-only
```

如果只想生成链接并写入 `config.py`，但不运行 `main.py`：

```bash
python generate_urls.py --date 2026-04-25 --yes
```

执行结果文件：

```text
tmp_order_bids.json
tmp_run_report_summary.txt
tmp_run_report.json
tmp_run_console.log
run_reports/
```

优先查看 `tmp_run_report_summary.txt`，这是最近一次执行的中文摘要。

`tmp_run_console.log` 会保存最近一次运行时终端里输出的完整日志。

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
