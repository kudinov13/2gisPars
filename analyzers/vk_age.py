import logging
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def get_vk_group_age(vk_url: str, service_token: str, timeout: int = 10) -> Optional[datetime]:
    if not vk_url or not service_token:
        return None

    screen_name = _extract_screen_name(vk_url)
    if not screen_name:
        return None

    try:
        resp = requests.get(
            "https://api.vk.com/method/groups.getById",
            params={
                "group_id": screen_name,
                "fields": "activity,create_date",
                "access_token": service_token,
                "v": "5.199",
            },
            timeout=timeout,
        )
        data = resp.json()
    except Exception as e:
        logger.debug(f"VK API ошибка: {e}")
        return None

    if "error" in data:
        logger.debug(f"VK API: {data['error'].get('error_msg', '')}")
        return None

    groups = data.get("response", {}).get("groups", [])
    if not groups:
        return None

    create_date = groups[0].get("create_date")
    if not create_date:
        return None

    try:
        return datetime.fromtimestamp(int(create_date))
    except (ValueError, TypeError):
        return None


def _extract_screen_name(url: str) -> Optional[str]:
    if not url:
        return None

    if url.startswith("https://vk.com/") or url.startswith("http://vk.com/"):
        path = urlparse(url).path.strip("/")
        return path if path else None

    if url.startswith("https://m.vk.com/") or url.startswith("http://m.vk.com/"):
        path = urlparse(url).path.strip("/")
        return path if path else None

    match = re.search(r"vk\.com/([a-zA-Z0-9_.-]+)", url)
    if match:
        return match.group(1)

    return None
