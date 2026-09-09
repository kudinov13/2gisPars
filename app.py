import logging
import os
import sys
import threading

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from config import Config
from filters import analyze_companies, company_key, deduplicate_companies, filter_by_contacts
from locations import get_region_cities
from models import Company
from niches import expand_rubrics
from report import generate_excel_report
from sources.twogis_scraper import search_companies_sync
from storage import LeadStorage

if getattr(sys, "frozen", False):
    _bundle_dir = sys._MEIPASS
    app = Flask(__name__, static_folder=os.path.join(_bundle_dir, "static"), static_url_path="/static")
    _data_dir = os.path.dirname(sys.executable)
else:
    app = Flask(__name__)
    _data_dir = os.path.dirname(__file__)
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
storage = LeadStorage(os.path.join(_data_dir, "parser_company.db"))
stop_event = threading.Event()
state_lock = threading.Lock()

parser_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_step": "",
    "results": [],
    "error": None,
    "finished": False,
    "stopped": False,
    "run_id": None,
}


def _split_values(value, fallback="") -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = str(value or fallback).replace("\n", ",").replace(";", ",").split(",")
    return list(dict.fromkeys(item.strip() for item in values if item and item.strip()))


def _build_config(data: dict) -> Config:
    cities = _split_values(data.get("cities") or data.get("city"), "Новосибирск")
    rubrics = _split_values(data.get("rubrics") or data.get("rubric"), "стоматология")
    return Config(
        vk_service_token=data.get("vk_token", ""),
        city=cities[0] if cities else "",
        cities=cities,
        region=str(data.get("region", "")).strip(),
        rubric=rubrics[0] if rubrics else "",
        rubrics=rubrics,
        use_niche_synonyms=bool(data.get("use_niche_synonyms", True)),
        lead_mode=data.get("lead_mode", "sales_ready"),
        require_messenger=bool(data.get("require_messenger", False)),
        require_phone=bool(data.get("require_phone", True)),
        only_young_companies=bool(data.get("only_young", False)),
        young_company_max_months=int(data.get("young_months", 24)),
        check_websites=bool(data.get("check_websites", True)),
        skip_good_sites=bool(data.get("skip_good_sites", True)),
        max_results=max(1, int(data.get("max_results", 500))),
        http_timeout=max(3, int(data.get("http_timeout", 10))),
        audit_workers=max(1, int(data.get("audit_workers", 6))),
    )


def _config_payload(config: Config) -> dict:
    return {
        "cities": config.cities,
        "region": config.region,
        "rubrics": config.rubrics,
        "vk_token": config.vk_service_token,
        "use_niche_synonyms": config.use_niche_synonyms,
        "lead_mode": config.lead_mode,
        "require_messenger": config.require_messenger,
        "require_phone": config.require_phone,
        "only_young": config.only_young_companies,
        "young_months": config.young_company_max_months,
        "check_websites": config.check_websites,
        "skip_good_sites": config.skip_good_sites,
        "max_results": config.max_results,
        "http_timeout": config.http_timeout,
        "audit_workers": config.audit_workers,
    }


