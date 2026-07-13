import asyncio
import json
import logging
import re
import time
from typing import Callable, Optional
from urllib.parse import quote, urlencode

from models import Company

logger = logging.getLogger(__name__)

# Словарь регион (республика/область/край) → slug 2GIS (столица/главный город региона)
# 2GIS использует slug столицы региона, но поиск охватывает весь регион
REGION_SLUG = {
    # Республики РФ
    "республика алтай": "gorno-altaysk",
    "алтай": "gorno-altaysk",
    "горный алтай": "gorno-altaysk",
    "республика адыгея": "maykop",
    "адыгея": "maykop",
    "республика башкортостан": "ufa",
    "башкортостан": "ufa",
    "республика бурятия": "ulan-ude",
    "бурятия": "ulan-ude",
    "республика дагестан": "makhachkala",
    "дагестан": "makhachkala",
    "республика ингушетия": "nazran",
    "ингушетия": "nazran",
    "кабардино-балкарская республика": "nalchik",
    "кабардино-балкария": "nalchik",
    "республика калмыкия": "elista",
    "калмыкия": "elista",
    "карачаево-черкесская республика": "cherkessk",
    "карачаево-черкесия": "cherkessk",
    "республика карелия": "petrozavodsk",
    "карелия": "petrozavodsk",
    "республика коми": "syktyvkar",
    "коми": "syktyvkar",
    "республика крым": "simferopol",
    "крым": "simferopol",
    "республика марий эл": "yoshkar-ola",
    "марий эл": "yoshkar-ola",
    "республика мордовия": "saransk",
    "мордовия": "saransk",
    "республика саха": "yakutsk",
    "саха": "yakutsk",
    "якутия": "yakutsk",
    "республика северная осетия": "vladikavkaz",
    "северная осетия": "vladikavkaz",
    "алания": "vladikavkaz",
    "республика татарстан": "kazan",
    "татарстан": "kazan",
    "республика тыва": "kyzyl",
    "тыва": "kyzyl",
    "республика удмуртия": "izhevsk",
    "удмуртия": "izhevsk",
    "республика хакасия": "abakan",
    "хакасия": "abakan",
    "чеченская республика": "grozny",
    "чечня": "grozny",
    "чувашская республика": "cheboksary",
    "чувашия": "cheboksary",
    # Края
    "алтайский край": "barnaul",
    "забайкальский край": "chita",
    "камчатский край": "petropavlovsk-kamchatsky",
    "краснодарский край": "krasnodar",
    "красноярский край": "krasnoyarsk",
    "пермский край": "perm",
    "приморский край": "vladivostok",
    "ставропольский край": "stavropol",
    "хабаровский край": "khabarovsk",
    # Области
    "амурская область": "blagoveshchensk",
    "архангельская область": "arkhangelsk",
    "астраханская область": "astrakhan",
    "белгородская область": "belgorod",
    "брянская область": "bryansk",
    "владимирская область": "vladimir",
    "волгоградская область": "volgograd",
    "вологодская область": "vologda",
    "воронежская область": "voronezh",
    "ивановская область": "ivanovo",
    "иркутская область": "irkutsk",
    "калининградская область": "kaliningrad",
    "калужская область": "kaluga",
    "кемеровская область": "kemerovo",
    "кировская область": "kirov",
    "костромская область": "kostroma",
    "курганская область": "kurgan",
    "курская область": "kursk",
    "липецкая область": "lipetsk",
    "магаданская область": "magadan",
    "московская область": "moscow",
    "мурманская область": "murmansk",
    "нижегородская область": "nizhniy-novgorod",
    "новгородская область": "velikiy-novgorod",
    "новосибирская область": "novosibirsk",
    "омская область": "omsk",
    "оренбургская область": "orenburg",
    "орловская область": "orel",
    "пензенская область": "penza",
    "псковская область": "pskov",
    "ростовская область": "rostov-na-donu",
    "рязанская область": "ryazan",
    "самарская область": "samara",
    "саратовская область": "saratov",
    "сахалинская область": "yuzhno-sakhalinsk",
    "свердловская область": "ekaterinburg",
    "смоленская область": "smolensk",
    "тамбовская область": "tambov",
    "тверская область": "tver",
    "томская область": "tomsk",
    "тульская область": "tula",
    "тюменская область": "tyumen",
    "ульяновская область": "ulyanovsk",
    "челябинская область": "chelyabinsk",
    "ярославская область": "yaroslavl",
    # Автономные округа / области
    "ханты-мансийский автономный округ": "khanty-mansiysk",
    "ямало-ненецкий автономный округ": "salekhard",
    "еврейская автономная область": "birobidzhan",
    "ненецкий автономный округ": "naryan-mar",
    "чукотский автономный округ": "anadyr",
}

