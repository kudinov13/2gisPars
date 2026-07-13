import logging
import os
import threading
import time

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

from sources.twogis_scraper import search_companies_sync
from filters import filter_by_contacts, analyze_companies
from report import generate_excel_report
from models import Company

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Глобальное состояние парсинга
parser_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_step": "",
    "results": [],
    "error": None,
    "finished": False,
}


def run_parser(config_dict: dict):
    global parser_state
    parser_state.update({
        "running": True,
        "progress": 0,
        "total": 0,
        "current_step": "Инициализация...",
        "results": [],
        "error": None,
        "finished": False,
    })

    try:
        from config import Config
        config = Config(
            vk_service_token=config_dict.get("vk_token", ""),
            city=config_dict.get("city", "Новосибирск"),
            region=config_dict.get("region", ""),
            rubric=config_dict.get("rubric", "стоматология"),
            require_messenger=config_dict.get("require_messenger", True),
            require_phone=config_dict.get("require_phone", True),
            only_young_companies=config_dict.get("only_young", False),
            young_company_max_months=config_dict.get("young_months", 24),
            check_websites=config_dict.get("check_websites", True),
            skip_good_sites=config_dict.get("skip_good_sites", True),
            max_results=config_dict.get("max_results", 500),
        )

        location_display = config.region if config.region else config.city
        parser_state["current_step"] = f"Открытие 2GIS: {location_display} / {config.rubric}"

        def on_progress(count, name):
            parser_state["progress"] = count
            parser_state["total"] = config.max_results
            parser_state["current_step"] = f"Сбор данных: [{count}] {name}"

        companies = search_companies_sync(
            city=config.city,
            rubric=config.rubric,
            max_results=config.max_results,
            timeout=config.http_timeout,
            headless=True,
            on_progress=on_progress,
            region=config.region,
        )

        parser_state["total"] = len(companies)

        if not companies:
            parser_state["error"] = "Компании не найдены"
            parser_state["running"] = False
            return

        parser_state["current_step"] = "Фильтрация по контактам"
        companies = filter_by_contacts(companies, config.require_messenger, config.require_phone)

        parser_state["current_step"] = "Анализ компаний"
        parser_state["total"] = len(companies)

        # Используем analyze_companies из filters.py (актуальная логика возраста)
        analyzed = analyze_companies(companies, config)

        parser_state["results"] = [_company_to_dict(c) for c in analyzed]
        parser_state["current_step"] = f"Готово. Найдено: {len(analyzed)} компаний"
        parser_state["finished"] = True

        # Сохраняем Excel
        if analyzed:
            output_file = os.path.join(os.path.dirname(__file__), "report.xlsx")
            generate_excel_report(analyzed, output_file)

    except Exception as e:
        parser_state["error"] = str(e)
        logger.exception("Ошибка парсинга")
    finally:
        parser_state["running"] = False


def _company_to_dict(c: Company) -> dict:
    return {
        "name": c.name,
        "address": c.address,
        "phone": c.primary_phone,
        "website": c.website or "—",
        "vk": c.vk_url or "—",
        "telegram": c.telegram_url or "—",
        "whatsapp": c.whatsapp_url or "—",
        "age_display": c.age_display,
        "is_young": c.is_young,
        "age_months": c.age_months,
        "age_unknown": c.age_unknown,
        "site_critical": c.site_critical_issues,
        "site_issues": c.site_issues,
        "has_site": c.has_site,
        "rubrics": ", ".join(c.rubrics),
    }


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/start", methods=["POST"])
def start_parser():
    if parser_state["running"]:
        return jsonify({"error": "Парсер уже запущен"}), 400

    config = request.json
    thread = threading.Thread(target=run_parser, args=(config,))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def stop_parser():
    parser_state["running"] = False
    return jsonify({"status": "stopped"})


@app.route("/api/status")
def get_status():
    return jsonify({
        "running": parser_state["running"],
        "progress": parser_state["progress"],
        "total": parser_state["total"],
        "current_step": parser_state["current_step"],
        "error": parser_state["error"],
        "finished": parser_state["finished"],
        "results_count": len(parser_state["results"]),
    })


@app.route("/api/results")
def get_results():
    return jsonify({"results": parser_state["results"]})


@app.route("/api/download")
def download_report():
    filepath = os.path.join(os.path.dirname(__file__), "report.xlsx")
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name="report.xlsx")
    return jsonify({"error": "Отчёт не найден"}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=18923, debug=False)
