import logging
import time
from typing import Optional

import requests

from models import Company

logger = logging.getLogger(__name__)


class TwoGisClient:
    BASE_URL = "https://catalog.api.2gis.ru/3.0/items"
    BRANCH_URL = "https://catalog.api.2gis.ru/3.0/branches"
    GEO_URL = "https://catalog.api.2gis.ru/3.0/geo"

    def __init__(self, api_key: str, timeout: int = 10):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ParserCompany/1.0"})

    def _get(self, url: str, params: dict) -> dict:
        params["key"] = self.api_key
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                logger.warning(f"2GIS API попытка {attempt+1}: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return {}

    def search_city(self, city_name: str) -> Optional[str]:
        params = {
            "q": city_name,
            "type": "city",
            "fields": "items.region_id",
            "limit": 1,
        }
        data = self._get(self.GEO_URL, params)
        items = data.get("result", {}).get("items", [])
        if items:
            return items[0].get("id")
        logger.error(f"Город '{city_name}' не найден в 2GIS")
        return None

    def search_companies(self, city_id: str, rubric: str, limit: int = 500) -> list[Company]:
        companies = []
        page = 1
        per_page = 50
        collected = 0

        while collected < limit:
            params = {
                "q": rubric,
                "region_id": city_id,
                "type": "branch",
                "fields": "items.contact_groups,items.rubrics,items.point,items.address_name",
                "page": page,
                "page_size": min(per_page, limit - collected),
                "sort": "rating",
            }
            data = self._get(self.BASE_URL, params)
            items = data.get("result", {}).get("items", [])

            if not items:
                break

            for item in items:
                company = self._parse_item(item)
                if company:
                    companies.append(company)
                    collected += 1
                    if collected >= limit:
                        break

            total = data.get("result", {}).get("total", 0)
            if collected >= total or collected >= limit:
                break

            page += 1
            time.sleep(0.3)

        logger.info(f"2GIS: найдено {len(companies)} компаний по рубрике '{rubric}'")
        return companies

    def _parse_item(self, item: dict) -> Optional[Company]:
        name = item.get("name", "")
        if not name:
            return None

        company = Company(name=name)

        company.address = item.get("address_name", "")

        point = item.get("point", {})
        if point:
            company.lat = point.get("lat")
            company.lon = point.get("lon")

        rubrics = item.get("rubrics", [])
        company.rubrics = [r.get("name", "") for r in rubrics if isinstance(r, dict)]

        contact_groups = item.get("contact_groups", [])
        for group in contact_groups:
            contacts = group.get("contacts", [])
            for contact in contacts:
                ctype = contact.get("type", "")
                value = contact.get("value", "")
                if not value:
                    continue

                company.raw_contacts.append({"type": ctype, "value": value})

                if ctype == "phone":
                    company.phones.append(value)
                elif ctype == "website":
                    company.website = value
                    company.has_site = True
                elif ctype == "vkontakte":
                    company.vk_url = value
                elif ctype == "telegram":
                    company.telegram_url = value
                elif ctype == "whatsapp":
                    company.whatsapp_url = value
                elif ctype in ("social", "social_profile"):
                    val_lower = value.lower()
                    if "vk.com" in val_lower or "vkontakte.ru" in val_lower:
                        company.vk_url = value
                    elif "t.me" in val_lower or "telegram" in val_lower:
                        company.telegram_url = value

        return company