# Ключевые слова для фильтрации адреса по региону
# Используется для проверки: действительно ли компания находится в нужном регионе
REGION_ADDRESS_KEYWORDS = {
    "республика алтай": ["республика алтай", "респ. алтай", "горно-алтайск", "майминский", "чемальский",
                         "онгудайский", "усть-коксинский", "усть-канский", "шебалинский",
                         "кош-агачский", "улаганский", "турочакский", "чойский", "r. altai"],
    "горный алтай": ["республика алтай", "респ. алтай", "горно-алтайск"],
    "алтай": ["республика алтай", "респ. алтай", "горно-алтайск"],
    "алтайский край": ["алтайский край", "барнаул", "бийск", "рубцовск", "алт. край"],
    "республика адыгея": ["республика адыгея", "адыгея", "майкоп"],
    "адыгея": ["республика адыгея", "адыгея", "майкоп"],
    "краснодарский край": ["краснодарский край", "краснодар", "сочи", "анапа", "новороссийск", "кубань"],
    "ставропольский край": ["ставропольский край", "ставрополь", "пятигорск", "кисловодск"],
    "республика дагестан": ["республика дагестан", "дагестан", "махачкала"],
    "дагестан": ["республика дагестан", "дагестан", "махачкала"],
    "чеченская республика": ["чеченская республика", "чечня", "грозный"],
    "чечня": ["чеченская республика", "чечня", "грозный"],
    "республика крым": ["республика крым", "крым", "симферополь", "севастополь"],
    "крым": ["республика крым", "крым", "симферополь", "севастополь"],
    "новосибирская область": ["новосибирская область", "новосибирск", "нсо"],
    "иркутская область": ["иркутская область", "иркутск"],
    "красноярский край": ["красноярский край", "красноярск"],
    "кемеровская область": ["кемеровская область", "кемерово", "кузбасс", "новокузнецк"],
    "томская область": ["томская область", "томск"],
    "омская область": ["омская область", "омск"],
    "тюменская область": ["тюменская область", "тюмень"],
    "свердловская область": ["свердловская область", "екатеринбург"],
    "челябинская область": ["челябинская область", "челябинск"],
    "ростовская область": ["ростовская область", "ростов-на-дону", "ростов", "дон"],
}


def _get_region_slug(region: str) -> str:
    """Возвращает 2GIS-slug для региона. Если не найден — транслитерирует."""
    key = region.lower().strip()
    # Точное совпадение
    if key in REGION_SLUG:
        return REGION_SLUG[key]
    # Частичное совпадение
    for reg_key, slug in REGION_SLUG.items():
        if reg_key in key or key in reg_key:
            return slug
    # Fallback: автотранслитерация
    return _auto_translit(key)


def _build_address_keywords(region: str) -> list[str]:
    """Возвращает список ключевых слов адреса для проверки принадлежности к региону."""
    key = region.lower().strip()
    # Точное совпадение
    if key in REGION_ADDRESS_KEYWORDS:
        return REGION_ADDRESS_KEYWORDS[key]
    # Частичное совпадение
    for reg_key, kws in REGION_ADDRESS_KEYWORDS.items():
        if reg_key in key or key in reg_key:
            return kws
    # Fallback: используем само название региона как ключевое слово
    return [key]


