import os
import json
from notion_client import Client
from datetime import datetime, timedelta
import calendar

# Ścieżka do pliku pamięci podręcznej (cache)
CACHE_FILE = "cache/state.json"

try:
    notion = Client(auth=os.environ["NOTION_TOKEN"])
    KALENDARZ_DB_ID = os.environ["KALENDARZ_DB_ID"]
    AKTYWNOSCI_DB_ID = os.environ["AKTYWNOSCI_DB_ID"]
    WYNIKI_DB_ID = os.environ["WYNIKI_DB_ID"]
except KeyError as e:
    print(f"FATAL BŁĄD: {e}")
    exit(1)

def get_formula_value(prop_dict):
    if prop_dict and "formula" in prop_dict:
        return prop_dict["formula"].get("number") or 0
    return 0

def get_number_value(prop_dict):
    if prop_dict:
        return prop_dict.get("number") or 0
    return 0

def generate_bar(current_val, target_val, max_overflow_blocks=10):
    if target_val == 0:
        return f"⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0/0"
    percentage = (current_val / target_val) * 100
    current_int = int(current_val)
    target_int = int(target_val)
    if current_val <= target_val:
        filled = round((current_val / target_val) * 10)
        color = "🟩" if percentage >= 70 else "🟦"
        bar = color * filled + "⬜" * (10 - filled)
        return f"{bar} {current_int}/{target_int} ({percentage:.0f}%)"
    else:
        overflow_ratio = (current_val - target_val) / target_val
        overflow_blocks = min(round(overflow_ratio * 10), max_overflow_blocks)
        bar = ("🟩" * 10) + ("🟪" * overflow_blocks)
        overflow_percent = int(percentage - 100)
        return f"{bar} {current_int}/{target_int} (+{overflow_percent}%)"

def generate_uid(name, typ):
    today = datetime.now().date()
    if typ == "Dzień":
        return f"DAY_{today.strftime('%Y_%m_%d')}"
    elif typ == "Tydzień":
        week_num = today.isocalendar()[1]
        return f"WEEK_{today.year}_W{week_num:02d}"
    elif typ == "Miesiąc":
        return f"MONTH_{today.year}_{today.month:02d}"
    return f"UNKNOWN_{name.replace('/', '_')}"

def find_or_create_record(name, db_id, typ, date_ref, period_text):
    results = notion.databases.query(database_id=db_id, filter={"property": "Nazwa", "title": {"equals": name}}).get("results")
    uid = generate_uid(name, typ)
    if results:
        page_id = results[0]["id"]
        notion.pages.update(page_id=page_id, properties={"UID": {"rich_text": [{"text": {"content": uid}}]}})
        return page_id, True
    else:
        page = notion.pages.create(parent={"database_id": db_id}, properties={
            "Nazwa": {"title": [{"text": {"content": name}}]},
            "Typ": {"select": {"name": typ}},
            "Data": {"date": {"start": str(date_ref)}},
            "Okres": {"rich_text": [{"text": {"content": period_text}}]},
            "UID": {"rich_text": [{"text": {"content": uid}}]}
        })
        return page["id"], False

def update_kpi(page_id, exec_str, rel_str):
    notion.pages.update(page_id=page_id, properties={
        "Execution KPI": {"rich_text": [{"text": {"content": exec_str}}]},
        "Relationship KPI": {"rich_text": [{"text": {"content": rel_str}}]}
    })

def aggregate_period(start_date, end_date):
    res = notion.databases.query(database_id=KALENDARZ_DB_ID, filter={
        "and": [
            {"property": "Data", "date": {"on_or_after": str(start_date)}},
            {"property": "Data", "date": {"on_or_before": str(end_date)}},
            {"property": "Dzień roboczy", "checkbox": {"equals": True}}
        ]
    }).get("results", [])
    totals = {"execution": 0, "relationship": 0, "plan_exec": 0, "plan_rel": 0}
    for row in res:
        p = row["properties"]
        totals["plan_exec"] += get_formula_value(p.get("Target execution"))
        totals["plan_rel"] += get_formula_value(p.get("Target relationship"))
        totals["execution"] += get_number_value(p.get("Execution (real)"))
        totals["relationship"] += get_number_value(p.get("Relationship (real)"))
    return totals, len(res)

today = datetime.now().date()
print(f"\n🔄 START SYNC ENGINE V3 [CACHE ENABLED]: {today}\n")

