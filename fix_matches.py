import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import argparse

# Mapping of 3-letter EPFO office codes to district names
office_code_to_district = {
    "ASR": "AMRITSAR", "LDH": "LUDHIANA", "JAL": "JALANDHAR", "BTI": "BHATINDA", "CHD": "CHANDIGARH",
    "HYD": "HYDERABAD", "PTC": "PATANCHERU", "KKP": "KUKATPALLI", "BNG": "BANGALORE", "MRD": "MAHADEVAPURA",
    "BLR": "BOMMASANDRA", "GLB": "GULBARGA", "HBL": "HUBLI", "RCH": "RAICHUR", "CKR": "CHIKMAGALUR",
    "MLR": "MANGALORE", "MYS": "MYSORE", "SHG": "SHIMOGA", "UDP": "UDUPI", "BOM": "BOMMASANDRA",
    "KRP": "K R PURAM", "PNY": "PEENYA", "BHA": "BHAGALPUR", "MUZ": "MUZAFFARPUR", "PAT": "PATNA",
    "CBE": "COIMBATORE", "SLM": "SALEM", "TRY": "TRICHY", "MDU": "MADURAI", "TNY": "TIRUNELVELI",
    "TAM": "TAMBARAM", "VLR": "VELLORE", "PDY": "PUDUCHERRY", "RAI": "RAIPUR", "CPM": "DELHI",
    "NHP": "DELHI", "SHD": "DELHI", "GOA": "GOA", "AHD": "AHMEDABAD", "NRD": "NADIAD",
    "RAJ": "RAJKOT", "VAT": "VATWA", "BRD": "BARODA", "SRT": "SURAT", "VAP": "VAPI",
    "BRH": "BHARUCH", "GGN": "GURGAON", "RTK": "ROHTAK", "CDP": "CUDDAPAH", "GNT": "GUNTUR",
    "RJY": "RAJAHMUNDRY", "VSP": "VISHAKAPATNAM", "SML": "SHIMLA", "FBD": "FARIDABAD", "KNL": "KARNAL",
    "JAM": "JAMSHEDPUR", "RAN": "RANCHI", "JMU": "JAMMU", "SRN": "SRINAGAR", "JLP": "JALPAIGURI",
    "JNG": "JANGIPUR", "SLG": "SILIGURI", "MAL": "MALAD", "NSK": "NASIK", "BAN": "BANDRA",
    "BPL": "BHOPAL", "GWL": "GWALIOR", "IND": "INDORE", "JBP": "JABALPUR", "SGR": "SAGAR",
    "UJJ": "UJJAIN", "AGR": "AGRA", "MRT": "MEERUT", "NOI": "NOIDA", "GHY": "GUWAHATI",
    "TSK": "TINSUKIA", "AKL": "AKOLA", "AUR": "AURANGABAD", "NAG": "NAGPUR", "KRN": "KARIMNAGAR",
    "NZB": "NIZAMABAD", "WGL": "WARANGAL", "BAM": "BERHAMPUR", "BBS": "BHUBANESWAR", "KJR": "KEONJHAR",
    "RKL": "ROURKELA", "KOL": "KOLHAPUR", "PUN": "PUNE", "SLP": "SOLAPUR", "JOD": "JODHPUR",
    "KOT": "KOTA", "UDR": "UDAIPUR", "THA": "THANE", "VSH": "VASHI", "AMB": "AMBATTUR",
    "MAS": "CHENNAI", "DDN": "DEHRADUN", "HLD": "HALDWANI", "ALD": "ALLAHABAD", "BLY": "BAREILLY",
    "GKP": "GORAKHPUR", "KNP": "KANPUR", "LKO": "LUCKNOW", "VNS": "VARANASI", "AND": "ANDUL",
    "CAL": "KOLKATA", "DGP": "DURGAPUR", "HLO": "HALDIA", "PRB": "BARRACKPORE", "TLO": "TITAGARH"
}

