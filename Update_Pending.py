"""Navigate to each pending grade/section and open the student table.
   Actual per‑student update logic will be plugged in later.

   Reuses core modules so nothing is duplicated.
"""

import time
import os
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError
from core.browser_utils import safe_close, PAGE_TIMEOUT
from core.navigation import login_and_land
from core.dom_extractors import robust_click_view_update


def open_pending_detail_pages():
    """Iterate over every *Pending* row and simply open its detail table."""
    load_dotenv()
    user, pwd = os.getenv("SSG_USER"), os.getenv("SSG_PASS")
    if not (user and pwd):
        raise SystemExit("Set SSG_USER & SSG_PASS in .env")

    pw, browser, page = login_and_land(user, pwd)

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
            print(f"→ Opening detail for {grade}_{section} …")
            # time.sleep(3)
            if not robust_click_view_update(row, grade, section, page):
                print(f"⚠ click failed for {grade}_{section}")
                processed.add(key)
                continue

            try:
                page.wait_for_selector("table.mat-mdc-table", timeout=PAGE_TIMEOUT)
            except TimeoutError:
                print(f"⚠ detail table timeout for {grade}_{section}")
                processed.add(key)
                page.go_back()
                page.wait_for_selector(
                    "div.example-container table[mat-table] button.btn-primary", timeout=PAGE_TIMEOUT
                )
                continue

            # ------- YOU WILL ADD UPDATE LOGIC HERE --------
            time.sleep(3)
            student_count = len(page.query_selector_all("table.mat-mdc-table tbody tr"))
            print(f"   ✓ loaded table ({student_count} rows) → ready for updates")
            # ------------------------------------------------
            from core.dom_extractors import update_student_row

            updated = 0
            for tr in page.query_selector_all("table.mat-mdc-table tbody tr"):
                if update_student_row(tr, section, page):  # add page param
                    updated += 1
            print(f"   ✓ updated {updated} pending students")
            page.wait_for_timeout(500)


            processed.add(key)
            page.go_back()
            page.wait_for_selector(
                "div.example-container table[mat-table] button.btn-primary", timeout=PAGE_TIMEOUT
            )

    print("✔ All pending sections opened (Pending Students Updated ;)")
    safe_close(browser, pw)


if __name__ == "__main__":
    open_pending_detail_pages()
