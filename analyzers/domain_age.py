import logging
import re
import socket
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def get_domain_age(url: str, timeout: int = 10) -> Optional[datetime]:
    if not url:
        return None

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    domain = domain.split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]

    if not domain or "." not in domain:
        return None

    # 1. Пробуем RDAP
    result = _get_domain_age_rdap(domain, timeout)
    if result:
        return result

    # 2. Fallback: WHOIS для .ru/.su/.рф и других
    result = _get_domain_age_whois(domain, timeout)
    if result:
        return result

    logger.debug(f"Не удалось определить возраст домена {domain}")
    return None


def _get_domain_age_rdap(domain: str, timeout: int) -> Optional[datetime]:
    """Получает дату регистрации через RDAP."""
    try:
        resp = requests.get(
            f"https://rdap.org/domain/{domain}",
            timeout=timeout,
            headers={"Accept": "application/rdap+json"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"RDAP ошибка для {domain}: {e}")
        return None

    events = data.get("events", [])
    for event in events:
        if event.get("eventAction") == "registration":
            date_str = event.get("eventDate", "")
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                try:
                    return datetime.strptime(date_str[:10], "%Y-%m-%d")
                except ValueError:
                    pass

    return None


def _get_domain_age_whois(domain: str, timeout: int) -> Optional[datetime]:
    """Получает дату регистрации через WHOIS (port 43).
    Надёжно для .ru/.su/.рф доменов - использует сервер TLD."""
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""

    # Выбор WHOIS-сервера по TLD
    whois_servers = {
        "ru": "whois.tcinet.ru",
        "su": "whois.tcinet.ru",
        "xn--p1ai": "whois.tcinet.ru",  # .рф
        "com": "whois.verisign-grs.com",
        "net": "whois.verisign-grs.com",
        "org": "whois.publicinterestregistry.org",
        "info": "whois.afilias.net",
        "biz": "whois.nic.biz",
        "io": "whois.nic.io",
        "me": "whois.nic.me",
        "pro": "whois.afilias.net",
    }

    server = whois_servers.get(tld)
    if not server:
        return None

    try:
        with socket.create_connection((server, 43), timeout=timeout) as sock:
            sock.sendall((domain + "\r\n").encode("utf-8"))
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            text = response.decode("utf-8", errors="ignore")
    except Exception as e:
        logger.debug(f"WHOIS ошибка для {domain}: {e}")
        return None

    # Парсим дату регистрации из ответа WHOIS
    # Форматы отличаются между серверами
    date_patterns = [
        # .ru/.su/.рф: created: 2010-01-01T00:00:00Z
        (r"created:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", "%Y-%m-%dT%H:%M:%SZ"),
        (r"created:\s*(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        # .com/.net: Creation Date: 2010-01-01T00:00:00Z
        (r"[Cc]reation [Dd]ate:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", "%Y-%m-%dT%H:%M:%SZ"),
        (r"[Cc]reation [Dd]ate:\s*(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"[Cc]reation [Dd]ate:\s*(\d{2}-\w{3}-\d{4})", "%d-%b-%Y"),
        # Общие
        (r"[Rr]egistered:\s*(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"[Rr]egistration [Dd]ate:\s*(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
    ]

    for pattern, date_format in date_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(1), date_format)
            except ValueError:
                continue

    logger.debug(f"WHOIS: дата регистрации не найдена для {domain}")
    return None