custom_office_overrides = {
    "AMBATTUR": "TN",
    "BOMMASANDRA": "KA",
    "K R PURAM (WHITEFIELD)": "KA",
    "KUKATPALLI": "TG",
    "TAMBARAM": "TN",
    "NOIDA": "UP",
    "DELHI (NORTH)": "DL",
    "DELHI (SOUTH)": "DL",
    "BANDRA(MUMBAI-I)": "MH",
    "THANE (MUMBAI-II)": "MH",
    "BARRACKPORE(TITAGARH)": "WB",
    "RAIPUR (CHATTISGARH)": "CG",
    "BHUBANESWAR": "OR",
    "BERHAMPUR": "OR",
    "ROURKELA": "OR",
    "KEONJHAR": "OR",
    "JAMSHEDPUR": "JH",
    "DURGAPUR": "WB",
    "VISHAKAPATNAM": "AP",
    "TRICHY": "TN",
    "NASIK": "MH",
    "BHATINDA": "PB",
    "GURGAON": "HR",
}

def find_state_for_office(office_name, office_state_map):
    office_name = office_name.upper().strip()
    if not office_name:
        return None
        
    if office_name in custom_office_overrides:
        return custom_office_overrides[office_name]
        
    if office_name in office_state_map:
        return office_state_map[office_name]
        
    cleaned_office = re.sub(r'\(.*\)', '', office_name).strip()
    if cleaned_office in office_state_map:
        return office_state_map[cleaned_office]
        
    if cleaned_office in custom_office_overrides:
        return custom_office_overrides[cleaned_office]
        
    for dist_name, state_code in office_state_map.items():
        if dist_name in office_name or dist_name in cleaned_office:
            return state_code
            
    for dist_name, state_code in office_state_map.items():
        if office_name in dist_name or cleaned_office in dist_name:
            return state_code
            
    return None

def get_state_from_eid_code(eid, office_state_map):
    if len(eid) >= 5:
        code = eid[2:5].upper()
        district = office_code_to_district.get(code)
        if district:
            state = find_state_for_office(district, office_state_map)
            if state:
                return state
    return None

def extract_establishment_details(file_path):
    details = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            if 'xl/worksheets/sheet1.xml' not in z.namelist():
                return []
            
            sheet_content = z.read('xl/worksheets/sheet1.xml')
            root = ET.fromstring(sheet_content)
            ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            
            rows = root.findall('.//x:row', ns)
            if not rows:
                return []
            
            est_id_col = None
            est_name_col = None
            office_name_col = None
            
            first_row = rows[0]
            cells = first_row.findall('./x:c', ns)
            for c in cells:
                col_ref = c.get('r')
                col_letter = "".join(filter(str.isalpha, col_ref))
                
                is_t = c.find('.//x:is/x:t', ns)
                val = ""
                if is_t is not None:
                    val = is_t.text or ""
                val_upper = val.strip().upper()
                
                if "ESTABLISHMENT ID" in val_upper or "ESTABLISHMENT CODE" in val_upper:
                    est_id_col = col_letter
                elif "ESTABLISHMENT NAME" in val_upper:
                    est_name_col = col_letter
                elif "OFFICE NAME" in val_upper or "OFFICE" in val_upper:
                    office_name_col = col_letter
            
            if not est_id_col:
                est_id_col = "A"
            if not est_name_col:
                est_name_col = "B"
            if not office_name_col:
                office_name_col = "D"
                
            for r in rows[1:]:
                cells = r.findall('./x:c', ns)
                row_vals = {}
                for c in cells:
                    col_ref = c.get('r')
                    col_letter = "".join(filter(str.isalpha, col_ref))
                    
                    is_t = c.find('.//x:is/x:t', ns)
                    val = ""
                    if is_t is not None:
                        val = is_t.text or ""
                    row_vals[col_letter] = val.strip()
                
                est_id = row_vals.get(est_id_col, "")
                est_name = row_vals.get(est_name_col, "")
                office = row_vals.get(office_name_col, "")
                if re.match(r'^[A-Z]{5}[0-9]{10}$', est_id):
                    details.append({
                        "establishment_id": est_id,
                        "establishment_name": est_name,
                        "office_name": office
                    })
    except Exception as e:
        # Fallback to regex
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for match in re.findall(r'\b[A-Z]{5}[0-9]{10}\b', text):
                details.append({
                    "establishment_id": match,
                    "establishment_name": "",
                    "office_name": ""
                })
        except Exception:
            pass
            
    return details

