import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

from analyzers.domain_age import get_domain_age
from analyzers.vk_age import get_vk_group_age
from analyzers.website_checker import check_website
from models import Company
from sources.twogis_scraper import _is_valid_company_site

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def normalize_domain(url: str) -> str:
    value = (url or "").strip().lower()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.removeprefix("www.").split(":")[0]


def company_key(company: Company) -> str:
    if company.source_id:
        return f"2gis:{company.source_id}"
    phones = sorted(filter(None, (normalize_phone(phone) for phone in company.phones)))
    if phones:
        return f"phone:{phones[0]}"
    domain = normalize_domain(company.website or "")
    if domain:
        return f"domain:{domain}"
    return f"name:{company.name.strip().lower()}|{company.address.strip().lower()}"


def deduplicate_companies(companies: list[Company]) -> list[Company]:
    unique: dict[str, Company] = {}
    aliases: dict[str, str] = {}
    for company in companies:
        # Дедупликация по source_id — основной ключ
        keys = {company_key(company)}
        # Телефон и домен — только если у компании нет source_id (неизвестный источник)
        if not company.source_id:
            keys.update(f"phone:{phone}" for phone in map(normalize_phone, company.phones) if phone)
            domain = normalize_domain(company.website or "")
            if domain:
                keys.add(f"domain:{domain}")
        existing_key = next((aliases[key] for key in keys if key in aliases), None)
        if existing_key is None:
            primary = company_key(company)
            unique[primary] = company
            for key in keys:
                aliases[key] = primary
            continue
        target = unique[existing_key]
        target.phones = list(dict.fromkeys(target.phones + company.phones))
        target.rubrics = list(dict.fromkeys(target.rubrics + company.rubrics))
        target.raw_contacts.extend(item for item in company.raw_contacts if item not in target.raw_contacts)
        for attr in ("website", "vk_url", "telegram_url", "whatsapp_url", "source_id", "city"):
            if not getattr(target, attr) and getattr(company, attr):
                setattr(target, attr, getattr(company, attr))
        target.has_site = target.has_site or company.has_site
        target.rating = max(filter(lambda value: value is not None, (target.rating, company.rating)), default=None)
        target.reviews_count = max(target.reviews_count, company.reviews_count)
        target.branches_count = max(target.branches_count, company.branches_count)
        for key in keys:
            aliases[key] = existing_key
    return list(unique.values())


def filter_by_contacts(companies: list[Company], require_messenger: bool, require_phone: bool) -> list[Company]:
    result = [company for company in companies if not (
        (require_phone and not company.phones) or (require_messenger and not company.has_messenger)
    )]
    logger.info(f"Фильтр по контактам: {len(result)} из {len(companies)}")
    return result


def classify_business(company: Company):
    score = 0
    reasons = []
    name = company.name.lower()
    if company.branches_count >= 5:
        score += 4
        reasons.append(f"много филиалов: {company.branches_count}")
    elif company.branches_count > 1:
        score += 2
        reasons.append(f"несколько филиалов: {company.branches_count}")
    if any(word in name for word in ("сеть", "холдинг", "группа компаний", "федеральн", "корпорац")):
        score += 3
        reasons.append("признак сети в названии")
    if len(company.phones) >= 4:
        score += 2
        reasons.append("много телефонов")
    if company.reviews_count >= 500:
        score += 2
        reasons.append("очень много отзывов")
    if any(word in name for word in ("ип ", "мастер", "ателье", "студия", "мастерская")):
        score -= 1
        reasons.append("признак малого бизнеса в названии")
    company.business_size = "крупный" if score >= 4 else "средний" if score >= 2 else "малый"
    company.business_size_reasons = reasons or ["нет признаков крупной сети"]


