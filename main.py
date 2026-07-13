import logging
import sys

from config import Config, parse_args
from sources.twogis_scraper import search_companies_sync
from filters import filter_by_contacts, analyze_companies
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
        print("⚠️  Внимание: фильтр молодых компаний включён, но VK токен не указан.")
        print("   Возраст будет определяться только по домену (если есть сайт).")
        print("   Для точности получите сервисный токен: https://vk.com/dev")
        print()

    print(f"🔍 Поиск: город={config.city}, рубрика={config.rubric}")
    print(f"   Фильтры: мессенджер={config.require_messenger}, телефон={config.require_phone}")
    print(f"   Молодые компании: {'да (до ' + str(config.young_company_max_months) + ' мес)' if config.only_young_companies else 'нет'}")
    print(f"   Проверка сайтов: {'да' if config.check_websites else 'нет'}")
    print()

    def on_progress(count, name):
        print(f"  [{count}] {name}", end="\r")

    companies = search_companies_sync(
        city=config.city,
        rubric=config.rubric,
        max_results=config.max_results,
        timeout=config.http_timeout,
        headless=True,
        on_progress=on_progress,
    )
    print()

    if not companies:
        print("❌ Компании не найдены")
        sys.exit(0)

    logger.info(f"Найдено компаний: {len(companies)}")

    companies = filter_by_contacts(companies, config.require_messenger, config.require_phone)
    if not companies:
        print("❌ После фильтрации по контактам не осталось компаний")
        sys.exit(0)

    companies = analyze_companies(companies, config)
    if not companies:
        print("❌ После анализа и фильтрации не осталось компаний")
        sys.exit(0)

    generate_excel_report(companies, config.output_file)


if __name__ == "__main__":
    main()
