import argparse
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    twogis_api_key: str = ""  # Не используется (скрапер не требует ключа)
    vk_service_token: str = ""
    city: str = "Новосибирск"
    cities: list[str] = field(default_factory=list)
    region: str = ""
    rubric: str = "стоматология"
    rubrics: list[str] = field(default_factory=list)
    use_niche_synonyms: bool = True
    lead_mode: str = "sales_ready"
    require_messenger: bool = False
    require_phone: bool = True
    only_young_companies: bool = False
    young_company_max_months: int = 24
    check_websites: bool = True
    skip_good_sites: bool = True
    max_minor_issues: int = 3
    max_results: int = 500
    http_timeout: int = 10
    audit_workers: int = 6
    output_file: str = "report.xlsx"


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Парсер компаний по 2GIS с проверкой сайтов и фильтром молодых компаний"
    )
    parser.add_argument("--city", type=str, default="Новосибирск", help="Город поиска")
    parser.add_argument("--region", type=str, default="", help="Регион поиска (республика, область, край). Если указан - город игнорируется")
    parser.add_argument("--rubric", type=str, default="стоматология", help="Сферы через запятую")
    parser.add_argument("--no-synonyms", action="store_true", help="Не расширять известные ниши синонимами")
    parser.add_argument("--lead-mode", choices=("all", "no_site", "problem_site", "high_rating_no_site", "sales_ready"), default="sales_ready")
    parser.add_argument("--vk-token", type=str, default=None, help="Сервисный токен VK (или переменная VK_SERVICE_TOKEN)")
    parser.add_argument("--only-young", action="store_true", help="Искать только молодые компании")
    parser.add_argument("--young-months", type=int, default=24, help="Максимальный возраст молодой компании (мес)")
    parser.add_argument("--require-messenger", action="store_true", help="Оставить только компании с мессенджером")
    parser.add_argument("--no-phone-filter", action="store_true", help="Не фильтровать по наличию телефона")
    parser.add_argument("--no-site-check", action="store_true", help="Не проверять сайты компаний")
    parser.add_argument("--no-skip-good", action="store_true", help="Не пропускать компании с хорошими сайтами")
    parser.add_argument("--max-results", type=int, default=500, help="Максимум компаний для обработки")
    parser.add_argument("--output", type=str, default="report.xlsx", help="Файл отчёта (xlsx)")

    args = parser.parse_args()

    cities = [value.strip() for value in args.city.split(",") if value.strip()]
    rubrics = [value.strip() for value in args.rubric.split(",") if value.strip()]
    return Config(
        vk_service_token=args.vk_token or os.environ.get("VK_SERVICE_TOKEN", ""),
        city=cities[0] if cities else "",
        cities=cities,
        region=args.region,
        rubric=rubrics[0] if rubrics else "",
        rubrics=rubrics,
        use_niche_synonyms=not args.no_synonyms,
        lead_mode=args.lead_mode,
        require_messenger=args.require_messenger,
        require_phone=not args.no_phone_filter,
        only_young_companies=args.only_young,
        young_company_max_months=args.young_months,
        check_websites=not args.no_site_check,
        skip_good_sites=not args.no_skip_good,
        max_results=args.max_results,
        output_file=args.output,
    )