def find_downloaded_files(target_id):
    if not target_id:
        return []
    downloads_dir = "downloads"
    if not os.path.exists(downloads_dir):
        downloads_dir = os.path.join(os.getcwd(), "downloads")
        
    files = []
    if os.path.exists(downloads_dir):
        for fname in os.listdir(downloads_dir):
            if fname.startswith(target_id) and fname.endswith(".xlsx"):
                files.append(os.path.join(downloads_dir, fname))
                
    # Also check user Downloads directory
    user_home = os.path.expanduser("~")
    user_downloads = os.path.join(user_home, "Downloads")
    if os.path.exists(user_downloads):
        for fname in os.listdir(user_downloads):
            if fname.startswith(target_id) and fname.endswith(".xlsx"):
                files.append(os.path.join(user_downloads, fname))
                
    return list(set(files))

def fix_json_file(file_path, office_state_map):
    if not os.path.exists(file_path):
        print(f"[!] File not found: {file_path}")
        return False
        
    print(f"[*] Reading {file_path}...")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] Error loading JSON: {e}")
        return False
        
    fixed_count = 0
    
    for vcode, entry in data.items():
        if not isinstance(entry, dict) or entry.get("status") != "success":
            continue
            
        allowed_states = set(entry.get("allowed_state_codes", []))
        if not allowed_states:
            continue
            
        target_est_id = entry.get("target_establishment_id")
        matched_est_ids = entry.get("matched_establishment_ids", [])
        list_est_ids_existing = entry.get("list_establishment_ids", [])
        disclaimer = entry.get("disclaimer")
        
        # Determine the initial raw matched IDs as strings
        raw_matched_ids = []
        if list_est_ids_existing:
            if isinstance(list_est_ids_existing[0], dict):
                raw_matched_ids = [item.get("establishment id") for item in list_est_ids_existing if isinstance(item, dict)]
            else:
                raw_matched_ids = [str(item) for item in list_est_ids_existing]
        elif matched_est_ids:
            if isinstance(matched_est_ids[0], dict):
                raw_matched_ids = [item.get("establishment id") for item in matched_est_ids if isinstance(item, dict)]
            else:
                raw_matched_ids = [str(item) for item in matched_est_ids]
                
        # 1. Try to find the Excel files for the target establishment ID
        excel_files = find_downloaded_files(target_est_id)
        
        list_est_ids = []
        matched_est_ids_new = []
        
        if excel_files:
            all_details = []
            for f_path in excel_files:
                details = extract_establishment_details(f_path)
                all_details.extend(details)
                
            seen_ids = set()
            unique_details = []
            for d in all_details:
                eid = d["establishment_id"]
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    unique_details.append(d)
                    
            for d in unique_details:
                list_est_ids.append({
                    "establishment Name": d["establishment_name"],
                    "establishment id": d["establishment_id"]
                })
                
            prefix_matches = []
            office_matches = []
            for d in unique_details:
                eid = d["establishment_id"]
                office = d["office_name"]
                prefix = eid[:2].upper()
                office_state = find_state_for_office(office, office_state_map)
                
                item = {
                    "establishment Name": d["establishment_name"],
                    "establishment id": eid
                }
                if prefix in allowed_states:
                    prefix_matches.append((eid, item))
                elif office_state in allowed_states:
                    office_matches.append((eid, item))
                    
            if prefix_matches:
                target_est_id = prefix_matches[0][0]
                disclaimer = None
                matched_est_ids_new = [item for _, item in prefix_matches] + [item for _, item in office_matches]
            elif office_matches:
                target_est_id = office_matches[0][0]
                disclaimer = None
                matched_est_ids_new = [item for _, item in office_matches]
            else:
                # No match found, fallback to first row target, empty matched list
                disclaimer = entry.get("disclaimer") or f"State code mismatch ignored (Target: {list(allowed_states)}, Found ID: {target_est_id[:2]}, Office: unknown)."
                matched_est_ids_new = []
                
        else:
            # 2. Fall back to using the matched_establishment_ids list directly
            unique_details = []
            for eid in raw_matched_ids:
                if not eid:
                    continue
                est_name = entry.get("vendor_name", "")
                code = eid[2:5].upper()
                office = office_code_to_district.get(code, "")
                unique_details.append({
                    "establishment_id": eid,
                    "establishment_name": est_name,
                    "office_name": office
                })
                
            for d in unique_details:
                list_est_ids.append({
                    "establishment Name": d["establishment_name"],
                    "establishment id": d["establishment_id"]
                })
                
            prefix_matches = []
            office_matches = []
            for d in unique_details:
                eid = d["establishment_id"]
                office = d["office_name"]
                prefix = eid[:2].upper()
                office_state = find_state_for_office(office, office_state_map)
                
                item = {
                    "establishment Name": d["establishment_name"],
                    "establishment id": eid
                }
                if prefix in allowed_states:
                    prefix_matches.append((eid, item))
                elif office_state in allowed_states:
                    office_matches.append((eid, item))
                    
            if prefix_matches:
                target_est_id = prefix_matches[0][0]
                disclaimer = None
                matched_est_ids_new = [item for _, item in prefix_matches] + [item for _, item in office_matches]
            elif office_matches:
                target_est_id = office_matches[0][0]
                disclaimer = None
                matched_est_ids_new = [item for _, item in office_matches]
            else:
                # No match found, fallback to target, empty matched list
                disclaimer = entry.get("disclaimer") or f"State code mismatch ignored (Target: {list(allowed_states)}, Found ID: {target_est_id[:2]}, Office: unknown)."
                matched_est_ids_new = []
                
        # Update the entry
        entry["target_establishment_id"] = target_est_id
        entry["list_establishment_ids"] = list_est_ids
        entry["matched_establishment_ids"] = matched_est_ids_new
        if disclaimer:
            entry["disclaimer"] = disclaimer
        elif "disclaimer" in entry:
            del entry["disclaimer"]
            
        fixed_count += 1
        
    if fixed_count > 0:
        temp_file = file_path + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, file_path)
            print(f"\n[+] Successfully upgraded & resolved {fixed_count} records in: {file_path}")
        except Exception as e:
            print(f"[!] Error saving fixed file: {e}")
            return False
    else:
        print(f"\n[*] No records processed in {file_path}.")
        
    return True

