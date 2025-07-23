import os
import time
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError

# CONFIG
MAX_BROWSER_RETRIES = 3
MAX_NAV_RETRIES = 3
PAGE_TIMEOUT = 60_000
HEADLESS = False

# HELPERS
def launch_pw():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=HEADLESS, args=["--disable-gpu", "--disable-dev-shm-usage"])
    return pw, browser

def safe_close(*objs):
    for o in objs:
        try:
            o.close()
        except Exception:
            pass

# NAVIGATION
def login_and_land(user: str, pwd: str):
    last_err = None
    for b_try in range(1, MAX_BROWSER_RETRIES + 1):
        pw = browser = page = None
        try:
            pw, browser = launch_pw()
            page = browser.new_context().new_page()

            page.goto("https://sdms.udiseplus.gov.in/p2/v1/login?state-id=124", timeout=PAGE_TIMEOUT)
            page.fill("input[name='username']", user)
            page.fill("input[name='password']", pwd)
            input("Solve CAPTCHA in browser, then press [Enter] here → ")
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)

            page.click("div.filter2:has-text('Go to 2025-26')")
            if page.is_visible("div.modal-dialog"):
                page.click("button.btn.btn-danger:has-text('Close')")

            page.click("span.HideMobile:has-text('Student Movement and Progression')")
            page.click("span.HideMobile:has-text('Progression Activity')")

            time.sleep(4)
            summary_sel = "a.AnText:has-text('Progression Summary Section Wise')"
            page.wait_for_selector(summary_sel, timeout=PAGE_TIMEOUT)
            for n_try in range(1, MAX_NAV_RETRIES + 1):
                page.click(summary_sel)
                try:
                    page.wait_for_selector("div.example-container table[mat-table] button.btn-primary", timeout=PAGE_TIMEOUT)
                    print(f"✓ Summary ready (browser {b_try}, nav {n_try})")
                    return pw, browser, page
                except TimeoutError:
                    print("↻ retry summary click …")
            raise RuntimeError("View/Update buttons not visible")
        except Exception as err:
            last_err = err
            print(f"✗ browser launch {b_try} failed: {err}")
            safe_close(browser, pw)
    raise RuntimeError(f"All launches failed → {last_err}")

# PARSE STUDENT DETAILS
def parse_detail_table(page):
    from collections import OrderedDict
    records = []
    for tr in page.query_selector_all("table.mat-mdc-table tbody tr"):
        try:
            name = tr.query_selector("td.cdk-column-studentName span.fw-bold").inner_text().strip()
            status = tr.query_selector("td.cdk-column-status").inner_text().strip()
            progressed = tr.query_selector("td.cdk-column-updateDetails span.fw-bold").inner_text().strip()
            records.append(OrderedDict([("Student Name", name), ("Status", status), ("Progressed On", progressed)]))
        except Exception:
            continue
    return pd.DataFrame(records) if records else None

def robust_click_view_update(row, grade, section, page):
    from playwright.sync_api import Error as PwError
    try:
        row.query_selector("button.btn-primary").scroll_into_view_if_needed()
        row.query_selector("button.btn-primary").click()
        return True
    except PwError:
        sel = f"tr:has(td.cdk-column-className:has-text('{grade}')):has(td.cdk-column-sectionName:has-text('{section}')) button.btn-primary"
        try:
            page.locator(sel).first.scroll_into_view_if_needed()
            page.locator(sel).first.click()
            return True
        except Exception:
            return False

# MAIN EXPORT
def export_pending_sections(xlsx="UDISE.xlsx"):
    load_dotenv()
    user, pwd = os.getenv("SSG_USER"), os.getenv("SSG_PASS")
    if not (user and pwd):
        raise SystemExit("Set SSG_USER & SSG_PASS in .env")

    pw, browser, page = login_and_land(user, pwd)
    writer = pd.ExcelWriter(xlsx, engine="openpyxl")
    processed = set()

    while True:
        rows = page.query_selector_all("div.example-container table[mat-table] tbody tr")
        pending_rows = [r for r in rows if r.query_selector("td.cdk-column-status") and r.query_selector("td.cdk-column-status").inner_text().strip() == "Pending"]
        pending_rows = [r for r in pending_rows if (
            r.query_selector("td.cdk-column-className").inner_text().strip(),
            r.query_selector("td.cdk-column-sectionName").inner_text().strip(),
        ) not in processed]
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
                page.wait_for_selector("div.example-container table[mat-table] button.btn-primary", timeout=PAGE_TIMEOUT)
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
            page.wait_for_selector("div.example-container table[mat-table] button.btn-primary", timeout=PAGE_TIMEOUT)

    writer.close()
    print(f"✔ Export done → {xlsx}")
    safe_close(browser, pw)

if __name__ == "__main__":
    export_pending_sections()