import logging

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from models import Company

logger = logging.getLogger(__name__)


def generate_excel_report(companies: list[Company], output_file: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Компании"

    headers = [
        "№",
        "Название",
        "Адрес",
        "Телефон",
        "Сайт",
        "VK",
        "Telegram",
        "WhatsApp",
        "Возраст",
        "Молодая?",
        "Источники возраста",
        "Проблемы сайта (критичные)",
        "Проблемы сайта (минорные)",
        "Время загрузки (с)",
        "Рубрики",
    ]

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    young_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    critical_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

    for idx, company in enumerate(companies, 1):
        row = idx + 1
        ws.cell(row=row, column=1, value=idx)
        ws.cell(row=row, column=2, value=company.name)
        ws.cell(row=row, column=3, value=company.address)
        ws.cell(row=row, column=4, value=company.primary_phone)
        ws.cell(row=row, column=5, value=company.website or "—")
        ws.cell(row=row, column=6, value=company.vk_url or "—")
        ws.cell(row=row, column=7, value=company.telegram_url or "—")
        ws.cell(row=row, column=8, value=company.whatsapp_url or "—")
        ws.cell(row=row, column=9, value=company.age_display)
        ws.cell(row=row, column=10, value="Да" if company.is_young else "—")
        ws.cell(row=row, column=11, value=_age_sources(company))
        ws.cell(row=row, column=12, value="\n".join(company.site_critical_issues) if company.site_critical_issues else "—")
        ws.cell(row=row, column=13, value="\n".join(company.site_issues) if company.site_issues else "—")
        ws.cell(row=row, column=14, value=company.has_site)
        ws.cell(row=row, column=15, value=", ".join(company.rubrics))

        for col in range(1, len(headers) + 1):
            ws.cell(row=row, column=col).border = thin_border
            ws.cell(row=row, column=col).alignment = Alignment(vertical="top", wrap_text=True)

        if company.is_young:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row, column=col).fill = young_fill

        if company.site_critical_issues:
            ws.cell(row=row, column=12).fill = critical_fill

    col_widths = [5, 30, 35, 18, 30, 30, 25, 25, 12, 10, 25, 40, 40, 12, 30]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.row_dimensions[1].height = 35
    for row in range(2, len(companies) + 2):
        ws.row_dimensions[row].height = 30

    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(companies) + 1}"
    ws.freeze_panes = "A2"

    wb.save(output_file)
    logger.info(f"Отчёт сохранён: {output_file}")
    print(f"\n✅ Отчёт сохранён: {output_file}")
    print(f"   Всего компаний: {len(companies)}")


def _age_sources(company: Company) -> str:
    """Возвращает строку с источниками дат возраста компании."""
    sources = []
    if company.domain_created_date:
        sources.append(f"домен: {company.domain_created_date.strftime('%Y-%m-%d')}")
    if company.vk_group_created_date:
        sources.append(f"VK: {company.vk_group_created_date.strftime('%Y-%m-%d')}")
    if company.first_review_date:
        sources.append(f"2GIS отзыв: {company.first_review_date.strftime('%Y-%m-%d')}")
    if company.age_unknown:
        sources.append("источник не найден")
    return "\n".join(sources) if sources else "—"
