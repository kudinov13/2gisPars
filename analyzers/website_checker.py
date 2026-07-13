import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin

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


def check_website(url: str, timeout: int = 10) -> SiteCheckResult:
    result = SiteCheckResult()

    if not url:
        return result

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        start = time.time()
        resp = requests.get(url, timeout=timeout, allow_redirects=True, verify=True)
        result.load_time = round(time.time() - start, 2)
        result.status_code = resp.status_code
    except requests.exceptions.SSLError:
        result.critical_issues.append("SSL-сертификат недействителен или отсутствует")
        try:
            start = time.time()
            resp = requests.get(url.replace("https://", "http://"), timeout=timeout, allow_redirects=True)
            result.load_time = round(time.time() - start, 2)
            result.status_code = resp.status_code
        except Exception:
            result.critical_issues.append("Сайт недоступен")
            return result
    except requests.exceptions.ConnectionError:
        result.critical_issues.append("Сайт недоступен (ошибка соединения)")
        return result
    except requests.exceptions.Timeout:
        result.critical_issues.append("Превышено время ожидания загрузки сайта")
        return result
    except Exception as e:
        result.critical_issues.append(f"Ошибка загрузки: {e}")
        return result

    if resp.status_code >= 400:
        result.critical_issues.append(f"HTTP ошибка: {resp.status_code}")
        return result

    final_url = resp.url
    if final_url.startswith("http://") and not final_url.startswith("http://localhost"):
        result.issues.append("Нет HTTPS (сайт работает только по HTTP)")

    if result.load_time > 5.0:
        result.critical_issues.append(f"Очень медленная загрузка ({result.load_time}с)")
    elif result.load_time > 3.0:
        result.issues.append(f"Медленная загрузка ({result.load_time}с)")

    soup = BeautifulSoup(resp.text, "lxml")

    _check_meta_tags(soup, result)
    _check_viewport(soup, result)
    _check_title(soup, result)
    _check_robots_sitemap(url, result, timeout)
    _check_analytics(soup, result)
    _check_broken_links(url, soup, result, timeout)

    if not result.critical_issues and len(result.issues) <= 3:
        result.is_good = True

    return result


def _check_title(soup: BeautifulSoup, result: SiteCheckResult):
    title = soup.find("title")
    if not title or not title.text.strip():
        result.issues.append("Отсутствует <title> тег")
    elif len(title.text.strip()) > 70:
        result.issues.append("Слишком длинный <title> (>70 символов)")


def _check_meta_tags(soup: BeautifulSoup, result: SiteCheckResult):
    description = soup.find("meta", attrs={"name": "description"})
    if not description or not description.get("content", "").strip():
        result.issues.append("Отсутствует meta description")

    og_tags = soup.find_all("meta", attrs={"property": lambda x: x and x.startswith("og:")})
    if not og_tags:
        result.issues.append("Отсутствуют Open Graph теги (og:title, og:image и т.д.)")


def _check_viewport(soup: BeautifulSoup, result: SiteCheckResult):
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        result.critical_issues.append("Отсутствует meta viewport (сайт не адаптивный)")


def _check_robots_sitemap(base_url: str, result: SiteCheckResult, timeout: int):
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        resp = requests.get(f"{base}/robots.txt", timeout=timeout)
        if resp.status_code >= 400:
            result.issues.append("Отсутствует robots.txt")
    except Exception:
        result.issues.append("Отсутствует robots.txt")

    try:
        resp = requests.get(f"{base}/sitemap.xml", timeout=timeout)
        if resp.status_code >= 400:
            result.issues.append("Отсутствует sitemap.xml")
    except Exception:
        result.issues.append("Отсутствует sitemap.xml")


def _check_analytics(soup: BeautifulSoup, result: SiteCheckResult):
    text = str(soup)
    has_ga = "google-analytics" in text or "gtag" in text or "googletagmanager" in text
    has_ym = "mc.yandex" in text or "ym(" in text or "yandex_metrika" in text

    if not has_ga and not has_ym:
        result.issues.append("Не установлена веб-аналитика (Google Analytics / Яндекс.Метрика)")


def _check_broken_links(base_url: str, soup: BeautifulSoup, result: SiteCheckResult, timeout: int):
    links = soup.find_all("a", href=True)
    internal_links = set()
    parsed_base = urlparse(base_url)

    for link in links:
        href = link["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc == parsed_base.netloc:
            internal_links.add(full_url)

    checked = 0
    broken = 0
    for link_url in list(internal_links)[:15]:
        try:
            resp = requests.head(link_url, timeout=timeout, allow_redirects=True)
            if resp.status_code >= 400:
                broken += 1
            checked += 1
        except Exception:
            broken += 1
            checked += 1

    if checked > 0 and broken > 0:
        result.issues.append(f"Битые ссылки: {broken} из {checked} проверенных")
        if broken > 3:
            result.critical_issues.append(f"Много битых ссылок: {broken} из {checked}")
