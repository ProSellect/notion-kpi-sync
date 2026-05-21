import os
from notion_client import Client
from datetime import datetime, timedelta
import calendar

# Inicjalizacja
notion = Client(auth=os.environ["NOTION_TOKEN"])

KALENDARZ_DB_ID = os.environ["KALENDARZ_DB_ID"]
AKTYWNOSCI_DB_ID = os.environ["AKTYWNOSCI_DB_ID"]
WYNIKI_DB_ID = os.environ["WYNIKI_DB_ID"]

def generate_kpi_bar(current_val, target_val):
    """Generuje paski kolorowe KPI"""
    blocks_base = 10
    blocks_max_extra = 10
    
    if target_val == 0:
        return f"{'⬜' * blocks_base} 0/0 (0%)"
    
    current = int(float(current_val))
    target = int(float(target_val))
    percent = (current / target) * 100
    
    if percent >= 100:
        icon = "✅"
    elif percent >= 70:
        icon = "⚠️"
    else:
        icon = "🚨"
    
    if current <= target:
        filled_count = round((current / target) * blocks_base)
        
        if percent >= 100:
            char = "🟩"
        elif percent >= 70:
            char = "🟨"  
        else:
            char = "🟥"
            
        bar = char * filled_count + "⬜" * (blocks_base - filled_count)
        overflow_text = ""
    else:
        green_blocks = blocks_base
        ratio = (current - target) / target 
        purple_blocks = min(round(ratio * blocks_max_extra), blocks_max_extra)
        
        bar = "🟩" * green_blocks + "🟪" * purple_blocks
        overflow_text = f" (+{current - target})"
    
    return f"{bar} {current}/{target}{overflow_text} {icon} ({int(percent)}%)"

