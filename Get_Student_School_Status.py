# get_school_by_pen.py
# ---------------------------------------------
"""Lookup School Name in UDISE+ Import Module using already-fetched PEN + DOB.
   If Current School Name is 'UN-TAGGED', auto-import to this school
   using Section + Admission Date from Excel (ddlSection, TxtDateOfAddmission).
"""

import os
import time
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError
from core.browser_utils import safe_close, PAGE_TIMEOUT
from core.navigation_pen import login_and_land



def wait_for_student_refresh(page, pen: str, stud_name: str = "", timeout=15_000):
    """
    Wait until the page finishes loading the requested student.
    We treat the load as done when the body text contains the new PEN
    (preferred) or, if that never shows, when it contains the student name.
    """
    expr = """
    (args) => {
        const body = document.body ? document.body.innerText : '';
        if (!body) return false;
        if (args.pen && body.includes(args.pen)) return true;
        if (args.name && body.includes(args.name)) return true;
        return false;
    }"""
    try:
        page.wait_for_function(expr, arg={"pen": pen, "name": stud_name}, timeout=timeout)
    except TimeoutError:
        # fallthrough—best effort; caller will still try to read
        pass
    # small settle for DOM paints
    page.wait_for_timeout(500)

# ---------- date helpers ----------

def normalize_ddmmyyyy(value):
    """Return DD/MM/YYYY from mixed inputs; None if can't parse."""
    if pd.isna(value):
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    s = str(value).strip()
    if len(s) == 10 and s[2] == "/" and s[5] == "/":  # already good
        return s
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return None


# ---------- selectors ----------
# Top search inputs
PEN_INPUT_LOC = "ul.SerachBoxus input.mat-mdc-input-element"
DOB_INPUT_LOC = "ul.SerachBoxus input.mat-mdc-input-element"
GO_BTN_LOC    = "ul.SerachBoxus button:has-text('Go')"

# Current + previous school name spans (we'll take first)
SCHOOL_NAME_LOC = "li:has(> span.titleUser:has-text('School Name')) span.userValue"

# Import panel (shown only when student is UN-TAGGED)
IMPORT_SECTION_SEL = "ul.existingSchool1 li:has(label:has-text('Import Section')) select"
IMPORT_DATE_SEL    = "ul.existingSchool1 li:has(label:has-text('Date of Admission')) input"
IMPORT_BTN_SEL     = "ul.existingSchool1 button:has-text('IMPORT')"


# ---------- SweetAlert helper ----------

def handle_import_popups(page,
                         confirm_timeout=15_000,
                         success_timeout=10_000,
                         settle_ms=300):
    """
    Handle the two-step SweetAlert sequence after clicking IMPORT:

    1) Confirm dialog:  Cancel (red, class=swal2-confirm) + Confirm (blue, class=swal2-cancel).
       We must click the *Confirm* button (blue).
    2) Success dialog:  'Okay' (class=swal2-confirm). Click to dismiss.

    Returns True if we clicked Confirm (i.e., attempted import), else False.
    """

    # --- wait for confirm popup ---
    try:
        page.wait_for_selector("div.swal2-popup.swal2-show", timeout=confirm_timeout)
    except TimeoutError:
        return False

    # scope to the currently visible popup
    popup = page.locator("div.swal2-popup.swal2-show").last

    # find buttons in confirm popup
    btns = popup.locator("button.swal2-styled")
    clicked_confirm = False

    # try explicit text match first (more robust than class)
    for label in ("Confirm", "Yes", "OK", "Okey", "Okay"):
        loc = popup.locator(f"button.swal2-styled:has-text('{label}')")
        if loc.count():
            try:
                loc.click()
                clicked_confirm = True
                break
            except Exception:
                pass

    if not clicked_confirm:
        # known class inversion: blue Confirm carries class swal2-cancel
        if popup.locator("button.swal2-cancel").count():
            try:
                popup.locator("button.swal2-cancel").click()
                clicked_confirm = True
            except Exception:
                pass

    if not clicked_confirm:
        # fallback: click the *last* styled button (visually Confirm in your screenshots)
        try:
            btns.last.click()
            clicked_confirm = True
        except Exception:
            pass

    # give the request a beat to fire
    page.wait_for_timeout(settle_ms)

    # --- wait for success popup (best-effort) ---
    if clicked_confirm:
        try:
            page.wait_for_selector("div.swal2-popup.swal2-icon-success.swal2-show",
                                   timeout=success_timeout)
            success_pop = page.locator("div.swal2-popup.swal2-icon-success.swal2-show").last

            # buttons: Usually only 'Okay' (swal2-confirm)
            ok_clicked = False
            for label in ("Okay", "Ok", "Okey", "Close"):
                loc = success_pop.locator(f"button.swal2-styled:has-text('{label}')")
                if loc.count():
                    try:
                        loc.click()
                        ok_clicked = True
                        break
                    except Exception:
                        pass

            if not ok_clicked and success_pop.locator("button.swal2-confirm").count():
                try:
                    success_pop.locator("button.swal2-confirm").click()
                except Exception:
                    pass

            # wait for it to vanish (don’t block too long)
            try:
                page.wait_for_selector("div.swal2-popup.swal2-icon-success.swal2-show",
                                       state="detached", timeout=5_000)
            except TimeoutError:
                pass

        except TimeoutError:
            # no success popup? ignore
            pass

    return clicked_confirm