def main():
    parser = argparse.ArgumentParser(description="Upgrade & Fix EPFO mismatches in vendor_est_matches.json using district mapping")
    parser.add_argument("-i", "--input", default=None, help="Path to vendor_est_matches.json to fix")
    args = parser.parse_args()
    
    # Load districts map
    districts_file = "districts.json"
    if not os.path.exists(districts_file):
        print(f"[!] {districts_file} not found in the current directory.")
        return
        
    with open(districts_file, "r", encoding="utf-8") as f:
        districts_data = json.load(f)
        
    office_state_map = {}
    for d in districts_data.get("districts", []):
        dist_name = d.get("district", "").strip().upper()
        if dist_name:
            office_state_map[dist_name] = d.get("stateCode", "").strip().upper()
            
    # Path fallbacks
    paths_to_try = []
    if args.input:
        paths_to_try.append(args.input)
    else:
        user_home = os.path.expanduser("~")
        downloads_path = os.path.join(user_home, "Downloads", "vendor_est_matches.json")
        paths_to_try.append(downloads_path)
        paths_to_try.append("vendor_est_matches.json")
        
    fixed_any = False
    for path in paths_to_try:
        if os.path.exists(path):
            if fix_json_file(path, office_state_map):
                fixed_any = True
                
    if not fixed_any:
        print("[!] No files were successfully processed.")

if __name__ == "__main__":
    main()
