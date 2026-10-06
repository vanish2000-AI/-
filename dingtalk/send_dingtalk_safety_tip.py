#!/usr/bin/env python3
"""Send one daily safety tip to a DingTalk custom robot.

This script intentionally uses only Python's standard library. Secrets are
read from environment variables so they never need to be committed to GitHub.
"""

from __future__ import annotations

import base64
import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent


def get_config_value(config: object, name: str, default: object = None) -> object:
    if not isinstance(config, dict):
        return default
    return config.get(name, default)


def as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        return default
    return bool(value)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON 无效：{path}；{exc}") from exc


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def shanghai_now() -> datetime:
    # Asia/Shanghai has no DST. A fixed offset also keeps this script
    # independent of the runner machine's local timezone.
    return datetime.now(timezone(timedelta(hours=8)))


def choose_tip(config: dict) -> str:
    tips = [
        str(item).strip()
        for item in (get_config_value(config, "tips", []) or [])
        if str(item).strip()
    ]
    if not tips:
        raise RuntimeError("tips 至少需要一条非空提示语。")
    day_of_year = int(shanghai_now().strftime("%j"))
    return tips[(day_of_year - 1) % len(tips)]


def public_image_base_url() -> str:
    configured = os.environ.get("DINGTALK_IMAGE_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    ref_name = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"
    if repository:
        return f"https://raw.githubusercontent.com/{repository}/{quote(ref_name, safe='')}"

    return ""


def choose_image(config: dict) -> dict[str, str | None]:
    enabled = as_bool(get_config_value(config, "imageLibraryEnabled", False))
    if not enabled:
        return {"name": None, "local_path": None, "public_url": None, "warning": None}

    configured_path = str(
        get_config_value(config, "imageLibraryPath", "dingtalk/image-library.json")
    ).strip()
    library_path = resolve_path(configured_path, REPOSITORY_ROOT)
    library = load_json(library_path)
    if not isinstance(library, dict):
        raise RuntimeError(f"图片库清单必须是 JSON 对象：{library_path}")

    items = [
        item
        for item in (get_config_value(library, "items", []) or [])
        if isinstance(item, dict) and as_bool(item.get("enabled", True), True)
    ]
    if not items:
        raise RuntimeError(f"图片库没有 enabled=true 的图片：{library_path}")

    selected = secrets.choice(items)
    name = str(selected.get("name", "未命名图片")).strip() or "未命名图片"
    local_path_value = str(selected.get("localPath", "")).strip()
    public_url = str(selected.get("publicUrl", "")).strip()

    if not local_path_value:
        raise RuntimeError(f"图片库条目缺少 localPath：{name}")

    local_path = resolve_path(local_path_value, REPOSITORY_ROOT)
    if not local_path.is_file():
        raise RuntimeError(f"图片库条目的本地文件不存在：{local_path}")

    if public_url and not public_url.startswith(("http://", "https://")):
        raise RuntimeError(f"图片库条目 publicUrl 必须是 http/https：{name}")

    if not public_url:
        base_url = public_image_base_url()
        if base_url:
            relative = local_path.relative_to(REPOSITORY_ROOT).as_posix()
            public_url = f"{base_url}/{quote(relative, safe='/')}"

    warning = None
    if not public_url:
        warning = (
            f"随机选中图片“{name}”，但没有公网地址；"
            "钉钉无法读取 GitHub Runner 或本机文件，已按 imageFallback 处理。"
        )

    return {
        "name": name,
        "local_path": str(local_path),
        "public_url": public_url or None,
        "warning": warning,
    }


def build_payload(config: dict) -> tuple[dict, str, str | None, str | None]:
    tip = choose_tip(config)
    date_text = shanghai_now().strftime("%Y-%m-%d")
    content = f"【每日安全提示】{date_text}\n{tip}"

    keyword = str(get_config_value(config, "keyword", "") or "").strip()
    if keyword and keyword.casefold() not in content.casefold():
        content = f"{keyword} {content}"

    image = choose_image(config)
    image_url = image["public_url"]
    image_name = image["name"]

    if image_name and not image_url:
        fallback = str(get_config_value(config, "imageFallback", "text") or "text")
        fallback = fallback.strip().lower()
        if fallback == "error":
            raise RuntimeError(str(image["warning"]))
        if fallback != "text":
            raise RuntimeError(f"imageFallback 只支持 text 或 error，当前值：{fallback}")

    message_type = str(get_config_value(config, "messageType", "text") or "text")
    message_type = message_type.strip().lower()

    if image_url:
        message_type = "markdown"

    if message_type == "text":
        payload = {
            "msgtype": "text",
            "text": {"content": content},
        }
    elif message_type == "markdown":
        markdown_text = content
        if image_url:
            markdown_text += f"\n\n![安全提示图片]({image_url})"
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": "每日安全提示", "text": markdown_text},
        }
    else:
        raise RuntimeError(f"messageType 只支持 text 或 markdown，当前值：{message_type}")

    payload["at"] = {
        "atMobiles": [],
        "isAtAll": as_bool(get_config_value(config, "atAll", False)),
    }
    return payload, content, image_name, image["warning"]


def signed_webhook_url(webhook_url: str, secret: str) -> str:
    if not secret:
        return webhook_url

    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("ascii")
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}{urlencode({'timestamp': timestamp, 'sign': sign})}"


def post_message(webhook_url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        signed_webhook_url(
            webhook_url,
            os.environ.get("DINGTALK_SECRET", "").strip(),
        ),
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"钉钉 Webhook HTTP {exc.code}：{detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"调用钉钉 Webhook 失败：{exc.reason}") from exc

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"钉钉返回的不是有效 JSON：{raw}") from exc

    error_code = result.get("errcode")
    if error_code is not None and int(error_code) != 0:
        raise RuntimeError(
            f"钉钉返回错误：errcode={error_code}, errmsg={result.get('errmsg', '')}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a DingTalk daily safety tip.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print the payload without calling DingTalk.",
    )
    args = parser.parse_args()

    webhook_url = os.environ.get("DINGTALK_WEBHOOK_URL", "").strip()
    if not webhook_url and not args.dry_run:
        raise RuntimeError("缺少 GitHub Actions Secret：DINGTALK_WEBHOOK_URL")
    if webhook_url and not webhook_url.startswith("https://oapi.dingtalk.com/robot/send"):
        raise RuntimeError("DINGTALK_WEBHOOK_URL 不是钉钉自定义机器人地址。")

    config_path = os.environ.get(
        "DINGTALK_CONFIG_PATH",
        str(REPOSITORY_ROOT / "dingtalk" / "config.json"),
    )
    config = load_json(resolve_path(config_path, REPOSITORY_ROOT))
    if not isinstance(config, dict):
        raise RuntimeError("钉钉配置必须是 JSON 对象。")

    payload, preview, image_name, image_warning = build_payload(config)
    if args.dry_run:
        print(f"DryRun：不会调用钉钉。消息预览：{preview.replace(chr(10), ' ')}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if image_name:
            print(f"DryRun：本次随机图片：{image_name}")
        if image_warning:
            print(f"DryRun：图片处理提示：{image_warning}")
        return 0

    result = post_message(webhook_url, payload)
    print(f"已发送钉钉每日安全提示：{preview.replace(chr(10), ' ')}")
    if image_name:
        print(f"本次随机图片：{image_name}")
    if image_warning:
        print(f"图片处理提示：{image_warning}")
    print(f"钉钉返回：{result}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - concise CI failure output
        print(f"发送失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
