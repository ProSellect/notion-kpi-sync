import os
import json
from notion_client import Client
from datetime import datetime, timedelta
import calendar

try:
    notion = Client(auth=os.environ["NOTION_TOKEN"])
    KALENDARZ_DB_ID = os.environ["KALENDARZ_DB_ID"]
    AKTYWNOSCI_DB_ID = os.environ["AKTYWNOSCI_DB_ID"]
    WYNIKI_DB_ID = os.environ["WYNIKI_DB_ID"]
except KeyError as e:
    print(f"FATAL BŁĄD: {e}")
    exit(1)

def get_formula_value(prop_dict):
    """Bezpieczne pobranie wartości z formuły"""
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
    else:
        return f"UNKNOWN_{name.replace('/', '_')}"

def find_or_create_record(name, db_id, typ, date_ref, period_text):
    results = notion.databases.query(database_id=db_id, filter={"property": "Nazwa", "title": {"equals": name}}).get("results")
    uid = generate_uid(name, typ)
    
    if results:
        page_id = results[0]["id"]
        notion.pages.update(page_id=page_id, properties={
            "UID": {"rich_text": [{"text": {"content": uid}}]}
        })
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
        totals["plan_exec"] += p.get("Target execution", {}).get("number", 0) or 0
        totals["plan_rel"] += p.get("Target relationship", {}).get("number", 0) or 0
        totals["execution"] += p.get("Execution (real)", {}).get("number", 0) or 0
        totals["relationship"] += p.get("Relationship (real)", {}).get("number", 0) or 0
    
    return totals, len(res)

today = datetime.now().date()
print(f"\n🔄 START SYNC ENGINE V3 DEBUG: {today}\n")

# 1. Sprawdź dzień roboczy
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
print(f"✅ Znaleziono dzień roboczy: {dzien_id[:8]}...")

# Pobieramy cele
pobierz_plany = dzien_page["properties"]
plan_exec = pobierz_plany.get("Target execution", {}).get("number", 0) or 0
plan_rel = pobierz_plany.get("Target relationship", {}).get("number", 0) or 0
print(f"📋 Cele z Kalendarza: Execution={plan_exec}, Relationship={plan_rel}\n")

# 2. Policz aktywności
print("🔍 KROK 2: Pobieram dzisiejsze aktywności...")
print(f"   Filtruję bazę Aktywności po: Data == {today}")

act_list = notion.databases.query(database_id=AKTYWNOSCI_DB_ID, filter={
    "property": "Data", "date": {"equals": str(today)}
}).get("results", [])

print(f"✅ Znaleziono {len(act_list)} rekordów aktywności\n")

if len(act_list) == 0:
    print("⚠️ UWAGA: Brak aktywności dla tej daty!")
    print("   Możliwe przyczyny:")
    print("   1. Pole 'Data' w bazie Aktywności ma inną nazwę (np. 'Data (dzień)')")
    print("   2. Nie ma wpisów z dzisiejszą datą")
    print("   3. Dane są w innej bazie\n")

exec_real = 0
rel_real = 0

print("🔍 KROK 3: Liczę wartości flag...")
for idx, akt in enumerate(act_list):
    props = akt["properties"]
    
    # DEBUG: Wypisz wszystkie nazwy kolumn w pierwszym rekordzie
    if idx == 0:
        print(f"   📋 Dostępne kolumny w rekordzie aktywności:")
        for key in props.keys():
            print(f"      - {key}")
        print()
    
    exec_flag = get_formula_value(props.get("Execution flag"))
    sprz_flag = get_formula_value(props.get("Sprzedaż flag"))
    kontakt_flag = get_formula_value(props.get("Kontakt flag"))
    
    exec_real += exec_flag + sprz_flag
    rel_real += kontakt_flag
    
    if idx < 3:  # Pokaż pierwsze 3 rekordy
        print(f"   Rekord {idx+1}: Execution={exec_flag}, Sprzedaż={sprz_flag}, Kontakt={kontakt_flag}")

print(f"\n📊 SUMA: Execution={int(exec_real)}, Relationship={int(rel_real)}")

# 3. Aktualizacja rekordu w Kalendarzu Pracy
print(f"\n🔍 KROK 4: Zapisuję do Kalendarza Pracy (ID: {dzien_id[:8]}...)...")
notion.pages.update(page_id=dzien_id, properties={
    "Execution (real)": {"number": exec_real}, 
    "Relationship (real)": {"number": rel_real}
})
print(f"✅ Zapisano: Execution (real)={int(exec_real)}, Relationship (real)={int(rel_real)}\n")

# 4. Wyniki KPI – DZIEŃ
nazwa_dnia = today.strftime("%d/%m/%Y")
period_dnia = today.strftime("%d.%m.%Y")
id_dnia, _ = find_or_create_record(nazwa_dnia, WYNIKI_DB_ID, "Dzień", today, period_dnia)

exec_bar = generate_bar(exec_real, plan_exec)
rel_bar = generate_bar(rel_real, plan_rel)

print(f"📊 Paski do zapisania:")
print(f"   Execution KPI: {exec_bar}")
print(f"   Relationship KPI: {rel_bar}\n")

update_kpi(id_dnia, exec_bar, rel_bar)

# 5-6. Tydzień i Miesiąc (bez zmian, skrócone dla przejrzystości)
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

print("\n✅ DONE: Wszystkie etapy zakończone!\n")