# --- KROK CACHE: Pobierz i sprawdź stan aktywności ---
print("🔍 SZYBKI DIORAMA: Pobieram dzisiejsze aktywności do weryfikacji...")
act_list = notion.databases.query(database_id=AKTYWNOSCI_DB_ID, filter={
    "property": "Data", "date": {"equals": str(today)}
}).get("results", [])

exec_real = 0
rel_real = 0
for akt in act_list:
    props = akt["properties"]
    exec_real += get_formula_value(props.get("Execution flag")) + get_formula_value(props.get("Sprzedaż flag"))
    rel_real += get_formula_value(props.get("Kontakt flag"))

# Przygotuj unikalny podpis obecnych danych
current_state = {
    "date": str(today),
    "exec": int(exec_real),
    "rel": int(rel_real),
    "count": len(act_list)
}

# Próba wczytania poprzedniego cache
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f:
            old_state = json.load(f)
        if old_state == current_state:
            print(f"⏸️ CACHE MATCH: Dane dla {today} nie zmieniły się ({current_state['count']} aktywności). Pomijam dalszą synchronizację.")
            exit(0)
    except Exception:
        print("⚠️ Błąd odczytu cache - wymuszam pełny proces.")

# --- KONIEC KROKU CACHE ---

print("🔍 KROK 1: Szukam dzisiejszego dnia roboczego...")
dzien_robo = notion.databases.query(database_id=KALENDARZ_DB_ID, filter={
    "and": [
        {"property": "Data", "date": {"equals": str(today)}},
        {"property": "Dzień roboczy", "checkbox": {"equals": True}}
    ]
}).get("results", [])

if not dzien_robo:
    print("⏸️ BRAK DNIA ROBOCZEGO! Koniec.")
    exit(0)

dzien_page = dzien_robo[0]
dzien_id = dzien_page["id"]

pobierz_plany = dzien_page["properties"]
plan_exec = get_formula_value(pobierz_plany.get("Target execution"))
plan_rel = get_formula_value(pobierz_plany.get("Target relationship"))

print(f"📊 SUMA: Execution={int(exec_real)}, Relationship={int(rel_real)}")

print(f"\n🔍 KROK 4: Zapisuję do Kalendarza Pracy...")
notion.pages.update(page_id=dzien_id, properties={
    "Execution (real)": {"number": exec_real}, 
    "Relationship (real)": {"number": rel_real}
})

nazwa_dnia = today.strftime("%d/%m/%Y")
period_dnia = today.strftime("%d.%m.%Y")
id_dnia, _ = find_or_create_record(nazwa_dnia, WYNIKI_DB_ID, "Dzień", today, period_dnia)

update_kpi(id_dnia, generate_bar(exec_real, plan_exec), generate_bar(rel_real, plan_rel))

# Tydzień i Miesiąc
week_start = today - timedelta(days=today.weekday())
week_end = week_start + timedelta(days=6)
tydz_nr = today.isocalendar()[1]
nazwa_tydz = f"Week {tydz_nr:02d}/{today.year}"
okres_tydz = f"{week_start.strftime('%d.%m')}-{week_end.strftime('%d.%m.%Y')}"
tot_tydz, _ = aggregate_period(week_start, week_end)
id_tydz, _ = find_or_create_record(nazwa_tydz, WYNIKI_DB_ID, "Tydzień", week_start, okres_tydz)
update_kpi(id_tydz, generate_bar(tot_tydz["execution"], tot_tydz["plan_exec"]), generate_bar(tot_tydz["relationship"], tot_tydz["plan_rel"]))

month_start = today.replace(day=1)
month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
nazwa_mies = month_start.strftime("%Y-%m")
okres_mies = f"{calendar.month_name[today.month]} {today.year}"
tot_mies, _ = aggregate_period(month_start, month_end)
id_mies, _ = find_or_create_record(nazwa_mies, WYNIKI_DB_ID, "Miesiąc", month_start, okres_mies)
update_kpi(id_mies, generate_bar(tot_mies["execution"], tot_mies["plan_exec"]), generate_bar(tot_mies["relationship"], tot_mies["plan_rel"]))

# Zapisanie nowego stanu do cache po udanej synchronizacji
with open(CACHE_FILE, "w") as f:
    json.dump(current_state, f)
print("💾 Nowy stan zapisany w pamięci cache.")

print("\n✅ DONE: Wszystkie etapy zakończone!\n")