def get_week_range(date):
    monday = date - timedelta(days=date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

def get_month_range(date):
    first = date.replace(day=1)
    last = date.replace(day=calendar.monthrange(date.year, date.month)[1])
    return first, last

def find_or_create_record(name, db_id, typ, date_ref, period_text):
    results = notion.databases.query(
        database_id=db_id,
        filter={"property": "Nazwa", "title": {"equals": name}}
    ).get("results")
    
    if results:
        return results[0]["id"], False
    
    page = notion.pages.create(
        parent={"database_id": db_id},
        properties={
            "Nazwa": {"title": [{"text": {"content": name}}]},
            "Typ": {"select": {"name": typ}},
            "Data": {"date": {"start": str(date_ref)}},
            "Okres": {"rich_text": [{"text": {"content": period_text}}]}
        }
    )
    print(f"  ➕ Utworzono nowy wpis: {name}")
    return page["id"], True

def update_record(page_id, db_operacje, db_kontakt, db_sprzedaz):
    notion.pages.update(
        page_id=page_id,
        properties={
            "Operacje KPI": {"rich_text": [{"text": {"content": db_operacje}}]},
            "Kontakt KPI": {"rich_text": [{"text": {"content": db_kontakt}}]},
            "Sprzedaż KPI": {"rich_text": [{"text": {"content": db_sprzedaz}}]}
        }
    )

def aggregate_period(start_date, end_date):
    res = notion.databases.query(
        database_id=KALENDARZ_DB_ID,
        filter={
            "and": [
                {"property": "Date", "date": {"on_or_after": str(start_date)}},
                {"property": "Date", "date": {"on_or_before": str(end_date)}},
                {"property": "Dzień roboczy", "checkbox": {"equals": True}}
            ]
        }
    ).get("results")
    
    totals = {
        "op": 0, "kon": 0, "sprz": 0,
        "plan_op": 0, "plan_kon": 0, "plan_sprz": 0
    }
    
    for row in res:
        props = row["properties"]
        totals["plan_op"] += props.get("Plan Operacje", {}).get("number", 0) or 0
        totals["plan_kon"] += props.get("Plan Kontakt", {}).get("number", 0) or 0
        totals["plan_sprz"] += props.get("Plan Sprzedaż", {}).get("number", 0) or 0
        
        totals["op"] += props.get("Operacje (real)", {}).get("number", 0) or 0
        totals["kon"] += props.get("Kontakt (real)", {}).get("number", 0) or 0
        totals["sprz"] += props.get("Sprzedaż (real)", {}).get("number", 0) or 0
    
    return totals, len(res)

today = datetime.now().date()
print(f"\n🔄 START SYNCU ({today}): godz. {datetime.now().strftime('%H:%M')}")

dzen_robo = notion.databases.query(
    database_id=KALENDARZ_DB_ID,
    filter={
        "and": [
            {"property": "Date", "date": {"equals": str(today)}},
            {"property": "Dzień roboczy", "checkbox": {"equals": True}}
        ]
    }
).get("results")

if not dzen_robo:
    print("⏸️ BRAK DNIA ROBOCZEGO! Zatrzymuję sync.")
    exit(0)

dzien_page = dzen_robo[0]
dzien_id = dzien_page["id"]

pobierz_plany = dzien_page["properties"]
plan_op = pobierz_plany.get("Plan Operacje", {}).get("number", 0) or 0
plan_kon = pobierz_plany.get("Plan Kontakt", {}).get("number", 0) or 0
plan_sprz = pobierz_plany.get("Plan Sprzedaż", {}).get("number", 0) or 0

act_list = notion.databases.query(
    database_id=AKTYWNOSCI_DB_ID,
    filter={"property": "Date", "date": {"equals": str(today)}}
).get("results", [])

akt_op = 0
akt_kon = 0
akt_sprz = 0

for akt in act_list:
    props = akt["properties"]
    if props.get("Operacje flag"):
        akt_op += props["Operacje flag"].get("number", 0) or 0
    if props.get("Kontakt flag"):
        akt_kon += props["Kontakt flag"].get("number", 0) or 0
    if props.get("Sprzedaż flag"):
        akt_sprz += props["Sprzedaż flag"].get("number", 0) or 0

print(f" 📊 DZIEŃ: {len(act_list)} aktywności | Op:{akt_op}/{plan_op} | Kon:{akt_kon}/{plan_kon} | Spr:{akt_sprz}/{plan_sprz}")

notion.pages.update(page_id=dzien_id, properties={
    "Operacje (real)": {"number": akt_op},
    "Kontakt (real)": {"number": akt_kon},
    "Sprzedaż (real)": {"number": akt_sprz}
})

nazwa_dnia = today.strftime("%d/%m/%Y")
period_dnia = today.strftime("%d.%m.%Y")
id_dnia, nowy_dnia = find_or_create_record(nazwa_dnia, WYNIKI_DB_ID, "Dzień", today, period_dnia)

update_record(id_dnia,
    generate_kpi_bar(akt_op, plan_op),
    generate_kpi_bar(akt_kon, plan_kon),
    generate_kpi_bar(akt_sprz, plan_sprz)
)

start_tygodnia, kon_tygodnia = get_week_range(today)
tydz_nr = today.isocalendar()[1]
nazwa_tydz = f"Week {tydz_nr:02d}/{today.year}"
okres_tydz = f"{start_tygodnia.strftime('%d.%m')}-{kon_tygodnia.strftime('%d.%m.%Y')}"

tota_ltydz, ilosc_dni = aggregate_period(start_tygodnia, kon_tygodnia)
id_tydz, nowy_tydz = find_or_create_record(nazwa_tydz, WYNIKI_DB_ID, "Tydzień", start_tygodnia, okres_tydz)

update_record(id_tydz,
    generate_kpi_bar(tota_ltydz["op"], tota_ltydz["plan_op"]),
    generate_kpi_bar(tota_ltydz["kon"], tota_ltydz["plan_kon"]),
    generate_kpi_bar(tota_ltydz["sprz"], tota_ltydz["plan_sprz"])
)

start_mies, kon_mies = get_month_range(today)
nazwa_mies = f"{today.month:02d}/{today.year}"
okres_mies = f"{calendar.month_name[today.month]} {today.year}"

total_mies, _ = aggregate_period(start_mies, kon_mies)
id_mies, nowy_mies = find_or_create_record(nazwa_mies, WYNIKI_DB_ID, "Miesiąc", start_mies, okres_mies)

update_record(id_mies,
    generate_kpi_bar(total_mies["op"], total_mies["plan_op"]),
    generate_kpi_bar(total_mies["kon"], total_mies["plan_kon"]),
    generate_kpi_bar(total_mies["sprz"], total_mies["plan_sprz"])
)

print(f"\n🎉 DONE: Dzień, Tydzień, Miesiąc zsynchronizowane!")
