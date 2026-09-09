import logging
import time
from sources.twogis_scraper import search_companies_sync
from config import Config
from filters import filter_by_contacts, analyze_companies

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

start = time.time()
print("Тест: Новосибирск / стоматология (макс 150) с фильтрами по умолчанию")
companies = search_companies_sync(
    city="Новосибирск",
    rubric="стоматология",
    max_results=150,
    timeout=30,
    headless=True,
)
print(f"Собрано: {len(companies)} (до фильтров) за {int(time.time()-start)} сек")

config = Config(
    vk_service_token="",
    city="Новосибирск",
    rubric="стоматология",
    require_messenger=True,
    require_phone=True,
    only_young_companies=False,
    young_company_max_months=24,
    check_websites=False,
    skip_good_sites=False,
    max_results=150,
)

filtered = filter_by_contacts(companies, config.require_messenger, config.require_phone)
print(f"После фильтра контактов: {len(filtered)}")

analyzed = analyze_companies(filtered, config)
print(f"После анализа: {len(analyzed)}")
for c in analyzed[:10]:
    print(f"  - {c.name}: тел={c.primary_phone}, мессенджеры={c.has_messenger}, сайт={c.website or '-'}")