def run_parser(config_dict: dict, run_id: int | None = None):
    global parser_state
    config = _build_config(config_dict)
    if run_id is None:
        run_id = storage.create_run(_config_payload(config))
        collected = []
        start_query_index = 0
    else:
        collected = storage.load_companies(run_id)
        saved_run = storage.get_run(run_id) or {}
        start_query_index = int(saved_run.get("query_index", 0))
        storage.update_run(run_id, status="running", error="")
    stop_event.clear()
    with state_lock:
        parser_state.update({
            "running": True, "progress": 0, "total": config.max_results,
            "current_step": "Инициализация...", "results": [], "error": None,
            "finished": False, "stopped": False, "run_id": run_id,
        })

    try:
        region_cities = get_region_cities(config.region) if config.region else []
        if region_cities:
            locations = [(city, "") for city in region_cities]
        elif config.region:
            locations = [("", config.region)]
        else:
            locations = [(city, "") for city in config.cities]
        rubrics = expand_rubrics(config.rubrics, config.use_niche_synonyms)
        combinations = [(city, region, rubric) for rubric in rubrics for city, region in locations]
        if region_cities:
            candidate_limit = config.max_results
            per_query = max(10, min(50, config.max_results // max(1, len(locations))))
        else:
            candidate_limit = config.max_results
            per_query = max(10, min(config.max_results, 50))

        pending_combinations = combinations[start_query_index:]
        for query_index, (city, region, rubric) in enumerate(pending_combinations, start_query_index + 1):
            if stop_event.is_set():
                break
            location = region or city
            parser_state["current_step"] = f"2GIS [{query_index}/{len(combinations)}]: {location} / {rubric}"

            def on_collect(count, name):
                parser_state["progress"] = min(config.max_results, len(collected) + count)
                parser_state["current_step"] = f"Сбор: {location} / {rubric} — {name}"

            found = search_companies_sync(
                city=city,
                region=region,
                rubric=rubric,
                max_results=per_query,
                timeout=config.http_timeout,
                headless=True,
                on_progress=on_collect,
                should_stop=stop_event.is_set,
            )
            for company in found:
                company.city = location
            collected = deduplicate_companies(collected + found)[:candidate_limit]
            storage.save_companies(run_id, collected, company_key)
            storage.update_run(
                run_id, progress=len(collected), total=config.max_results,
                query_index=None if stop_event.is_set() else query_index,
            )
            if len(collected) >= candidate_limit:
                break

        if stop_event.is_set():
            storage.update_run(run_id, status="stopped", progress=len(collected), total=config.max_results)
            parser_state.update({
                "running": False, "stopped": True, "finished": False,
                "current_step": f"Остановлено. Сохранено: {len(collected)}. Можно продолжить запуск.",
            })
            return

        unique_count = len(collected)
        companies = filter_by_contacts(collected, config.require_messenger, config.require_phone)
        contact_count = len(companies)
        logger.info(f"Воронка: уникальных={unique_count}, с контактами={contact_count}")
        parser_state["current_step"] = f"Глубокий аудит сайтов: {contact_count} компаний"
        parser_state["total"] = len(companies)

        def on_analysis(count, name):
            parser_state["progress"] = count
            parser_state["current_step"] = name

        analyzed = analyze_companies(
            companies, config, should_stop=stop_event.is_set, on_progress=on_analysis,
        )[:config.max_results]
        if not stop_event.is_set():
            storage.clear_companies(run_id)
        storage.save_companies(run_id, analyzed, company_key)

        if stop_event.is_set():
            storage.update_run(run_id, status="stopped", progress=len(analyzed), total=len(companies))
            parser_state.update({
                "running": False, "stopped": True, "finished": False,
                "current_step": f"Остановлено. Сохранено: {len(analyzed)}. Можно продолжить запуск.",
            })
            return

        parser_state["results"] = [_company_to_dict(company) for company in analyzed]
        parser_state["current_step"] = (
            f"Готово: {len(analyzed)} лидов из {unique_count} уникальных компаний "
            f"({contact_count} с телефоном)"
        )
        parser_state["finished"] = True
        output_file = os.path.join(_data_dir, f"report_{run_id}.xlsx")
        generate_excel_report(analyzed, output_file)
        storage.update_run(run_id, status="finished", progress=len(analyzed), total=len(analyzed))
    except Exception as exc:
        parser_state["error"] = str(exc)
        storage.update_run(run_id, status="error", error=str(exc))
        logger.exception("Ошибка парсинга")
    finally:
        parser_state["running"] = False


def _company_to_dict(company: Company) -> dict:
    return {
        "lead_key": company_key(company),
        "name": company.name,
        "address": company.address,
        "city": company.city,
        "phone": company.primary_phone,
        "website": company.website if company.website and company.has_site else "нет сайта",
        "vk": company.vk_url or "-",
        "telegram": company.telegram_url or "-",
        "whatsapp": company.whatsapp_url or "-",
        "has_messenger": company.has_messenger,
        "rating": company.rating,
        "reviews_count": company.reviews_count,
        "lead_score": company.lead_score,
        "lead_reasons": company.lead_reasons,
        "business_size": company.business_size,
        "business_size_reasons": company.business_size_reasons,
        "sales_status": company.sales_status,
        "sales_comment": company.sales_comment,
        "age_display": company.age_display,
        "is_young": company.is_young,
        "age_months": company.age_months,
        "age_unknown": company.age_unknown,
        "site_critical": company.site_critical_issues,
        "site_issues": company.site_issues,
        "site_is_good": company.site_is_good,
        "site_load_time": company.site_load_time,
        "site_status_code": company.site_status_code,
        "site_audit_score": company.site_audit_score,
        "site_audit_confidence": company.site_audit_confidence,
        "has_site": company.has_site,
        "rubrics": ", ".join(company.rubrics),
    }


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/start", methods=["POST"])
def start_parser():
    with state_lock:
        if parser_state["running"]:
            return jsonify({"error": "Парсер уже запущен"}), 400
        parser_state.update({"running": True, "finished": False, "stopped": False, "error": None})
    data = request.get_json(silent=True) or {}
    thread = threading.Thread(target=run_parser, args=(data,), daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/stop", methods=["POST"])
def stop_parser():
    with state_lock:
        if not parser_state["running"]:
            return jsonify({"status": "idle"})
        parser_state["current_step"] = "Остановка после текущей операции..."
    stop_event.set()
    return jsonify({"status": "stopping"})


@app.route("/api/status")
def get_status():
    return jsonify({
        key: parser_state[key] for key in (
            "running", "progress", "total", "current_step", "error", "finished", "stopped", "run_id",
        )
    } | {"results_count": len(parser_state["results"])})


@app.route("/api/results")
def get_results():
    requested_run_id = request.args.get("run_id", type=int)
    run_id = requested_run_id or parser_state["run_id"]
    if requested_run_id:
        companies = storage.load_companies(requested_run_id)
        return jsonify({"results": [_company_to_dict(company) for company in companies], "run_id": requested_run_id})
    return jsonify({"results": parser_state["results"], "run_id": run_id})


@app.route("/api/download")
def download_report():
    run_id = request.args.get("run_id", type=int) or parser_state["run_id"]
    if not run_id:
        return jsonify({"error": "Запуск не выбран"}), 404
    filepath = os.path.join(_data_dir, f"report_{run_id}.xlsx")
    if not os.path.exists(filepath):
        companies = storage.load_companies(run_id)
        if not companies:
            return jsonify({"error": "Отчёт не найден"}), 404
        generate_excel_report(companies, filepath)
    return send_file(filepath, as_attachment=True, download_name=f"report_{run_id}.xlsx")


@app.route("/api/runs")
def list_runs():
    runs = storage.list_runs()
    for item in runs:
        item.pop("config_json", None)
    return jsonify({"runs": runs})


@app.route("/api/runs/<int:run_id>/resume", methods=["POST"])
def resume_run(run_id: int):
    with state_lock:
        if parser_state["running"]:
            return jsonify({"error": "Парсер уже запущен"}), 400
        run = storage.get_run(run_id)
        if not run:
            return jsonify({"error": "Список не найден"}), 404
        parser_state.update({"running": True, "finished": False, "stopped": False, "error": None})
    thread = threading.Thread(target=run_parser, args=(run["config"], run_id), daemon=True)
    thread.start()
    return jsonify({"status": "started", "run_id": run_id})


@app.route("/api/runs/<int:run_id>", methods=["DELETE"])
def delete_run(run_id: int):
    if parser_state["running"] and parser_state["run_id"] == run_id:
        return jsonify({"error": "Нельзя удалить активный запуск"}), 409
    deleted = storage.delete_run(run_id)
    filepath = os.path.join(_data_dir, f"report_{run_id}.xlsx")
    if os.path.exists(filepath):
        os.remove(filepath)
    return jsonify({"deleted": deleted})


@app.route("/api/runs/<int:run_id>/leads", methods=["PATCH"])
def update_lead(run_id: int):
    data = request.get_json(silent=True) or {}
    lead_key = str(data.get("lead_key", ""))
    status = str(data.get("sales_status", "Новый"))
    comment = str(data.get("sales_comment", ""))
    allowed = {"Новый", "Подготовлен", "Позвонили", "Перезвонить", "Не дозвонились", "Не актуально", "Сайт заказан", "Отказ"}
    if not lead_key or status not in allowed:
        return jsonify({"error": "Некорректные данные"}), 400
    storage.update_lead(run_id, lead_key, status, comment)
    return jsonify({"updated": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=18923, debug=False)
