import os
import tempfile
import unittest

from config import Config
from filters import analyze_companies, calculate_lead_score, classify_business, deduplicate_companies, filter_by_contacts, normalize_phone
from locations import get_region_cities
from models import Company
from niches import expand_rubrics
from report import generate_excel_report
from sources.twogis_scraper import TwoGisScraper, _build_address_keywords, _get_region_slug, _translit_city
from storage import LeadStorage


class ParserFeatureTests(unittest.TestCase):
    def test_rating_and_reviews_are_parsed(self):
        company = TwoGisScraper()._parse_item({
            "id": "123_hash", "name": "Мастерская",
            "reviews": {"general_rating": 4.8, "general_review_count": 37}, "org": {"branch_count": 2},
        })
        self.assertEqual(company.source_id, "123")
        self.assertEqual(company.rating, 4.8)
        self.assertEqual(company.reviews_count, 37)
        self.assertEqual(company.branches_count, 2)

    def test_review_date_ignores_unrelated_dates(self):
        company = Company(name="Компания")
        html = '<script id="__NEXT_DATA__">{"built":"2020-01-01T00:00","reviews":[{"date":"2024-02-03T10:20"}]}</script>'
        TwoGisScraper()._extract_first_review_date(html, company)
        self.assertEqual(company.first_review_date.strftime("%Y-%m-%d"), "2024-02-03")

    def test_phone_normalization_and_deduplication(self):
        first = Company(name="А", phones=["8 (999) 123-45-67"], rubrics=["Клининг"])
        second = Company(name="А компания", phones=["+7 999 123 45 67"], rubrics=["Уборка"])
        result = deduplicate_companies([first, second])
        self.assertEqual(normalize_phone(first.primary_phone), "79991234567")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].rubrics, ["Клининг", "Уборка"])

    def test_small_business_lead_score(self):
        company = Company(name="Мастерская мебели", phones=["+79991234567"], rating=4.7, reviews_count=25)
        classify_business(company)
        calculate_lead_score(company)
        self.assertEqual(company.business_size, "малый")
        self.assertGreaterEqual(company.lead_score, 80)
        self.assertIn("нет сайта", company.lead_reasons)

    def test_niche_synonyms(self):
        values = expand_rubrics(["клининг", "своя ниша"])
        self.assertIn("уборка помещений", values)
        self.assertIn("своя ниша", values)
        self.assertEqual(len(values), len(set(value.lower() for value in values)))
        self.assertIn("имплантация зубов", expand_rubrics(["Стоматологии"]))

    def test_specific_region_match_wins(self):
        self.assertEqual(_translit_city("Набережные Челны"), "nabchelny")
        self.assertEqual(_get_region_slug("Алтайский край, Россия"), "barnaul")
        self.assertIn("барнаул", _build_address_keywords("Алтайский край, Россия"))

    def test_region_expands_to_multiple_cities(self):
        cities = get_region_cities("Алтайский край")
        self.assertIn("Барнаул", cities)
        self.assertIn("Бийск", cities)
        self.assertIn("Рубцовск", cities)
        self.assertGreater(len(cities), 3)

    def test_region_city_slugs_are_valid(self):
        for city in get_region_cities("Алтайский край"):
            slug = _translit_city(city)
            self.assertTrue(slug, f"Нет slug для города {city}")
            self.assertNotIn("novosibirsk", slug)

    def test_storage_roundtrip_and_sales_status(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LeadStorage(os.path.join(directory, "test.db"))
            run_id = storage.create_run({"cities": ["Тула"]})
            company = Company(name="Компания", source_id="42", lead_score=75)
            storage.save_companies(run_id, [company], lambda item: f"2gis:{item.source_id}")
            storage.update_lead(run_id, "2gis:42", "Позвонили", "Перезвонить завтра")
            storage.save_companies(run_id, [company], lambda item: f"2gis:{item.source_id}")
            storage.update_run(run_id, query_index=3)
            loaded = storage.load_companies(run_id)
            self.assertEqual(loaded[0].sales_status, "Позвонили")
            self.assertEqual(loaded[0].sales_comment, "Перезвонить завтра")
            self.assertEqual(storage.get_run(run_id)["query_index"], 3)
            self.assertTrue(storage.delete_run(run_id))

    def test_excel_report_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "report.xlsx")
            generate_excel_report([Company(name="Компания", rating=4.9, reviews_count=12, lead_score=90)], path)
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 0)

    def test_config_does_not_require_messenger_by_default(self):
        self.assertFalse(Config().require_messenger)
        company = Company(name="Без мессенджера", phones=["+79991234567"])
        self.assertEqual(filter_by_contacts([company], False, True), [company])

    def test_good_site_is_skipped(self):
        company = Company(name="Качественный сайт", phones=["+79991234567"], website="https://example.org", has_site=True, site_is_good=True)
        config = Config(check_websites=False, skip_good_sites=True, lead_mode="all")
        self.assertEqual(analyze_companies([company], config), [])

    def test_site_quality_threshold(self):
        from analyzers.website_checker import SiteCheckResult, _finish
        good = _finish(SiteCheckResult(issues=["Нет H1"]))
        weak = _finish(SiteCheckResult(issues=["Нет H1", "Нет description", "Битая ссылка"]))
        self.assertTrue(good.is_good)
        self.assertFalse(weak.is_good)


if __name__ == "__main__":
    unittest.main()
