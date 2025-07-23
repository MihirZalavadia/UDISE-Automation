# release_request_combined.py
# ============================================================
"""End‑to‑end script for UDISE +:

    1.  **open_release_request_module()**
        • Logs in (2025‑26) using `.env` creds.
        • Clicks **Student Release Request Management → Go → Generate Student Release Request(s) Within State**.
        • Returns `(page, browser, pw)` already parked on the PEN/DOB form.

    2.  **generate_release_requests()**
        • Loads *students_extracted_with_PEN_school.xlsx*.
        • Drops rows where `school_name == "SMT. SAROJINI NAIDU GIRLS HIGH SCHOOL"`.
        • For each remaining student:
            ─ Fill PEN & DOB → *Get Details*
            ─ If current school is Sarojini Naidu → skip
            ─ Else select remark **Please release …** and click *Generate Student Release Request*.
            ─ Handles SweetAlert (success / already‑raised) and writes outcome to `release_status`.
        • Saves checkpoints every 20 students and final XLSX `students_release_requests.xlsx`.

    Run standalone:
        python release_request_combined.py
"""

import os
import re
import time
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError

from core.browser_utils import safe_close
from core.navigation_pen import login_and_land

# -------------------------------------------------------------------------
# CONSTANTS / SELECTORS
# -------------------------------------------------------------------------
TARGET_SCHOOL = "SMT. SAROJINI NAIDU GIRLS HIGH SCHOOL"

# --- navigation selectors ---
MENU_SPAN   = "span.HideMobile:has-text('Student Release Request Management')"
CARD_GO_BTN = "li.cardIcon:has(h2:has-text('Student Release Request Management')) button:has-text('Go')"
GEN_BTN_TOP = "button:has-text('Generate Student Release Request')"

# --- form selectors ---
PEN_INPUT  = "input[placeholder='Enter PEN']"
DOB_INPUT  = "input[placeholder='DD/MM/YYYY']"
GET_BTN    = "button:has-text('Get Details')"

SCHOOL_NAME_SPAN = "li:has(span.title:has-text('School Name')) span.vlause"
REMARK_SELECT = "div:has(p:has-text('Select Remark')) select.form-select"
GEN_REQ_BTN      = "button:has-text('Generate Student Release Request')"

# --- SweetAlert selectors ---
POPUP_ANY   = "div.swal2-popup.swal2-show"
OK_BTN_POP  = "div.swal2-popup.swal2-show button.swal2-confirm"
SUCCESS_TTL = "div.swal2-popup.swal2-icon-success h2.swal2-title"
ERROR_TTL   = "div.swal2-popup.swal2-icon-error   h2.swal2-title"

# -------------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------------

def normalize_ddmmyyyy(val):
    if pd.isna(val):
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return s
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return None


def handle_popup(page):
    """Return status string from SweetAlert (success / already raised)."""
    status = "Unknown"
    sr_no  = ""
    try:
        page.wait_for_selector(POPUP_ANY, timeout=10_000)
        if page.is_visible(SUCCESS_TTL):
            ttl = page.inner_text(SUCCESS_TTL).strip()
            m = re.search(r"Request No: (\S+)", ttl)
            if m:
                sr_no = m.group(1)
            status = f"Request Raised {sr_no}" if sr_no else "Request Raised"
        elif page.is_visible(ERROR_TTL):
            ttl = page.inner_text(ERROR_TTL).strip()
            if "already pending" in ttl.lower():
                status = "Already Raised"
            else:
                status = ttl[:60]
    finally:
        if page.is_visible(OK_BTN_POP):
            page.click(OK_BTN_POP)
            page.wait_for_selector(POPUP_ANY, state="detached", timeout=5_000)
    return status

# -------------------------------------------------------------------------
# Stage 1 – landing helper
# -------------------------------------------------------------------------

def open_release_request_module():
    """Login + navigate to Generate Student Release Request page."""
    load_dotenv()
    user, pwd = os.getenv("SSG_USER"), os.getenv("SSG_PASS")
    if not user or not pwd:
        raise SystemExit("Set SSG_USER & SSG_PASS in .env")

    pw = browser = page = None
    try:
        pw, browser, page = login_and_land(user, pwd)
        # menu → go card
        page.click(MENU_SPAN)
        time.sleep(0.5)
        page.click(CARD_GO_BTN)
        page.wait_for_load_state("networkidle")
        # generate button
        page.click(GEN_BTN_TOP)
        page.wait_for_load_state("networkidle")
        return page, browser, pw
    except Exception as err:
        safe_close(browser, pw)
        raise RuntimeError(f"Navigation failed: {err}")

# -------------------------------------------------------------------------
# Stage 2 – main loop
# -------------------------------------------------------------------------

def get_student_school_request(
    in_xlsx="students_extracted_with_PEN_school.xlsx",
    out_xlsx="students_release_requests.xlsx",
):

    df = pd.read_excel(in_xlsx)
    if "release_status" not in df.columns:
        df["release_status"] = ""

    todo_mask = df["school_name"].str.strip().ne(TARGET_SCHOOL)
    df_todo = df[todo_mask].reset_index(drop=False)
    idx_map = dict(zip(df_todo.index, df_todo["index"]))
    print(f"→ {len(df_todo)} students to process (after filter).")

    page, browser, pw = open_release_request_module()

    processed = 0
    for row_idx, orig_idx in idx_map.items():
        pen = str(df.at[orig_idx, "student_pen"]).strip()
        dob = normalize_ddmmyyyy(df.at[orig_idx, "TxtDateOfBirth"])
        if not dob:
            df.at[orig_idx, "release_status"] = "Skipped (bad DOB)"
            continue

        print(f"→ ({processed+1}/{len(df_todo)}) {pen} …", end="")
        try:
            page.fill(PEN_INPUT, pen)
            page.fill(DOB_INPUT, dob)
            page.click(GET_BTN)
            # wait for school
            try:
                page.wait_for_selector(SCHOOL_NAME_SPAN, timeout=6_000)
            except TimeoutError:
                pass
            school = page.inner_text(SCHOOL_NAME_SPAN).strip()
            print(school, end=" | ")

            if school.upper().replace(" ","") == TARGET_SCHOOL.upper().replace(" ",""):
                df.at[orig_idx, "release_status"] = "School is our school—skip"
                print("skip")
            else:
                # --- select remark + generate request ------------------------
                try:
                    time.sleep(1)
                    page.select_option(
                        "div:has(p:has-text('Select Remark')) select.form-select",
                        value="1",  # Please release the student…
                        timeout=10_000  # waits until enabled
                    )
                except TimeoutError:
                    print("   ↳ Remark dropdown never became enabled; skipping")
                    df.at[orig_idx, "release_status"] = "Skip (remark disabled)"
                    continue

                page.click(GEN_REQ_BTN)
                status = handle_popup(page)
                df.at[orig_idx, "release_status"] = status
                print(status)
        except Exception as e:
            df.at[orig_idx, "release_status"] = f"Error: {str(e)[:40]}"
            print("ERR", e)

        processed += 1
        if processed % 20 == 0:
            df.to_excel(out_xlsx, index=False)
            print("  (checkpoint saved)")
        page.wait_for_timeout(250)

    df.to_excel(out_xlsx, index=False)
    print(f"✔ Done. Saved → {out_xlsx}")
    safe_close(browser, pw)


if __name__ == "__main__":
    get_student_school_request()
