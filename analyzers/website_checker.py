import ipaddress
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class SiteCheckResult:
    issues: list[str] = field(default_factory=list)
    critical_issues: list[str] = field(default_factory=list)
    is_good: bool = False
    load_time: float = 0.0
    status_code: int = 0
    audit_score: int = 0
    confidence: str = "низкая"


def check_website(url: str, timeout: int = 10, deep: bool = True) -> SiteCheckResult:
    result = SiteCheckResult()
    if not url:
        return result
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not _is_public_url(url):
        result.critical_issues.append("Некорректный или небезопасный адрес сайта")
        return _finish(result)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    try:
        start = time.perf_counter()
        resp = _safe_request(session, "GET", url, timeout)
        result.load_time = round(time.perf_counter() - start, 2)
        result.status_code = resp.status_code
    except requests.exceptions.SSLError:
        result.critical_issues.append("SSL-сертификат недействителен")
        try:
            start = time.perf_counter()
            resp = _safe_request(session, "GET", url.replace("https://", "http://", 1), timeout)
            result.load_time = round(time.perf_counter() - start, 2)
            result.status_code = resp.status_code
        except requests.RequestException:
            result.critical_issues.append("Сайт недоступен")
            return _finish(result)
    except requests.exceptions.Timeout:
        result.critical_issues.append("Превышено время ожидания загрузки сайта")
        return _finish(result)
    except requests.RequestException as exc:
        result.critical_issues.append(f"Сайт недоступен: {exc.__class__.__name__}")
        return _finish(result)

    if resp.status_code >= 400:
        result.critical_issues.append(f"HTTP ошибка: {resp.status_code}")
        return _finish(result)
    if resp.url.startswith("http://"):
        result.critical_issues.append("Нет HTTPS")
    if result.load_time > 7:
        result.critical_issues.append(f"Очень медленный ответ сервера ({result.load_time}с)")
    elif result.load_time > 4:
        result.issues.append(f"Медленный ответ сервера ({result.load_time}с)")

    content_type = resp.headers.get("Content-Type", "").lower()
    if "html" not in content_type and resp.text:
        result.critical_issues.append("Главная страница не возвращает HTML")
        return _finish(result)

    soup = BeautifulSoup(resp.text, "lxml")
    _check_page_quality(soup, resp.text, result)
    if deep:
        _check_indexing(session, resp.url, result, timeout)
        _check_links(session, resp.url, soup, result, timeout)
    result.confidence = "высокая" if deep else "средняя"
    return _finish(result)


def _finish(result: SiteCheckResult) -> SiteCheckResult:
    score = 100 - len(result.critical_issues) * 30 - len(result.issues) * 5
    result.audit_score = max(0, min(100, score))
    result.is_good = not result.critical_issues and result.audit_score >= 90
    return result


def _is_public_url(url: str) -> bool:
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    result = []
    failed = []

    def resolve():
        try:
            result.extend(socket.getaddrinfo(hostname, None))
        except OSError:
            failed.append(True)

    resolver = threading.Thread(target=resolve, daemon=True)
    resolver.start()
    resolver.join(3)
    if resolver.is_alive() or failed or not result:
        return False
    try:
        return all(ipaddress.ip_address(item[4][0]).is_global for item in result)
    except ValueError:
        return False


def _safe_request(session: requests.Session, method: str, url: str, timeout: int, **kwargs):
    current = url
    for _ in range(6):
        if not _is_public_url(current):
            raise requests.RequestException("blocked address")
        response = session.request(method, current, timeout=timeout, allow_redirects=False, **kwargs)
        if response.status_code not in (301, 302, 303, 307, 308):
            response.url = current
            return response
        location = response.headers.get("Location")
        if not location:
            return response
        current = urljoin(current, location)
    raise requests.TooManyRedirects("too many redirects")


def _check_page_quality(soup: BeautifulSoup, html: str, result: SiteCheckResult):
    title = soup.find("title")
    if not title or not title.get_text(strip=True):
        result.issues.append("Отсутствует title")
    elif len(title.get_text(strip=True)) > 75:
        result.issues.append("Слишком длинный title")
    description = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
    if not description or not description.get("content", "").strip():
        result.issues.append("Отсутствует meta description")
    if not soup.find("meta", attrs={"name": lambda value: value and value.lower() == "viewport"}):
        result.critical_issues.append("Нет признака мобильной адаптации")
    visible_text = soup.get_text(" ", strip=True)
    if len(visible_text) < 250:
        result.critical_issues.append("На главной странице почти нет содержимого")
    has_phone = bool(soup.select('a[href^="tel:"]'))
    has_form = soup.find("form") is not None
    has_messenger = any(marker in html.lower() for marker in ("wa.me/", "t.me/", "vk.com/"))
    if not (has_phone or has_form or has_messenger):
        result.issues.append("Не найден заметный способ связи")
    if not soup.find("h1"):
        result.issues.append("Отсутствует заголовок H1")


def _check_indexing(session: requests.Session, base_url: str, result: SiteCheckResult, timeout: int):
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    try:
        robots = _safe_request(session, "GET", f"{base}/robots.txt", timeout)
        if robots.status_code >= 400:
            result.issues.append("Отсутствует robots.txt")
    except requests.RequestException:
        result.issues.append("Не удалось проверить robots.txt")
    try:
        sitemap = _safe_request(session, "GET", f"{base}/sitemap.xml", timeout)
        if sitemap.status_code >= 400:
            result.issues.append("Отсутствует sitemap.xml")
    except requests.RequestException:
        result.issues.append("Не удалось проверить sitemap.xml")


def _check_links(session: requests.Session, base_url: str, soup: BeautifulSoup, result: SiteCheckResult, timeout: int):
    base_host = urlparse(base_url).netloc
    links = []
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full_url = urljoin(base_url, href)
        if urlparse(full_url).netloc == base_host and full_url not in links:
            links.append(full_url)
    checked = broken = 0
    for link_url in links[:8]:
        try:
            response = _safe_request(session, "HEAD", link_url, min(timeout, 5))
            if response.status_code in (403, 405) or response.status_code >= 500:
                response = _safe_request(session, "GET", link_url, min(timeout, 5), stream=True)
            if response.status_code >= 400:
                broken += 1
        except requests.RequestException:
            broken += 1
        checked += 1
    if broken:
        result.issues.append(f"Битые внутренние ссылки: {broken} из {checked}")
    if broken >= 3:
        result.critical_issues.append("Много битых внутренних ссылок")
