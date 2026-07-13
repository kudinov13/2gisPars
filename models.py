from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Company:
    name: str = ""
    address: str = ""
    phones: list[str] = field(default_factory=list)
    website: Optional[str] = None
    vk_url: Optional[str] = None
    telegram_url: Optional[str] = None
    whatsapp_url: Optional[str] = None
    rubrics: list[str] = field(default_factory=list)
    lat: Optional[float] = None
    lon: Optional[float] = None

    # Результаты анализа
    has_site: bool = False
    site_issues: list[str] = field(default_factory=list)
    site_critical_issues: list[str] = field(default_factory=list)
    site_is_good: bool = False

    # Возраст
    domain_created_date: Optional[datetime] = None
    vk_group_created_date: Optional[datetime] = None
    first_review_date: Optional[datetime] = None
    is_young: bool = False
    age_months: Optional[int] = None
    age_unknown: bool = False

    # Прочее
    raw_contacts: list[dict] = field(default_factory=list)

    @property
    def primary_phone(self) -> str:
        return self.phones[0] if self.phones else ""

    @property
    def has_messenger(self) -> bool:
        return bool(self.vk_url or self.telegram_url or self.whatsapp_url)

    @property
    def age_display(self) -> str:
        if self.age_months is not None:
            if self.age_months < 12:
                return f"{self.age_months} мес."
            years = self.age_months // 12
            months = self.age_months % 12
            return f"{years} г. {months} мес." if months else f"{years} г."
        if self.age_unknown:
            return "неизвестно (возм. молодая)"
        return "неизвестно"
