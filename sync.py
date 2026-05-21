import os
from notion_client import Client
from datetime import datetime, timedelta
import calendar

# Połączenie z Notion
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
KALENDARZ_DB_ID = os.environ.get("KALENDARZ_DB_ID")
AKTYWNOSCI_DB_ID = os.environ.get("AKTYWNOSCI_DB_ID")
WYNIKI_DB_ID = os.environ.get("WYNIKI_DB_ID")

notion = Client(auth=NOTION_TOKEN)

def generate_bar(current, target, max_overflow_blocks=10):
    if target == 0:
        return "⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0/0 (0%)"
    
    percentage = (current / target) * 100
    current_int = int(current)
    target_int = int(target)
    
    if percentage >= 100:
        status_icon = "✅"
    elif percentage >= 70:
        status_icon = "⚠️"
    else:
        status_icon = "🚨"
    
    if current <= target:
        filled = round((current / target) * 10)
        
        if percentage >= 100:
            color = "🟩"
        elif percentage >= 70:
            color = "🟨"
        else:
            color = "🟥"
        
        bar = color * filled + "⬜" * (10 - filled)
        overflow_text = ""
    else:
        green_blocks = 10
        overflow_ratio = (current - target) / target
        purple_blocks = min(round(overflow_ratio * 10), max_overflow_blocks)
        
        bar = "🟩" * green_blocks + "🟪" * purple_blocks
        overflow_text = f" (+{current_int - target_int})"
    
    return f"{bar} {current_int}/{target_int}{overflow_text} {status_icon} ({percentage:.0f}%)"