def _address_matches_region(address: str, region_keywords: list[str]) -> bool:
    """Проверяет, содержит ли адрес компании хотя бы одно ключевое слово региона."""
    if not address or not region_keywords:
        return True  # Если нет адреса или ключевых слов — не отсеиваем
    address_lower = address.lower()
    return any(kw.lower() in address_lower for kw in region_keywords)


# Транслитерация русских городов в URL-формат 2GIS
CITY_TRANSLIT = {
    "москва": "moscow", "санкт-петербург": "spb", "спб": "spb",
    "новосибирск": "novosibirsk", "екатеринбург": "ekaterinburg",
    "казань": "kazan", "нижний новгород": "nizhniy-novgorod",
    "челябинск": "chelyabinsk", "самара": "samara", "омск": "omsk",
    "ростов-на-дону": "rostov-na-donu", "уфа": "ufa",
    "красноярск": "krasnoyarsk", "воронеж": "voronezh",
    "волгоград": "volgograd", "краснодар": "krasnodar",
    "пермь": "perm", "саратов": "saratov", "тюмень": "tyumen",
    "тольятти": "tolyatti", "ижевск": "izhevsk", "барнаул": "barnaul",
    "ульяновск": "ulyanovsk", "иркутск": "irkutsk",
    "хабаровск": "khabarovsk", "ярославль": "yaroslavl",
    "владивосток": "vladivostok", "махачкала": "makhachkala",
    "оренбург": "orenburg", "томск": "tomsk", "кемерово": "kemerovo",
    "новокузнецк": "novokuznetsk", "рязань": "ryazan",
    "астана": "astana", "пенза": "penza", "липецк": "lipetsk",
    "тула": "tula", "киев": "kyiv", "белгород": "belgorod",
    "ставрополь": "stavropol", "курск": "kursk", "брянск": "bryansk",
    "владимир": "vladimir", "сочи": "sochi", "сургут": "surgut",
    "калуга": "kaluga", "архангельск": "arkhangelsk",
    "чебоксары": "cheboksary", "калининград": "kaliningrad",
    "симферополь": "simferopol", "севастополь": "sevastopol",
    "якутск": "yakutsk", "вологда": "vologda",
    "бийск": "biysk", "нальчик": "nalchik", "назрань": "nazran",
    "магадан": "magadan", "биробиджан": "birobidzhan",
    "анадырь": "anadyr", "горно-алтайск": "gorno-altaysk",
    "кызыл": "kyzyl", "абакан": "abakan", "грозный": "grozny",
    "майкоп": "maykop", "элиста": "elista", "чебоксары": "cheboksary",
    "саранск": "saransk", "ижевск": "izhevsk", "кострома": "kostroma",
    "орёл": "orel", "смоленск": "smolensk", "тверь": "tver",
    "великий новгород": "velikiy-novgorod", "псков": "pskov",
    "мурманск": "murmansk", "петрозаводск": "petrozavodsk",
    "сыктывкар": "syktyvkar", "киров": "kirov",
    "нижневартовск": "nizhnevartovsk", "нефтеюганск": "nefteyugansk",
    "новороссийск": "novorossiysk", "таганрог": "taganrog",
    "шахты": "shakhty", "братск": "bratsk", "ангарск": "angarsk",
    "дзержинск": "dzerzhinsk", "орск": "orsk", "каменск-уральский": "kamensk-uralsky",
    "благовещенск": "blagoveshchensk", "энгельс": "engels",
    "королев": "korolyov", "мытищи": "mytishchi", "химки": "khimki",
    "подольск": "podolsk", "люберцы": "lyubertsy", "электросталь": "elektrostal",
    "красногорск": "krasnogorsk", "коломна": "kolomna",
    "одесса": "odessa", "минск": "minsk", "алматы": "almaty",
    "шымкент": "shymkent", "караганда": "karaganda",
    "актау": "aktau", "атырау": "atyrau", "актау": "aktau",
    "ташкент": "tashkent", "бишкек": "bishkek", "душанбе": "dushanbe",
    "ереван": "yerevan", "баку": "baku", "тбилиси": "tbilisi",
}


def _translit_city(city: str) -> str:
    key = city.lower().strip()
    if key in CITY_TRANSLIT:
        return CITY_TRANSLIT[key]
    # Автоматическая транслитерация для неизвестных городов
    return _auto_translit(key)