def calculate_lead_score(company: Company):
    score = 0
    reasons = []
    if company.phones:
        score += 20
        reasons.append("есть телефон")
    if not company.has_site:
        score += 35
        reasons.append("нет сайта")
    elif not company.site_is_good:
        score += 20
        reasons.append("сайт требует улучшений")
    if company.rating is not None and company.rating >= 4.5:
        score += 15
        reasons.append(f"рейтинг {company.rating:.1f}")
    if company.reviews_count >= 10:
        score += 10
        reasons.append(f"отзывов: {company.reviews_count}")
    if company.has_messenger:
        score += 8
        reasons.append("есть мессенджер")
    if company.business_size == "малый":
        score += 12
        reasons.append("вероятно малый бизнес")
    elif company.business_size == "крупный":
        score -= 15
        reasons.append("вероятно крупный бизнес")
    if company.site_is_good:
        score -= 50
        reasons.append("качественный сайт")
    company.lead_score = max(0, min(100, score))
    company.lead_reasons = reasons


def analyze_companies(companies: list[Company], config, should_stop=None, on_progress=None) -> list[Company]:
    now = datetime.now().replace(tzinfo=None)
    companies = deduplicate_companies(companies)
    for company in companies:
        if company.website and not _is_valid_company_site(company.website):
            company.website = None
            company.has_site = False
        classify_business(company)

    if config.check_websites:
        site_companies = [company for company in companies if company.has_site and company.website]
        cache = {}
        domains = {}
        for company in site_companies:
            domains.setdefault(normalize_domain(company.website), company.website)
        executor = ThreadPoolExecutor(max_workers=max(1, min(config.audit_workers, 12)))
        futures = {executor.submit(check_website, url, config.http_timeout, True): domain for domain, url in domains.items()}
        stopped = False
        for index, future in enumerate(as_completed(futures), 1):
            if should_stop and should_stop():
                stopped = True
                for pending in futures:
                    pending.cancel()
                break
            domain = futures[future]
            try:
                cache[domain] = future.result()
            except Exception as exc:
                logger.warning(f"Ошибка аудита {domain}: {exc}")
            if on_progress:
                on_progress(index, f"Аудит сайта: {domain}")
        executor.shutdown(wait=not stopped, cancel_futures=stopped)
        for company in site_companies:
            site_result = cache.get(normalize_domain(company.website))
            if not site_result:
                continue
            company.site_issues = site_result.issues
            company.site_critical_issues = site_result.critical_issues
            company.site_is_good = site_result.is_good
            company.site_load_time = site_result.load_time
            company.site_status_code = site_result.status_code
            company.site_audit_score = site_result.audit_score
            company.site_audit_confidence = site_result.confidence

    result = []
    for index, company in enumerate(companies, 1):
        if should_stop and should_stop():
            break
        if config.only_young_companies:
            if company.website:
                company.domain_created_date = get_domain_age(company.website, timeout=config.http_timeout)
            if company.vk_url and config.vk_service_token:
                company.vk_group_created_date = get_vk_group_age(
                    company.vk_url, config.vk_service_token, timeout=config.http_timeout,
                )
            company.age_months = _calculate_age_months(company, now)
            if company.age_months is None:
                company.age_unknown = True
                company.is_young = True
            elif company.age_months > config.young_company_max_months:
                continue
            else:
                company.is_young = True
        calculate_lead_score(company)
        if config.skip_good_sites and company.site_is_good:
            continue
        if config.lead_mode == "no_site" and company.has_site:
            continue
        if config.lead_mode == "problem_site" and company.has_site and company.site_is_good:
            continue
        if config.lead_mode == "high_rating_no_site" and (company.has_site or (company.rating or 0) < 4.5):
            continue
        if config.lead_mode == "sales_ready" and (not company.phones or (company.has_site and company.site_is_good)):
            continue
        result.append(company)
        if on_progress:
            on_progress(index, company.name)
    return sorted(result, key=lambda company: company.lead_score, reverse=True)


def _calculate_age_months(company: Company, now: datetime) -> int | None:
    dates = []
    for date in (company.domain_created_date, company.vk_group_created_date, company.first_review_date):
        if date:
            dates.append(date.replace(tzinfo=None) if date.tzinfo is not None else date)
    if not dates:
        return None
    return int((now - min(dates)).days / 30.44)
