"""Fetch Student PEN using Aadhaar + YOB from UDISE Import Module.
   Navigates after login, loops through each Aadhaar from Excel,
   and appends PEN or failure status back into the DataFrame.
"""

import time
import os
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError, Error as PwError
from core.browser_utils import safe_close, PAGE_TIMEOUT
from core.navigation_pen import login_and_land
from datetime import datetime


def get_yob(value):
    """
    Accepts either pandas Timestamp, datetime, or string "DD/MM/YYYY".
    Returns 4-digit year as str, or None if parse fails.
    """
    if pd.isna(value):
        return None
    if hasattr(value, "year"):
        return str(value.year)
    try:
        return str(datetime.strptime(str(value).strip(), "%d/%m/%Y").year)
    except ValueError:
        return None
# Load and filter Aadhaar data
df = (
    pd.read_excel("students_extracted.xlsx")
      .query("aadharId.notnull() & aadharId != 0")
      .reset_index(drop=True)
)

def open_and_get_student_pen():
    load_dotenv()
    user, pwd = os.getenv("SSG_USER"), os.getenv("SSG_PASS")
    if not (user and pwd):
        raise SystemExit("Set SSG_USER & SSG_PASS in .env")

    pw = browser = page = None
    found, not_found = 0, 0

    try:
        pw, browser, page = login_and_land(user, pwd)

        for idx, row in df.iterrows():
            try:
                aadhar = str(int(row["aadharId"])).zfill(12)
                yob = get_yob(row["TxtDateOfBirth"])
                if yob is None:
                    df.at[idx, "student_pen"] = "Bad DOB"
                    print(f"✗ {row.TxtStudName} → invalid DOB")
                    not_found += 1
                    continue

                # Open modal
                # time.sleep(1)
                page.click("a:has-text('Get PEN & DOB')")
                # time.sleep(3)
                page.wait_for_selector("input[name='aadhaar']", timeout=5_000)
                page.fill("input[name='aadhaar']", aadhar)
                page.fill("input[name='dob']", str(yob))
                page.click("button:has-text('Search')")

                # Wait for result or failure popup
                try:
                    page.wait_for_selector(
                        "table.table tbody tr td:nth-child(1)", timeout=8_000
                    )
                    pen = page.inner_text("table.table tbody tr td:nth-child(1)")
                    dob = page.inner_text("table.table tbody tr td:nth-child(2)")
                    df.at[idx, "student_pen"] = pen
                    df.at[idx, "TxtDateOfBirth"] = dob
                    print(f"✓ {row.TxtStudName} → PEN {pen}")
                    found += 1

                except TimeoutError:
                    if page.is_visible("div.swal2-popup"):
                        page.click("button.swal2-confirm")
                        df.at[idx, "student_pen"] = "Wrong Aadhaar/YOB"
                        print(f"✗ {row.TxtStudName} → not found")
                        not_found += 1
                    else:
                        raise TimeoutError("No result and no popup appeared.")

                # Close modal
                page.press("body", "Escape")
                page.wait_for_selector("a:has-text('Get PEN & DOB')", timeout=4_000)

            except Exception as e:
                df.at[idx, "student_pen"] = f"Error: {str(e)[:30]}"
                print(f"‼ {row.TxtStudName} → ERROR → {e}")
                page.press("body", "Escape")
                time.sleep(1)

    finally:
        safe_close(browser, pw)
        df.to_excel("students_extracted_with_PEN.xlsx", index=False)
        print(f"\n🟢 Done → {found} PEN found, 🔴 {not_found} not found")
        print("📄 File saved as: students_extracted_with_PEN.xlsx")


if __name__ == "__main__":
    open_and_get_student_pen()
