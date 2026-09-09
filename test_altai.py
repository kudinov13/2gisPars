import logging
from sources.twogis_scraper import search_companies_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

companies = search_companies_sync(
    city="",
    region="Республика Алтай",
    rubric="тур базы",
    max_results=5,
    timeout=30,
    headless=True,
    on_progress=lambda count, name: print(f"[{count}] {name}"),
)

print(f"\nИтого: {len(companies)} компаний")
for c in companies:
    print(f"- {c.name} | {c.address} | {c.primary_phone}")
