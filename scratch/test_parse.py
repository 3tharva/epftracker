import os
import openpyxl.reader.excel
openpyxl.reader.excel.apply_stylesheet = lambda archive, wb: None
import pandas as pd

def parse_wage_month(month_str):
    if not isinstance(month_str, str):
        return None
    parts = month_str.strip().split('-')
    if len(parts) != 2:
        return None
    month_name, year_str = parts[0].upper(), parts[1]
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    if month_name not in months:
        return None
    month_num = months.index(month_name) + 1
    try:
        if len(year_str) == 2:
            year = 2000 + int(year_str)
        elif len(year_str) == 4:
            year = int(year_str)
        else:
            return None
    except ValueError:
        return None
    return (year, month_num)

def get_latest_payment_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        df = pd.read_excel(file_path)
        cols = {c.strip().lower(): c for c in df.columns}
        wage_month_col = next((cols[c] for c in ['wage month', 'wagemonth', 'month'] if c in cols), None)
        amount_col = next((cols[c] for c in ['amount', 'amt', 'total amount'] if c in cols), None)
        emp_col = next((cols[c] for c in ['no. of employee', 'no. of employees', 'employee count', 'employees', 'no_of_employee', 'no_of_employees'] if c in cols), None)
        
        if not wage_month_col:
            return None
            
        best_row = None
        best_date = None
        
        for idx, row in df.iterrows():
            wm_val = str(row[wage_month_col]).strip()
            parsed = parse_wage_month(wm_val)
            if parsed:
                if not best_date or parsed > best_date:
                    best_date = parsed
                    best_row = row
                    
        if best_row is not None:
            amt_val = best_row[amount_col] if amount_col is not None else None
            emp_val = best_row[emp_col] if emp_col is not None else None
            
            try:
                if pd.isna(amt_val):
                    amt_val = None
                elif isinstance(amt_val, float):
                    amt_val = round(amt_val, 2)
                else:
                    amt_val = int(amt_val)
            except Exception:
                pass
                
            try:
                if pd.isna(emp_val):
                    emp_val = None
                else:
                    emp_val = int(emp_val)
            except Exception:
                pass
                
            return {
                "wage_month": str(best_row[wage_month_col]).strip(),
                "amount": amt_val,
                "employees": emp_val
            }
    except Exception as e:
        print(f"Error: {e}")
    return None

print(get_latest_payment_info(r'downloads/0000231635/AMAN_ELECTRICALS_MRMRT1527249000_payment_details.xlsx'))
