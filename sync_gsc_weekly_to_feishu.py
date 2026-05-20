from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


REQUIRED_FIELDS = {
    "站点": {"type": 1, "property": None},
    "周开始日期": {
        "type": 5,
        "property": {"date_formatter": "yyyy-MM-dd", "auto_fill": False},
    },
    "周结束日期": {
        "type": 5,
        "property": {"date_formatter": "yyyy-MM-dd", "auto_fill": False},
    },
    "点击": {"type": 2, "property": {"formatter": "0"}},
    "展现": {"type": 2, "property": {"formatter": "0"}},
    "唯一键": {"type": 1, "property": None},
    "同步时间": {
        "type": 5,
        "property": {"date_formatter": "yyyy-MM-dd HH:mm", "auto_fill": False},
    },
}


@dataclass(frozen=True)
class Config:
    site_url: str
    google_token_file: Path
    feishu_app_id: str
    feishu_app_secret: str
    feishu_app_token: str
    feishu_table_id: str
    google_client_secret_file: Path | None = None
    google_oauth_client_json: str | None = None


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_config(env_file: Path) -> Config:
    load_dotenv(env_file)
    google_token_file = Path(os.environ.get("GOOGLE_TOKEN_FILE", ".secrets/gsc_token.json"))
    google_client_secret_file = os.environ.get("GOOGLE_CLIENT_SECRET_FILE", "").strip()
    google_oauth_client_json = os.environ.get("GOOGLE_OAUTH_CLIENT_JSON", "").strip()
    if (
        not google_client_secret_file
        and not google_oauth_client_json
        and not google_token_file.exists()
    ):
        raise RuntimeError(
            "Provide GOOGLE_CLIENT_SECRET_FILE or GOOGLE_OAUTH_CLIENT_JSON for the first OAuth run."
        )

    return Config(
        site_url=env_required("GSC_SITE_URL"),
        google_token_file=google_token_file,
        google_client_secret_file=Path(google_client_secret_file)
        if google_client_secret_file
        else None,
        google_oauth_client_json=google_oauth_client_json or None,
        feishu_app_id=env_required("FEISHU_APP_ID"),
        feishu_app_secret=env_required("FEISHU_APP_SECRET"),
        feishu_app_token=env_required("FEISHU_APP_TOKEN"),
        feishu_table_id=env_required("FEISHU_TABLE_ID"),
    )


def get_google_credentials(config: Config) -> Credentials:
    creds: Credentials | None = None
    token_file = config.google_token_file

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), GSC_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())

    if not creds or not creds.valid:
        if config.google_oauth_client_json:
            flow = InstalledAppFlow.from_client_config(
                json.loads(config.google_oauth_client_json), GSC_SCOPES
            )
        elif config.google_client_secret_file:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.google_client_secret_file), GSC_SCOPES
            )
        else:
            raise RuntimeError("Google OAuth client config was not provided.")

        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            authorization_prompt_message=(
                "Open this URL if the browser does not open automatically:\n{url}\n"
            ),
        )

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers=headers,
        json=payload,
        params=params,
        timeout=60,
    )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"{method} {url} returned non-JSON status {response.status_code}: "
            f"{response.text[:500]}"
        ) from exc
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed: HTTP {response.status_code} {data}")
    return data


def query_gsc_week(
    creds: Credentials,
    site_url: str,
    start_date: date,
    end_date: date,
    data_state: str,
) -> dict[str, float]:
    encoded_site = quote(site_url, safe="")
    url = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        f"{encoded_site}/searchAnalytics/query"
    )
    payload = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": [],
        "aggregationType": "byProperty",
        "dataState": data_state,
    }
    data = request_json(
        "POST",
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
        payload=payload,
    )
    rows = data.get("rows") or []
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
    row = rows[0]
    return {
        "clicks": float(row.get("clicks", 0)),
        "impressions": float(row.get("impressions", 0)),
        "ctr": float(row.get("ctr", 0)),
        "position": float(row.get("position", 0)),
    }


def get_feishu_tenant_token(config: Config) -> str:
    data = request_json(
        "POST",
        f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal",
        payload={"app_id": config.feishu_app_id, "app_secret": config.feishu_app_secret},
    )
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu tenant token error: {data}")
    return data["tenant_access_token"]


def feishu_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def check_feishu_response(data: dict[str, Any], action: str) -> dict[str, Any]:
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu {action} failed: {data}")
    return data.get("data") or {}


def list_feishu_fields(config: Config, token: str) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    page_token = ""
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        data = request_json(
            "GET",
            (
                f"{FEISHU_BASE_URL}/bitable/v1/apps/{config.feishu_app_token}"
                f"/tables/{config.feishu_table_id}/fields"
            ),
            headers=feishu_headers(token),
            params=params,
        )
        body = check_feishu_response(data, "list fields")
        for field in body.get("items", []):
            fields[field.get("field_name", "")] = field
        if not body.get("has_more"):
            return fields
        page_token = body.get("page_token", "")


def ensure_feishu_fields(config: Config, token: str) -> None:
    existing = list_feishu_fields(config, token)
    for field_name, definition in REQUIRED_FIELDS.items():
        if field_name in existing:
            continue
        payload = {
            "field_name": field_name,
            "type": definition["type"],
        }
        if definition["property"] is not None:
            payload["property"] = definition["property"]
        data = request_json(
            "POST",
            (
                f"{FEISHU_BASE_URL}/bitable/v1/apps/{config.feishu_app_token}"
                f"/tables/{config.feishu_table_id}/fields"
            ),
            headers=feishu_headers(token),
            payload=payload,
        )
        check_feishu_response(data, f"create field {field_name}")