# ---------- main ----------
def get_school_by_pen(
    in_xlsx="students_extracted_with_PEN.xlsx",
    out_xlsx="students_extracted_with_PEN_school.xlsx",
):
    load_dotenv()
    user, pwd = os.getenv("SSG_USER"), os.getenv("SSG_PASS")
    if not (user and pwd):
        raise SystemExit("Set SSG_USER & SSG_PASS in .env")

    # Load data
    df = pd.read_excel(in_xlsx)

    # Ensure required cols
    if "student_pen" not in df.columns:
        raise SystemExit(f"Input file {in_xlsx} missing required column 'student_pen'.")
    if "school_name" not in df.columns:
        df["school_name"] = ""
    if "import_status" not in df.columns:
        df["import_status"] = ""  # OK / Skipped / Error
    if "ddlSection" not in df.columns:
        df["ddlSection"] = ""     # fallback
    if "TxtDateOfAddmission" not in df.columns:  # note user spelled Addmission
        df["TxtDateOfAddmission"] = ""

    # Filter: only rows with usable PEN
    bad_markers = {"Wrong Aadhaar/YOB", "Bad DOB", "No Aadhaar", "", None, pd.NA}
    eligible_idx = []
    for i, pen in enumerate(df["student_pen"]):
        p = str(pen).strip() if not pd.isna(pen) else ""
        if p and p not in bad_markers and not p.startswith("Error"):
            eligible_idx.append(i)

    print(f"→ {len(eligible_idx)} students eligible for school lookup.")

    pw = browser = page = None
    found_schl = not_found_schl = imported_cnt = import_fail = 0

    try:
        pw, browser, page = login_and_land(user, pwd)  # lands on Import Module search page
        print("✓ Landed on Import Module Go page.")

        for n, idx in enumerate(eligible_idx, start=1):
            pen = str(df.at[idx, "student_pen"]).strip()
            raw_dob = df.at[idx, "TxtDateOfBirth"] if "TxtDateOfBirth" in df.columns else ""
            dob = normalize_ddmmyyyy(raw_dob)
            stud_name = str(df.at[idx, "TxtStudName"]) if "TxtStudName" in df.columns else pen

            if dob is None:
                df.at[idx, "school_name"] = "DOB Parse Fail"
                df.at[idx, "import_status"] = "Skipped (DOB)"
                print(f"✗ [{n}] {stud_name} → bad DOB ({raw_dob})")
                not_found_schl += 1
                continue

            print(f"→ [{n}/{len(eligible_idx)}] {stud_name} (PEN {pen}) …", end="")

            try:
                # Locate PEN & DOB inputs fresh each loop to avoid stale handles
                pen_input = page.locator(PEN_INPUT_LOC).nth(0)
                dob_input = page.locator(DOB_INPUT_LOC).nth(1)

                # fill
                pen_input.scroll_into_view_if_needed()
                pen_input.click()
                pen_input.fill("")
                pen_input.fill(pen)

                dob_input.click()
                dob_input.fill("")
                dob_input.fill(dob)

                # submit
                page.click(GO_BTN_LOC)
                wait_for_student_refresh(page, pen, stud_name)

                # wait for school name(s) or popup
                try:
                    page.wait_for_selector(SCHOOL_NAME_LOC, timeout=10_000)
                    school_locator = page.locator(SCHOOL_NAME_LOC)
                    count = school_locator.count()
                    current_school = school_locator.first.inner_text().strip()
                    prev_school = school_locator.nth(1).inner_text().strip() if count > 1 else ""

                    df.at[idx, "school_name"] = current_school
                    if prev_school:
                        col = "prev_school_name"
                        if col not in df.columns:
                            df[col] = ""
                        df.at[idx, col] = prev_school

                    found_schl += 1
                    print(f" {current_school}")

                    # ---------- Auto-import when UN-TAGGED ----------
                    if current_school.replace(" ", "").upper() == "UN-TAGGED":
                        # Which section to import?
                        sec_letter_raw = str(df.at[idx, "ddlSection"]).strip().upper()
                        sec_letter = ""
                        if sec_letter_raw.startswith("A"): sec_letter = "A"
                        elif sec_letter_raw.startswith("B"): sec_letter = "B"
                        # Map letter -> value in dropdown
                        sec_val = "1" if sec_letter == "A" else "2" if sec_letter == "B" else "-1"

                        adm_raw = df.at[idx, "TxtDateOfAddmission"]
                        adm_date = normalize_ddmmyyyy(adm_raw) or dob  # fallback to DOB if blank

                        if sec_val in ("1","2"):
                            try:
                                # select section
                                page.wait_for_selector(IMPORT_SECTION_SEL, timeout=5_000)
                                page.select_option(IMPORT_SECTION_SEL, value=sec_val)

                                # date of admission
                                if adm_date:
                                    page.fill(IMPORT_DATE_SEL, "")
                                    page.fill(IMPORT_DATE_SEL, adm_date)

                                page.click(IMPORT_BTN_SEL)

                                # 2‑step SweetAlert (Confirm -> Okay)
                                confirmed = handle_import_popups(page)
                                if not confirmed:
                                    print("   ↳ WARN: import confirm popup not detected.")

                                df.at[idx, "import_status"] = f"Imported ({sec_letter}/{adm_date})"
                                imported_cnt += 1
                                print(f"   ↳ Imported section {sec_letter} on {adm_date}")
                            except Exception as imp_err:
                                df.at[idx, "import_status"] = f"Import FAIL: {imp_err}"
                                import_fail += 1
                                print(f"   ↳ IMPORT ERROR: {imp_err}")
                        else:
                            df.at[idx, "import_status"] = "Skipped (no section)"
                            print("   ↳ Import skipped: no ddlSection in file")

                    else:
                        df.at[idx, "import_status"] = "No Import (tagged)"

                except TimeoutError:
                    # see if there's an error popup
                    if page.is_visible("div.swal2-popup"):
                        click_any_swal_confirm(page)
                    df.at[idx, "school_name"] = "Not Found"
                    df.at[idx, "import_status"] = "Skipped (no school)"
                    not_found_schl += 1
                    print(" NOT FOUND")

            except Exception as e:
                df.at[idx, "school_name"] = f"Error: {str(e)[:30]}"
                df.at[idx, "import_status"] = f"Error: {str(e)[:30]}"
                not_found_schl += 1
                print(f" ERROR ({e})")

            # Friendly pacing
            page.wait_for_timeout(250)

            # Checkpoint autosave
            if n % 25 == 0:
                df.to_excel(out_xlsx, index=False)
                print(f"   (checkpoint saved @ {n})")

    finally:
        # Always persist
        try:
            df.to_excel(out_xlsx, index=False)
        except Exception as e:
            print(f"⚠ could not write {out_xlsx}: {e}")
        safe_close(browser, pw)
        print("\n–––– SCHOOL LOOKUP + IMPORT SUMMARY ––––")
        print(f"school found: {found_schl} | not found/error: {not_found_schl}")
        print(f"imported: {imported_cnt} | import fail: {import_fail}")
        print(f"Saved → {out_xlsx}")


if __name__ == "__main__":
    get_school_by_pen()
