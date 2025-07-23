"""Standalone script: export every *Pending* class/section to UDISE.xlsx."""
import time
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError
from core.browser_utils import safe_close, PAGE_TIMEOUT
from core.navigation import login_and_land
from core.dom_extractors import parse_detail_table, robust_click_view_update

OUTPUT_FILE = "UDISE.xlsx"


def export_pending_sections(xlsx: str = OUTPUT_FILE):
    load_dotenv()
    import os

    user, pwd = os.getenv("SSG_USER"), os.getenv("SSG_PASS")
    if not (user and pwd):
        raise SystemExit("Set SSG_USER & SSG_PASS in .env")

    pw, browser, page = login_and_land(user, pwd)
    writer = pd.ExcelWriter(xlsx, engine="openpyxl")
    processed = set()

    while True:
        rows = page.query_selector_all("div.example-container table[mat-table] tbody tr")
        pending_rows = [
            r
            for r in rows
            if r.query_selector("td.cdk-column-status")
            and r.query_selector("td.cdk-column-status").inner_text().strip() == "Pending"
        ]
        pending_rows = [
            r
            for r in pending_rows
            if (
                r.query_selector("td.cdk-column-className").inner_text().strip(),
                r.query_selector("td.cdk-column-sectionName").inner_text().strip(),
            )
            not in processed
        ]
        if not pending_rows:
            break

        for row in pending_rows:
            grade = row.query_selector("td.cdk-column-className").inner_text().strip()
            section = row.query_selector("td.cdk-column-sectionName").inner_text().strip()
            key = (grade, section)
            sheet = f"{grade}_{section}".replace(" ", "")[:31]
            print(f"→ {sheet}: opening detail…")

            if not robust_click_view_update(row, grade, section, page):
                print(f"⚠ click failed for {sheet}")
                processed.add(key)
                continue

            try:
                page.wait_for_selector("table.mat-mdc-table", timeout=PAGE_TIMEOUT)
            except TimeoutError:
                print(f"⚠ detail timeout for {sheet}")
                processed.add(key)
                page.go_back()
                page.wait_for_selector(
                    "div.example-container table[mat-table] button.btn-primary",
                    timeout=PAGE_TIMEOUT,
                )
                continue

            time.sleep(5)
            df = parse_detail_table(page)
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=sheet, index=False)
                print(f"   ✓ {len(df)} rows saved → {sheet}")
            else:
                print(f"⚠ parsed 0 rows for {sheet}")

            processed.add(key)
            page.go_back()
            page.wait_for_selector(
                "div.example-container table[mat-table] button.btn-primary",
                timeout=PAGE_TIMEOUT,
            )

    writer.close()
    print(f"✔ Export done → {xlsx}")
    safe_close(browser, pw)


if __name__ == "__main__":
    export_pending_sections()
