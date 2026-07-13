import logging
from datetime import datetime

from models import Company
from analyzers.website_checker import check_website
from analyzers.domain_age import get_domain_age
from analyzers.vk_age import get_vk_group_age

logger = logging.getLogger(__name__)


def filter_by_contacts(companies: list[Company], require_messenger: bool, require_phone: bool) -> list[Company]:
    result = []
    for c in companies:
        if require_phone and not c.phones:
            continue
        if require_messenger and not c.has_messenger:
            continue
        result.append(c)
    logger.info(f"Фильтр по контактам: {len(result)} из {len(companies)}")
    return result


def analyze_companies(companies: list[Company], config) -> list[Company]:
    now = datetime.now()
    result = []

    for i, company in enumerate(companies, 1):
        logger.info(f"[{i}/{len(companies)}] Анализ: {company.name}")

        if config.check_websites and company.has_site and company.website:
            site_result = check_website(company.website, timeout=config.http_timeout)
            company.site_issues = site_result.issues
            company.site_critical_issues = site_result.critical_issues
            company.site_is_good = site_result.is_good

            if config.skip_good_sites and site_result.is_good:
                logger.info(f"  → Сайт хороший, пропускаем компанию")
                continue

        if company.website:
            domain_date = get_domain_age(company.website, timeout=config.http_timeout)
            company.domain_created_date = domain_date
            if domain_date:
                logger.info(f"  → Домен зарегистрирован: {domain_date.strftime('%Y-%m-%d')}")
            else:
                logger.debug(f"  → Не удалось определить возраст домена")

        if company.vk_url and config.vk_service_token:
            vk_date = get_vk_group_age(company.vk_url, config.vk_service_token, timeout=config.http_timeout)
            company.vk_group_created_date = vk_date
            if vk_date:
                logger.info(f"  → VK-группа создана: {vk_date.strftime('%Y-%m-%d')}")

        if company.first_review_date:
            logger.info(f"  → Первый отзыв на 2GIS: {company.first_review_date.strftime('%Y-%m-%d')}")

        company.age_months = _calculate_age_months(company, now)

        if config.only_young_companies:
            if company.age_months is None:
                # Возраст неизвестен — помечаем как потенциально молодую
                company.age_unknown = True
                company.is_young = True
                logger.info(f"  → Возраст неизвестен, помечена как потенциально молодая")
            elif company.age_months > config.young_company_max_months:
                logger.info(f"  → Возраст {company.age_months}мес, пропускаем (фильтр молодых)")
                continue
            else:
                company.is_young = True
                logger.info(f"  → Возраст {company.age_months}мес, молодая компания")

        result.append(company)

    logger.info(f"После анализа и фильтрации: {len(result)} компаний")
    return result


def _calculate_age_months(company: Company, now: datetime) -> int | None:
    """Вычисляет возраст компании в месяцах.
    Использует min(даты) — самая ранняя дата = минимальный возраст компании.
    Источники дат (по надёжности):
      1. Дата регистрации домена (WHOIS/RDAP)
      2. Дата создания VK-группы (VK API)
      3. Дата первого отзыва на 2GIS (косвенный признак)
    Если ни один источник не дал дату — возвращает None (возраст неизвестен)."""
    dates = []
    if company.domain_created_date:
        dates.append(company.domain_created_date)
    if company.vk_group_created_date:
        dates.append(company.vk_group_created_date)
    if company.first_review_date:
        dates.append(company.first_review_date)

    if not dates:
        return None

    # min = самая ранняя дата = компания существует минимум с этого момента
    earliest = min(dates)
    delta = now - earliest
    return int(delta.days / 30.44)
