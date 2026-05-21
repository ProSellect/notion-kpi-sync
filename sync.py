import os
from notion_client import Client
from datetime import datetime, timedelta
import calendar

# Konfiguracja tokenów z Secretów
try:
    notion = Client(auth=os.environ["NOTION_TOKEN"])
    KALENDARZ_DB_ID = os.environ["KALENDARZ_DB_ID"]
    AKTYWNOSCI_DB_ID = os.environ["AKTYWNOSCI_DB_ID"]
    WYNIKI_DB_ID = os.environ["WYNIKI_DB_ID"]
except KeyError as e:
    print(f"BŁĄD Brakujące zmienne środowiskowe: {e}")
    exit(1)

def generate_kpi_bar(current_val, target_val):
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
    try:
        results = notion.databases.query(database_id=db_id, filter={"property": "Nazwa", "title": {"equals": name}}).get("results")
        if results:
            return results[0]["id"], False
        
        page = notion.pages.create(parent={"database_id": db_id}, properties={
            "Nazwa": {"title": [{"text": {"content": name}}]},
            "Typ": {"select": {"name": typ}},
            "Data": {"date": {"start": str(date_ref)}},
            "Okres": {"rich_text": [{"text": {"content": period_text}}]}
        })
        print(f"  ➕ Utworzono nowy wpis: {name}")
        return page["id"], True
    except Exception as e:
        print(f"BŁĄD Tworzenie wpisu {name}: {e}")
        raise

def update_record(page_id, kpi_operacje, kpi_kontakt, kpi_sprzedaz):
    try:
        notion.pages.update(page_id=page_id, properties={
            "Operacje KPI": {"rich_text": [{"text": {"content": kpi_operacje}}]},
            "Kontakt KPI": {"rich_text": [{"text": {"content": kpi_kontakt}}]},
            "Sprzedaż KPI": {"rich_text": [{"text": {"content": kpi_sprzedaz}}]}
        })
    except Exception as e:
        print(f"BŁĄD Aktualizacja wpisu {page_id}: {e}")
        raise

def aggregate_period(start_date, end_date):
    """Poprawiona sekcja agregacji"""
    res = notion.databases.query(
        database_id=KALENDARZ_DB_ID,
        filter={
            "and": [
                {"property": "Date", "date": {"on_or_after": str(start_date)}},
                {"property": "Date", "date": {"on_or_before": str(end_date)}},
                {"property": "Dzień roboczy", "checkbox": {"equals": True}}
            ]
        }
    ).get("results", [])
    
    totals = {"op": 0, "kon": 0, "sprz": 0, "plan_op": 0, "plan_kon": 0, "plan_sprz": 0}
    
    for row in res:
        p = row["properties"]
        totals["plan_op"] += p.get("Plan Operacje", {}).get("number", 0) or 0
        totals["plan_kon"] += p.get("Plan Kontakt", {}).get("number", 0) or 0
        totals["plan_sprz"] += p.get("Plan Sprzedaż", {}).get("number", 0) or 0
        totals["op"] += p.get("Operacje (real)", {}).get("number", 0) or 0
        totals["kon"] += p.get("Kontakt (real)", {}).get("number", 0) or 0
        totals["sprz"] += p.get("Sprzedaż (real)", {}).get("number", 0) or 0
    
    return totals, len(res)

# --- GŁÓWNA LOGIKA ---
today = datetime.now().date()
print(f"🔄 START SYNCU ({today})...")

# Sprawdzenie czy jest dzień roboczy
try:
    dzien_robo = notion.databases.query(database_id=KALENDARZ_DB_ID, filter={
        "and": [{"property": "Date", "date": {"equals": str(today)}},
                {"property": "Dzień roboczy", "checkbox": {"equals": True}}]
    }).get("results", [])

    if not dzien_robo:
        print("⏸️ Brak dnia roboczego.")
        exit(0)

    dzien_page = dzien_robo[0]
    pobierz_plany = dzien_page["properties"]
    plan_op = pobierz_plany.get("Plan Operacje", {}).get("number", 0) or 0
    plan_kon = pobierz_plany.get("Plan Kontakt", {}).get("number", 0) or 0
    plan_sprz = pobierz_plany.get("Plan Sprzedaż", {}).get("number", 0) or 0

    act_list = notion.databases.query(database_id=AKTYWNOSCI_DB_ID, filter={"property": "Date", "date": {"equals": str(today)}}).get("results", [])
    akt_op = akt_kon = akt_sprz = 0

    for akt in act_list:
        props = akt["properties"]
        if props.get("Operacje flag"): akt_op += props["Operacje flag"].get("number", 0) or 0
        if props.get("Kontakt flag"): akt_kon += props["Kontakt flag"].get("number", 0) or 0
        if props.get("Sprzedaż flag"): akt_sprz += props["Sprzedaż flag"].get("number", 0) or 0

    print(f"📊 Dzisiaj: Op:{akt_op}/{plan_op} | Kon:{akt_kon}/{plan_kon} | Spr:{akt_sprz}/{plan_sprz}")

    notion.pages.update(page_id=dzien_page["id"], properties={
        "Operacje (real)": {"number": akt_op}, "Kontakt (real)": {"number": akt_kon}, "Sprzedaż (real)": {"number": akt_sprz}
    })

    # Dzień
    nazwa_dnia = today.strftime("%d/%m/%Y")
    period_dnia = today.strftime("%d.%m.%Y")
    id_dnia, _ = find_or_create_record(nazwa_dnia, WYNIKI_DB_ID, "Dzień", today, period_dnia)
    update_record(id_dnia, generate_kpi_bar(akt_op, plan_op), generate_kpi_bar(akt_kon, plan_kon), generate_kpi_bar(akt_sprz, plan_sprz))

    # Tydzień
    week_start, week_end = get_week_range(today)
    tydz_nr = today.isocalendar()[1]
    nazwa_tydz = f"Week {tydz_nr:02d}/{today.year}"
    okres_tydz = f"{week_start.strftime('%d.%m')}-{week_end.strftime('%d.%m.%Y')}"
    tot_tydz, _ = aggregate_period(week_start, week_end)
    id_tydz, _ = find_or_create_record(nazwa_tydz, WYNIKI_DB_ID, "Tydzień", week_start, okres_tydz)
    update_record(id_tydz, generate_kpi_bar(tot_tydz["op"], tot_tydz["plan_op"]), generate_kpi_bar(tot_tydz["kon"], tot_tydz["plan_kon"]), generate_kpi_bar(tot_tydz["sprz"], tot_tydz["plan_sprz"]))

    # Miesiąc
    month_start, month_end = get_month_range(today)
    nazwa_mies = f"{today.month:02d}/{today.year}"
    okres_mies = f"{calendar.month_name[today.month]} {today.year}"
    tot_mies, _ = aggregate_period(month_start, month_end)
    id_mies, _ = find_or_create_record(nazwa_mies, WYNIKI_DB_ID, "Miesiąc", month_start, okres_mies)
    update_record(id_mies, generate_kpi_bar(tot_mies["op"], tot_mies["plan_op"]), generate_kpi_bar(tot_mies["kon"], tot_mies["plan_kon"]), generate_kpi_bar(tot_mies["sprz"], tot_mies["plan_sprz"]))

    print("🎉 DONE: Synchronizacja zakończona!")
except Exception as e:
    print(f"FATAL ERROR podczas wykonywania synchronizacji: {e}")
    import traceback
    print(traceback.format_exc())
    exit(1)
