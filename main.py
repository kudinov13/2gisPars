import logging
import sys

from config import Config, parse_args
from locations import get_region_cities
from sources.twogis_scraper import search_companies_sync
from filters import analyze_companies, deduplicate_companies, filter_by_contacts
from niches import expand_rubrics
from report import generate_excel_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    config = parse_args()

    if config.only_young_companies and not config.vk_service_token:
        print("[!] Внимание: фильтр молодых компаний включён, но VK токен не указан.")
        print("   Возраст будет определяться только по домену (если есть сайт).")
        print("   Для точности получите сервисный токен: https://vk.com/dev")
        print()

    print(f"Поиск: город={config.city}, рубрика={config.rubric}")
    print(f"   Фильтры: мессенджер={config.require_messenger}, телефон={config.require_phone}")
    print(f"   Молодые компании: {'да (до ' + str(config.young_company_max_months) + ' мес)' if config.only_young_companies else 'нет'}")
    print(f"   Проверка сайтов: {'да' if config.check_websites else 'нет'}")
    print()

    def on_progress(count, name):
        print(f"  [{count}] {name}", end="\r")

    region_cities = get_region_cities(config.region) if config.region else []
    if region_cities:
        locations = [(city, "") for city in region_cities]
    elif config.region:
        locations = [("", config.region)]
    else:
        locations = [(city, "") for city in config.cities]
    rubrics = expand_rubrics(config.rubrics, config.use_niche_synonyms)
    combinations = [(city, region, rubric) for rubric in rubrics for city, region in locations]
    if region_cities:
        candidate_limit = config.max_results
        per_query = max(10, min(50, config.max_results // max(1, len(locations))))
    else:
        candidate_limit = config.max_results
        per_query = max(10, min(config.max_results, 50))
    companies = []
    for city, region, rubric in combinations:
        found = search_companies_sync(
            city=city,
            rubric=rubric,
            max_results=per_query,
            timeout=config.http_timeout,
            headless=True,
            on_progress=on_progress,
            region=region,
        )
        for company in found:
            company.city = region or city
        companies = deduplicate_companies(companies + found)[:candidate_limit]
        if len(companies) >= candidate_limit:
            break
    print()

    if not companies:
        print("[X] Компании не найдены")
        sys.exit(0)

    logger.info(f"Найдено компаний: {len(companies)}")

    companies = filter_by_contacts(companies, config.require_messenger, config.require_phone)
    if not companies:
        print("[X] После фильтрации по контактам не осталось компаний")
        sys.exit(0)

    companies = analyze_companies(companies, config)[:config.max_results]
    if not companies:
        print("[X] После анализа и фильтрации не осталось компаний")
        sys.exit(0)

    generate_excel_report(companies, config.output_file)


if __name__ == "__main__":
    main()