def normalize_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces = []
        for item in value:
            if isinstance(item, dict):
                pieces.append(str(item.get("text", "")))
            else:
                pieces.append(str(item))
        return "".join(pieces)
    return str(value)


def list_existing_records(config: Config, token: str) -> dict[str, str]:
    records: dict[str, str] = {}
    page_token = ""
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        data = request_json(
            "GET",
            (
                f"{FEISHU_BASE_URL}/bitable/v1/apps/{config.feishu_app_token}"
                f"/tables/{config.feishu_table_id}/records"
            ),
            headers=feishu_headers(token),
            params=params,
        )
        body = check_feishu_response(data, "list records")
        for record in body.get("items", []):
            fields = record.get("fields") or {}
            unique_key = normalize_text_value(fields.get("唯一键"))
            if unique_key:
                records[unique_key] = record["record_id"]
        if not body.get("has_more"):
            return records
        page_token = body.get("page_token", "")


def batch_create_records(
    config: Config,
    token: str,
    records: list[dict[str, Any]],
) -> int:
    if not records:
        return 0
    data = request_json(
        "POST",
        (
            f"{FEISHU_BASE_URL}/bitable/v1/apps/{config.feishu_app_token}"
            f"/tables/{config.feishu_table_id}/records/batch_create"
        ),
        headers=feishu_headers(token),
        payload={"records": [{"fields": record} for record in records]},
    )
    body = check_feishu_response(data, "batch create records")
    return len(body.get("records", []))


def batch_update_records(
    config: Config,
    token: str,
    records: list[dict[str, Any]],
) -> int:
    if not records:
        return 0
    data = request_json(
        "POST",
        (
            f"{FEISHU_BASE_URL}/bitable/v1/apps/{config.feishu_app_token}"
            f"/tables/{config.feishu_table_id}/records/batch_update"
        ),
        headers=feishu_headers(token),
        payload={"records": records},
    )
    body = check_feishu_response(data, "batch update records")
    return len(body.get("records", []))


def month_ranges(year_month: str, through: date | None = None) -> list[tuple[date, date]]:
    year, month = map(int, year_month.split("-", 1))
    last_day = calendar.monthrange(year, month)[1]
    current = date(year, month, 1)
    month_end = date(year, month, last_day)
    if through is None:
        through = month_end
    month_end = min(month_end, through)
    ranges: list[tuple[date, date]] = []

    while current <= month_end:
        days_until_sunday = 6 - current.weekday()
        end = min(current + timedelta(days=days_until_sunday), month_end)
        ranges.append((current, end))
        current = end + timedelta(days=1)

    return ranges


def date_to_ms(value: date) -> int:
    dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def now_to_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def build_weekly_records(
    creds: Credentials,
    site_url: str,
    year_month: str,
    data_state: str,
    through: date | None,
) -> list[dict[str, Any]]:
    sync_time = now_to_ms()
    records = []
    for start_date, end_date in month_ranges(year_month, through):
        metrics = query_gsc_week(creds, site_url, start_date, end_date, data_state)
        unique_key = f"{site_url}|{start_date.isoformat()}|{end_date.isoformat()}"
        records.append(
            {
                "站点": site_url,
                "周开始日期": date_to_ms(start_date),
                "周结束日期": date_to_ms(end_date),
                "点击": int(round(metrics["clicks"])),
                "展现": int(round(metrics["impressions"])),
                "唯一键": unique_key,
                "同步时间": sync_time,
            }
        )
    return records


def sync_records(config: Config, records: list[dict[str, Any]]) -> tuple[int, int]:
    token = get_feishu_tenant_token(config)
    ensure_feishu_fields(config, token)
    existing = list_existing_records(config, token)

    create_records = []
    update_records = []
    for record in records:
        unique_key = record["唯一键"]
        record_id = existing.get(unique_key)
        if record_id:
            update_records.append({"record_id": record_id, "fields": record})
        else:
            create_records.append(record)

    created = batch_create_records(config, token, create_records)
    updated = batch_update_records(config, token, update_records)
    return created, updated


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync weekly Google Search Console clicks/impressions to Feishu Bitable."
    )
    parser.add_argument("--env-file", default=".env", help="Path to dotenv config.")
    parser.add_argument(
        "--month",
        default=None,
        help="Month in YYYY-MM format. Defaults to the current month.",
    )
    parser.add_argument(
        "--through",
        default=None,
        help="Last date to include, in YYYY-MM-DD. Defaults to today for the current month.",
    )
    parser.add_argument(
        "--data-state",
        default="final",
        choices=["final", "all"],
        help="GSC dataState. Use final for stable reports; all may include fresh data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print GSC rows; do not write Feishu.",
    )
    parser.add_argument("--output", default=None, help="Optional JSON export path.")
    return parser.parse_args(argv)


def default_month() -> str:
    return date.today().strftime("%Y-%m")


def default_through(year_month: str) -> date:
    year, month = map(int, year_month.split("-", 1))
    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)
    today = date.today()
    if today.year == year and today.month == month:
        return today
    return month_end


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config = load_config(Path(args.env_file))
    creds = get_google_credentials(config)
    year_month = args.month or default_month()
    through = date.fromisoformat(args.through) if args.through else default_through(year_month)
    records = build_weekly_records(
        creds=creds,
        site_url=config.site_url,
        year_month=year_month,
        data_state=args.data_state,
        through=through,
    )

    print(json.dumps(records, ensure_ascii=False, indent=2))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.dry_run:
        return 0

    created, updated = sync_records(config, records)
    print(
        json.dumps(
            {
                "month": year_month,
                "site_url": config.site_url,
                "created": created,
                "updated": updated,
                "total": len(records),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
