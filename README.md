# UDISE+ Student Automation Toolkit

This project automates **UDISE+ student management tasks**, saving hours of manual work on government portals.  
It’s built for **teachers, school admins, and beginners learning automation**.

---

## **What Does This Tool Do?**

We have built scripts that:
1. **Extract student status** (Pending/Done) from the UDISE+ portal.  
2. **Update pending students** – automatically mark them as passed and assign class/section.  
3. **Fetch PEN (Permanent Education Number)** for students using Aadhaar and Date of Birth.  
4. **Check and update student school status** – move untagged students to your school.

---

## **Files Overview**

- **`main_extractor.py`**  
  Extracts the current status of all students (Pending/Done) and saves it in Excel for review.

- **`Update_Pending.py`**  
  Automatically updates all students marked as "Pending" by:
  - Assigning progression status.
  - Setting marks (random 75-85%).
  - Updating days attended (240-249).
  - Moving them to the correct class/section.

- **`Get_Pen.py`**  
  Looks up each student’s **PEN** using Aadhaar number and Year of Birth (from `students_extracted.xlsx`).

- **`Get_Student_School_Status.py`**  
  After `Get_Pen.py` is run, this script:
  - Fetches the **current school** of each student.
  - If the student is "UN-TAGGED" (not assigned to a school), it automatically adds them to your school with admission date and section.

---

## **How to Use**

1. **Prepare Your Excel File**  
   - Update `students_extracted.xlsx` with student details (Aadhaar, DOB, etc.).

2. **Run `main_extractor.py`**  
   - Generates a list of students and their status.

3. **Run `Update_Pending.py`**  
   - Updates all students marked as "Pending".

4. **Run `Get_Pen.py`**  
   - Fetches each student’s PEN and updates the Excel sheet.

5. **Run `Get_Student_School_Status.py`**  
   - Verifies current school.
   - Imports any "untagged" students into your school automatically.

---

## **Who Is This For?**

- **Teachers and school admins** – to avoid hours of manual data entry on glitchy portals.  
- **Beginners learning automation** – to see real-world Playwright & Python scripts in action.

---

## **Tech Behind It**

- **Python 3.10+**
- **Playwright** (for browser automation)
- **Pandas** (for Excel handling)
- **Dotenv** (for secure credentials)
- **Excel Input/Output** for simplicity.

---

## **Future Scope**
- Adding a **GUI interface** for teachers (no coding required).
- Auto-handling **CAPTCHA** with AI support.
- Centralized logging and error reporting.

---

## **Disclaimer**
This tool is for **educational purposes** and to help teachers manage UDISE+ data faster.  
Please use it responsibly as per official guidelines.