_AUTO_TRANS = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    ' ': '-', '-': '-',
}


def _auto_translit(text: str) -> str:
    """Автоматическая транслитерация русского текста в URL-формат."""
    result = []
    for ch in text:
        if ch in _AUTO_TRANS:
            result.append(_AUTO_TRANS[ch])
        elif ch.isascii() and (ch.isalnum() or ch == '-'):
            result.append(ch)
        # Остальные символы пропускаем
    translit = ''.join(result)
    # Убираем двойные дефисы
    while '--' in translit:
        translit = translit.replace('--', '-')
    return translit.strip('-')


_SOCIAL_DOMAINS = (
    "vk.com", "vkontakte.ru", "t.me", "telegram.me",
    "ok.ru", "odnoklassniki.ru",
    "instagram.com", "instagr.am",
    "facebook.com", "fb.com",
    "twitter.com", "x.com",
    "youtube.com", "youtu.be",
    "wa.me", "whatsapp.com",
    "viber.com",
    "tiktok.com",
    "dzen.ru",
    "max.ru",
)


def _is_social_url(url: str) -> bool:
    """Проверяет, является ли URL ссылкой на соцсеть/мессенджер."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in _SOCIAL_DOMAINS)


# Мусорные домены — НЕ являются реальным сайтом компании
_JUNK_DOMAINS = (
    # Агрегаторы ссылок / "визитки" (не полноценный сайт)
    "taplink.cc", "taplink.ru", "linktr.ee", "mssg.me", "lnk.bio",
    "mssg.io", "beacons.ai", "mylink.la", "linkin.bio", "clck.ru",
    "onelink.me", "hipolink.net", "biolink", "linktree",
    # Редиректы / трекеры / QR
    "checkscan.ru", "qrcode", "qr.io", "clck.yandex",
    "vk.link", "vk.cc", "bit.ly", "goo.gl", "clicks.", "tracker.",
    "utm.", "trk.",
    # Видео / стриминг
    "rutube.ru", "youtube.com", "youtu.be", "vimeo.com",
    # Маркетплейсы и агрегаторы (не собственный сайт)
    "wildberries.ru", "ozon.ru", "avito.ru", "market.yandex",
    "aliexpress", "flowwow.com", "yandex.ru/maps", "prodoctorov.ru",
    "zoon.ru", "yell.ru", "flamp.ru", "otzovik.com",
    # Пустые конструкторы (опубликованы без своего домена)
    ".tilda.ws", ".wixsite.com", ".nethouse.ru", ".ucoz.ru",
    ".jimdofree.com", ".blogspot.com", ".narod.ru", ".webnode.ru",
    ".site123.me", ".mozello.ru", ".b12sites.com", ".readymag.com",
    ".turbo.site", ".mya5.ru", ".flexbe.com", ".tb.ru",
    "object.pro",
)


def _is_junk_website(url: str) -> bool:
    """Проверяет, является ли URL мусорной ссылкой (агрегатор, трекер,
    конструктор-визитка, маркетплейс, видео), а НЕ реальным сайтом компании."""
    if not url:
        return True
    url_lower = url.lower()
    return any(junk in url_lower for junk in _JUNK_DOMAINS)


def _is_valid_company_site(url: str) -> bool:
    """Возвращает True, если URL похож на настоящий сайт компании."""
    return bool(url) and not _is_social_url(url) and not _is_junk_website(url)


class TwoGisScraper:
    """Скрапер 2GIS через Chrome (Playwright).
    Перехватывает внутренние API-запросы сайта 2GIS для получения данных компаний.
    Не требует API-ключа. Бесплатно навсегда.
    """

    BASE_URL = "https://2gis.ru"

    def __init__(self, timeout: int = 15, headless: bool = True):
        self.timeout = timeout
        self.headless = headless

    async def search_companies(
        self,
        city: str,
        rubric: str,
        max_results: int = 500,
        on_progress: Optional[Callable] = None,
        region: str = "",
    ) -> list[Company]:
        from playwright.async_api import async_playwright

        companies: list[Company] = []
        seen_ids: set[str] = set()
        raw_items: list[dict] = []  # Сырые данные компаний из маркеров
        api_key: str = ""  # Внутренний API-ключ 2GIS, извлечённый из запросов

        # Определяем slug: если задан регион — берём slug региона, иначе slug города
        if region and region.strip():
            location_slug = _get_region_slug(region.strip())
            region_keywords = _build_address_keywords(region.strip())
            logger.info(f"Режим поиска по региону: '{region}' → slug='{location_slug}'")
            logger.info(f"Ключевые слова для фильтрации адреса: {region_keywords}")
        else:
            location_slug = _translit_city(city)
            region_keywords = []
            logger.info(f"Режим поиска по городу: '{city}' → slug='{location_slug}'")

        rubric_encoded = quote(rubric, safe='')
        search_url = f"{self.BASE_URL}/{location_slug}/search/{rubric_encoded}"
        logger.info(f"Скрапер: открытие {search_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
            )

            # Stealth: hide automation
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)

            page = await context.new_page()

            # Перехватываем все JSON-ответы от catalog.api.2gis.ru
            async def handle_response(response):
                nonlocal api_key
                url = response.url

                # Извлекаем внутренний API-ключ из любого запроса к catalog.api
                if "catalog.api.2gis" in url and "key=" in url and not api_key:
                    key_match = re.search(r'key=([a-f0-9-]+)', url)
                    if key_match:
                        api_key = key_match.group(1)
                        logger.info(f"Извлечён API-ключ 2GIS: {api_key}")

                if "catalog.api.2gis" not in url:
                    return

                try:
                    body = await response.json()
                except Exception:
                    return

                result = body.get("result", body)
                if not isinstance(result, dict):
                    return

                items = result.get("items", [])
                if not items:
                    return

                for item in items:
                    if "name" not in item:
                        continue

                    # Фильтруем только компании
                    item_type = item.get("type", "")
                    if item_type and item_type not in ("branch", "firm", "organization", "spot"):
                        continue

                    item_id = item.get("id", "")
                    if not item_id or item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    raw_items.append(item)

                    if on_progress:
                        on_progress(len(raw_items), item.get("name", ""))

            page.on("response", handle_response)

            # Сначала открываем главную страницу 2GIS для установки cookies
            # Используем 30с timeout — museum-страница может грузиться медленно
            try:
                await page.goto(f"{self.BASE_URL}/{location_slug}", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
            except Exception as e:
                logger.warning(f"Ошибка загрузки главной страницы: {e}")

            # Обработка museum-страницы (антибот) на главной
            if "museum" in page.url:
                logger.info("Museum page on main, handling...")
                try:
                    btn = page.locator("#acceptRiskButton")
                    if await btn.count() > 0:
                        await btn.click()
                        await asyncio.sleep(5)
                except Exception as e:
                    logger.warning(f"Museum handling error: {e}")

            # Теперь открываем страницу поиска
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"Ошибка загрузки страницы поиска: {e}")

            await asyncio.sleep(3)

            # Если снова museum — кликаем и перенаправляем
            if "museum" in page.url:
                logger.info("Museum page on search, handling...")
                try:
                    btn = page.locator("#acceptRiskButton")
                    if await btn.count() > 0:
                        await btn.click()
                        await asyncio.sleep(3)
                except Exception:
                    pass
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.warning(f"Re-navigation error: {e}")

            logger.info(f"Current URL: {page.url}")

            # Ждём загрузки результатов
            await asyncio.sleep(5)

            # Скроллим для подгрузки большего числа компаний (маркеров)
            await self._scroll_for_items(page, raw_items, seen_ids, max_results, on_progress)

            logger.info(f"Собрано {len(raw_items)} компаний из маркеров")

            # Обогащаем данные: открываем страницу каждой компании для получения контактов
            # 2GIS сам делает items/byid запрос при открытии карточки компании
            companies = await self._enrich_by_visiting(
                page, raw_items, location_slug, max_results, on_progress,
                region_keywords=region_keywords,
            )

            await browser.close()

        logger.info(f"Скрапер: итогого {len(companies)} компаний с контактами")
        return companies

    async def _scroll_for_items(self, page, raw_items, seen_ids, max_results, on_progress):
        """Скроллит страницу для подгрузки большего числа маркеров."""
        prev_count = 0
        stagnant_rounds = 0
        max_stagnant = 10

        while len(raw_items) < max_results and stagnant_rounds < max_stagnant:
            # Скроллим вниз
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(0.5)

            await asyncio.sleep(2)

            if len(raw_items) == prev_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
                prev_count = len(raw_items)

            # Пагинация
            try:
                next_btn = page.locator('a[href*="/page/"]').last
                if await next_btn.count() > 0:
                    await next_btn.click()
                    await asyncio.sleep(3)
            except Exception:
                pass

    async def _enrich_by_visiting(self, page, raw_items: list[dict], city_slug: str, max_results: int, on_progress, region_keywords: list = None) -> list[Company]:
        """Открывает страницу каждой компании и парсит контакты из HTML.
        2GIS рендерит контакты (телефон, VK, TG, WA, сайт) прямо в HTML карточки."""
        companies: list[Company] = []

        for i, raw_item in enumerate(raw_items[:max_results]):
            item_id = str(raw_item.get("id", ""))
            name = raw_item.get("name", "")

            if not item_id:
                continue

            if on_progress:
                on_progress(i + 1, name)

            # Базовая компания из маркера
            company = self._parse_item(raw_item)
            if not company or not company.name:
                continue

            # Извлекаем числовой ID из составного ID маркера
            # Маркеры возвращают ID вида "70000001043874723_ygubhvlpdB..."
            # URL фирмы использует только числовую часть до "_"
            full_id = str(raw_item.get("id", ""))
            numeric_id = full_id.split("_")[0] if "_" in full_id else full_id

            # Проверяем принадлежность к региону по адресу из маркера (быстрая проверка до запроса)
            if region_keywords:
                raw_address = raw_item.get("address_name", "") or raw_item.get("full_address_name", "")
                if raw_address and not _address_matches_region(raw_address, region_keywords):
                    logger.debug(f"Пропускаем '{name}' — адрес '{raw_address}' не принадлежит региону")
                    continue

            # Строим URL карточки компании
            firm_url = f"{self.BASE_URL}/{city_slug}/firm/{numeric_id}"

            try:
                await page.goto(firm_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(5)
            except Exception:
                companies.append(company)
                continue

            # Если попали на museum — обрабатываем
            if "museum" in page.url:
                try:
                    btn = page.locator("#acceptRiskButton")
                    if await btn.count() > 0:
                        await btn.click()
                        await asyncio.sleep(5)
                        await page.goto(firm_url, wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(3)
                except Exception:
                    pass

            # Парсим контакты и дату первого отзыва из HTML
            try:
                html = await page.content()
                self._parse_contacts_from_html(html, company)
                self._extract_first_review_date(html, company)
                # Дополнительная проверка адреса по HTML (адрес может быть полнее)
                if region_keywords and company.address:
                    if not _address_matches_region(company.address, region_keywords):
                        logger.info(f"Отсеян '{name}' — адрес '{company.address}' не соответствует региону")
                        continue
            except Exception as e:
                logger.debug(f"HTML parse error for {name}: {e}")

            companies.append(company)

            # Небольшая задержка
            await asyncio.sleep(0.3)

        return companies

    def _parse_contacts_from_html(self, html: str, company: Company):
        """Извлекает контакты из HTML страницы компании 2GIS.
        Приоритет: __NEXT_DATA__ (структурированные данные) → link.2gis.ru (base64-ссылки) → regex."""
        import re as _re
        import base64 as _b64
        import json as _json

        # 1. Парсим __NEXT_DATA__ — там контакты в структурированном виде
        next_data_match = _re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.DOTALL
        )
        if next_data_match:
            try:
                next_data = _json.loads(next_data_match.group(1))
                self._extract_contacts_from_next_data(next_data, company)
            except Exception:
                pass

        # 2. Декодируем link.2gis.ru base64-ссылки
        if not company.website:
            self._extract_links_from_2gis_redirects(html, company)

        # 3. Regex fallback для телефонов (если __NEXT_DATA__ не дал)
        if not company.phones:
            phone_matches = _re.findall(r'\+7[\d\s\-\(\)]{10,17}', html)
            seen = set()
            for phone in phone_matches:
                phone_clean = phone.strip()
                if phone_clean not in seen and len(phone_clean) >= 12:
                    seen.add(phone_clean)
                    company.phones.append(phone_clean)
                    company.raw_contacts.append({"type": "phone", "value": phone_clean})

        # 4. Regex fallback для соцсетей
        if not company.vk_url:
            vk_matches = _re.findall(r'vk\.com/[a-zA-Z0-9_.-]+', html)
            if vk_matches:
                vk_url = f"https://{vk_matches[0]}"
                company.vk_url = vk_url
                company.raw_contacts.append({"type": "vkontakte", "value": vk_url})

        if not company.telegram_url:
            tg_matches = _re.findall(r't\.me/[a-zA-Z0-9_.-]+', html)
            if tg_matches:
                tg_url = f"https://{tg_matches[0]}"
                company.telegram_url = tg_url
                company.raw_contacts.append({"type": "telegram", "value": tg_url})

        if not company.whatsapp_url:
            wa_matches = _re.findall(r'wa\.me/[0-9]+', html)
            if wa_matches:
                wa_url = f"https://{wa_matches[0]}"
                company.whatsapp_url = wa_url
                company.raw_contacts.append({"type": "whatsapp", "value": wa_url})

        # 5. Regex fallback для сайта — ищем домены в видимом тексте
        if not company.website:
            # Ищем домены вида example.ru в тексте (не в href, а просто текст)
            # 2GIS показывает сайт как текст: white-dental.ru
            domain_matches = _re.findall(
                r'(?:^|[\s">])([a-z0-9][a-z0-9._-]+\.(?:ru|su|рф|com|net|org|info|biz|io|me|pro|dev|online|clinic|health|medical|stom|dent))',
                html, _re.IGNORECASE
            )
            for domain in domain_matches:
                domain_lower = domain.lower()
                # Фильтруем 2gis, соцсети, рекламные и служебные домены
                if any(x in domain_lower for x in ('2gis', 'yandex', 'vk.com', 't.me', 'wa.me', 'mail.ru', 'top100', 'tns', 'adfox', 'otello', 'doubleclick', 'mc.', 'top-fwz', 'facebook', 'google', 'apple', 'instagram')):
                    continue
                # Фильтруем соцсети, агрегаторы, трекеры, конструкторы
                if not _is_valid_company_site(domain_lower):
                    continue
                # Проверяем что это не часть другого домена (например d-assets.2gis.ru)
                if not domain_lower.startswith(('2gis', 'd-assets', 'd-api', 'st.', 'mc.', 'api.')):
                    company.website = f"http://{domain_lower}"
                    company.has_site = True
                    company.raw_contacts.append({"type": "website", "value": company.website})
                    break

    def _extract_contacts_from_next_data(self, next_data: dict, company: Company):
        """Извлекает контакты из __NEXT_DATA__ (Next.js SSR данные)."""
        import json as _json

        # Ищем contact_groups в разных местах структуры
        contact_groups = []

        # Путь 1: props.pageProps.firm.contact_groups
        props = next_data.get("props", {}).get("pageProps", {})
        firm = props.get("firm") or props.get("branch") or {}
        if isinstance(firm, dict):
            contact_groups = firm.get("contact_groups", [])

        # Путь 2: ищем вглубь через поиск по ключу
        if not contact_groups:
            contact_groups = self._find_key_recursive(next_data, "contact_groups") or []

        for group in contact_groups:
            if not isinstance(group, dict):
                continue
            contacts = group.get("contacts", [])
            for contact in contacts:
                if not isinstance(contact, dict):
                    continue
                ctype = contact.get("type", "")
                value = contact.get("value", "")
                if not value:
                    continue

                company.raw_contacts.append({"type": ctype, "value": value})

                if ctype == "phone":
                    if value not in company.phones:
                        company.phones.append(value)
                elif ctype == "website":
                    if not company.website and _is_valid_company_site(value):
                        company.website = value
                        company.has_site = True
                elif ctype == "vkontakte":
                    if not company.vk_url:
                        company.vk_url = value
                elif ctype == "telegram":
                    if not company.telegram_url:
                        company.telegram_url = value
                elif ctype == "whatsapp":
                    if not company.whatsapp_url:
                        company.whatsapp_url = value
                elif ctype in ("social", "social_profile"):
                    val_lower = value.lower()
                    if "vk.com" in val_lower or "vkontakte.ru" in val_lower:
                        if not company.vk_url:
                            company.vk_url = value
                    elif "t.me" in val_lower or "telegram" in val_lower:
                        if not company.telegram_url:
                            company.telegram_url = value

    def _extract_links_from_2gis_redirects(self, html: str, company: Company):
        """Декодирует link.2gis.ru redirect-ссылки (base64url) для извлечения реальных URL."""
        import re as _re
        import base64 as _b64

        # link.2gis.ru/4.2/HASH/aHR0cHM6Ly... (base64url)
        redirect_matches = _re.findall(
            r'link\.2gis\.ru/[\d.]+/[A-F0-9]+/([A-Za-z0-9+/=_-]+)', html
        )
        for encoded in redirect_matches:
            try:
                # base64url → base64
                padded = encoded + "=" * (4 - len(encoded) % 4) if len(encoded) % 4 else encoded
                decoded = _b64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
                # В декодированном тексте ищем URL
                url_match = _re.search(r'(https?://[^\s"\'<>]+)', decoded)
                if url_match:
                    url = url_match.group(1)
                    # Фильтруем 2gis, соцсети и мусорные домены (агрегаторы, трекеры)
                    if "2gis" in url:
                        continue
                    if not _is_valid_company_site(url):
                        continue
                    if not company.website:
                        company.website = url
                        company.has_site = True
                        company.raw_contacts.append({"type": "website", "value": url})
                        break
            except Exception:
                continue

    def _extract_first_review_date(self, html: str, company: Company):
        """Извлекает самую раннюю дату из HTML страницы компании.
        2GIS рендерит даты отзывов в формате ISO (2024-01-15T14:30).
        Самая ранняя дата ≈ дата первого отзыва ≈ начало активности компании."""
        import re as _re
        from datetime import datetime as _dt

        # Ищем все ISO даты: 2020-06-15T00:00 или 2024-01-15T14:30
        iso_dates = _re.findall(r'(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2})', html)
        if not iso_dates:
            return

        # Сортируем и берём самую раннюю
        iso_dates.sort()
        earliest_str = iso_dates[0]

        try:
            company.first_review_date = _dt.strptime(earliest_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            pass

    def _find_key_recursive(self, obj, key: str, max_depth: int = 5):
        """Рекурсивно ищет значение ключа в вложенной структуре dict/list."""
        if max_depth <= 0:
            return None
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                result = self._find_key_recursive(v, key, max_depth - 1)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_key_recursive(item, key, max_depth - 1)
                if result is not None:
                    return result
        return None

    def _parse_item(self, item: dict) -> Optional[Company]:
        """Парсит элемент из ответа API 2GIS в объект Company."""
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

        # Контакты могут быть в contact_groups или в contacts
        contact_groups = item.get("contact_groups", [])
        if not contact_groups:
            # Иногда контакты прямо в item
            contacts = item.get("contacts", [])
            if contacts:
                contact_groups = [{"contacts": contacts}]

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
                    if _is_valid_company_site(value):
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


def search_companies_sync(
    city: str,
    rubric: str,
    max_results: int = 500,
    timeout: int = 15,
    headless: bool = True,
    on_progress: Optional[Callable] = None,
    region: str = "",
) -> list[Company]:
    """Синхронная обёртка для скрапера 2GIS."""
    scraper = TwoGisScraper(timeout=timeout, headless=headless)
    return asyncio.run(scraper.search_companies(city, rubric, max_results, on_progress, region=region))
