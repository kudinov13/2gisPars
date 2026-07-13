import logging
from sources.twogis_scraper import search_companies_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def on_progress(count, name):
    print(f"  [{count}] {name}")

print("Тест скрапера: Новосибирск / стоматология (макс 5)")
companies = search_companies_sync(
    city="Новосибирск",
    rubric="стоматология",
    max_results=5,
    timeout=30,
    headless=True,
    on_progress=on_progress,
)

print(f"\nИтого: {len(companies)} компаний")
for c in companies[:10]:
    print(f"  - {c.name}")
    print(f"    тел: {c.primary_phone}, сайт: {c.website or '—'}")
    print(f"    VK: {c.vk_url or '—'}, TG: {c.telegram_url or '—'}, WA: {c.whatsapp_url or '—'}")
    print()