def get_week_range(date):
    monday = date - timedelta(days=date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

def get_month_range(date):
    first = date.replace(day=1)
    last = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    return first, last

def get_formula_number(prop):
    if prop and prop.get("formula"):
        formula = prop.get("formula", {})
        if formula.get("type") == "number":
            return formula.get("number", 0) or 0
    return 0

def find_or_create_wynik(name, typ, date_ref, okres_text):
    existing = notion.databases.query(
        database_id=WYNIKI_DB_ID,
        filter={"property": "Nazwa", "title": {"equals": name}}
    ).get("results")
    
    if existing:
        return existing[0]["id"]
    else:
        new_page = notion.pages.create(
            parent={"database_id": WYNIKI_DB_ID},
            properties={
                "Nazwa": {"title": [{"text": {"content": name}}]},
                "Typ": {"select": {"name": typ}},
                "Data": {"date": {"start": str(date_ref)}},
                "Okres": {"rich_text": [{"text": {"content": okres_text}}]}
            }
        )
        print(f"➕ Utworzono {name}")
        return new_page["id"]

def update_wynik_kpi(page_id, kpi_operacje, kpi_kontakt, kpi_sprzedaz):
    notion.pages.update(
        page_id=page_id,
        properties={
            "Operacje KPI": {"rich_text": [{"text": {"content": kpi_operacje}}]},
            "Kontakt KPI": {"rich_text": [{"text": {"content": kpi_kontakt}}]},
            "Sprzedaż KPI": {"rich_text": [{"text": {"content": kpi_sprzedaz}}]}
        }
    )

def aggregate_working_days(start_date, end_date):
    days = notion.databases.query(
        database_id=KALENDARZ_DB_ID,
        filter={
            "and": [
                {"property": "Data", "date": {"on_or_after": str(start_date)}},
                {"property": "Data", "date": {"on_or_before": str(end_date)}},
                {"property": "Dzień roboczy", "checkbox": {"equals": True}}
            ]
        }
    ).get("results", [])
    
    totals = {
        "operacje_plan": 0, "operacje_real": 0,
        "kontakt_plan": 0, "kontakt_real": 0,
        "sprzedaz_plan": 0, "sprzedaz_real": 0
    }
    
    for day in days:
        props = day["properties"]
        totals["operacje_plan"] += get_formula_number(props.get("Target operacje"))
        totals["operacje_real"] += props.get("Operacje (real)", {}).get("number", 0) or 0
        totals["kontakt_plan"] += get_formula_number(props.get("Target kontakty"))
        totals["kontakt_real"] += props.get("Kontakty (real)", {}).get("number", 0) or 0
        totals["sprzedaz_plan"] += get_formula_number(props.get("Target sprzedaż"))
        totals["sprzedaz_real"] += props.get("Sprzedaż (real)", {}).get("number", 0) or 0
    
    return totals, len(days)

# ==================== GŁÓWNY KOD ====================

today = datetime.now().date()
print(f"\n🔄 START: {today} {datetime.now().strftime('%H:%M')}")

# KROK 1: Sprawdź dzień roboczy
dzien_roboczy = notion.databases.query(
    database_id=KALENDARZ_DB_ID,
    filter={
        "and": [
            {"property": "Data", "date": {"equals": str(today)}},
            {"property": "Dzień roboczy", "checkbox": {"equals": True}}
        ]
    }
).get("results")

if not dzien_roboczy:
    print("⏸️ Brak dnia roboczego - pomijam")
    exit(0)

dzien = dzien_roboczy[0]
props = dzien["properties"]

plan_op = get_formula_number(props.get("Target operacje"))
plan_kon = get_formula_number(props.get("Target kontakty"))
plan_sprz = get_formula_number(props.get("Target sprzedaż"))

print(f"📋 Plan: Operacje={plan_op}, Kontakty={plan_kon}, Sprzedaż={plan_sprz}")

# KROK 2: Zsumuj flagi z aktywności
aktywnosci = notion.databases.query(
    database_id=AKTYWNOSCI_DB_ID,
    filter={"property": "Data", "date": {"equals": str(today)}}
).get("results", [])

real_op = 0
real_kon = 0
real_sprz = 0

for akt in aktywnosci:
    akt_props = akt["properties"]
    real_op += get_formula_number(akt_props.get("Operacje flag"))
    real_kon += get_formula_number(akt_props.get("Kontakt flag"))
    real_sprz += get_formula_number(akt_props.get("Sprzedaż flag"))

print(f"📊 DZIEŃ ({len(aktywnosci)} aktywności): Op {int(real_op)}/{plan_op}, Kon {int(real_kon)}/{plan_kon}, Sprz {int(real_sprz)}/{plan_sprz}")

# Zapisz do Kalendarz pracy
notion.pages.update(
    page_id=dzien["id"],
    properties={
        "Operacje (real)": {"number": int(real_op)},
        "Kontakty (real)": {"number": int(real_kon)},
        "Sprzedaż (real)": {"number": int(real_sprz)}
    }
)

# KROK 3: DZIEŃ - zapisz do Wyniki KPI
dzien_name = today.strftime("%d/%m/%Y")
dzien_okres = today.strftime("%d.%m.%Y")
dzien_page_id = find_or_create_wynik(dzien_name, "Dzień", today, dzien_okres)

update_wynik_kpi(
    dzien_page_id,
    generate_bar(real_op, plan_op),
    generate_bar(real_kon, plan_kon),
    generate_bar(real_sprz, plan_sprz)
)
print(f"✅ Dzień: {dzien_name}")

# KROK 4: TYDZIEŃ
week_start, week_end = get_week_range(today)
week_num = today.isocalendar()[1]
week_name = f"Week {week_num:02d}/{today.year}"
week_okres = f"{week_start.strftime('%d.%m')}-{week_end.strftime('%d.%m.%Y')}"

week_totals, week_days = aggregate_working_days(week_start, week_end)
print(f"📊 TYDZIEŃ ({week_days} dni): Op {int(week_totals['operacje_real'])}/{int(week_totals['operacje_plan'])}")

week_page_id = find_or_create_wynik(week_name, "Tydzień", week_start, week_okres)
update_wynik_kpi(
    week_page_id,
    generate_bar(week_totals['operacje_real'], week_totals['operacje_plan']),
    generate_bar(week_totals['kontakt_real'], week_totals['kontakt_plan']),
    generate_bar(week_totals['sprzedaz_real'], week_totals['sprzedaz_plan'])
)
print(f"✅ Tydzień: {week_name}")

# KROK 5: MIESIĄC
month_start, month_end = get_month_range(today)
month_name = f"{today.month:02d}/{today.year}"
month_okres = f"{calendar.month_name[today.month]} {today.year}"

month_totals, month_days = aggregate_working_days(month_start, month_end)
print(f"📊 MIESIĄC ({month_days} dni): Op {int(month_totals['operacje_real'])}/{int(month_totals['operacje_plan'])}")

month_page_id = find_or_create_wynik(month_name, "Miesiąc", month_start, month_okres)
update_wynik_kpi(
    month_page_id,
    generate_bar(month_totals['operacje_real'], month_totals['operacje_plan']),
    generate_bar(month_totals['kontakt_real'], month_totals['kontakt_plan']),
    generate_bar(month_totals['sprzedaz_real'], month_totals['sprzedaz_plan'])
)
print(f"✅ Miesiąc: {month_name}")

print(f"\n🎉 KONIEC: {datetime.now().strftime('%H:%M')}\n")
