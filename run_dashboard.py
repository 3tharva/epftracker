import http.server
import socketserver
import webbrowser
import threading
import os
import sys
import json
import re
import io
import subprocess
import time
from urllib.parse import urlparse, parse_qs
import pandas as pd

PORT = 8000

# Global reference to running scraper process
scraper_process = None

def standardize_columns(df):
    """
    Looks for vendor code, name, and GSTN columns case-insensitively and standardizes names.
    Falls back to first three columns if matching fails.
    """
    cols = {c.strip().lower(): c for c in df.columns}
    
    code_col = None
    for cand in ['vendor', 'code', 'vendor code', 'vendor_code', 'id', 'vendor_id', 'vendorcode']:
        if cand in cols:
            code_col = cols[cand]
            break
            
    name_col = None
    for cand in ['vendor name', 'vendor_name', 'name', 'establishment name', 'establishment_name', 'vendorname']:
        if cand in cols:
            name_col = cols[cand]
            break
            
    gst_col = None
    for cand in ['vendor gstn', 'vendor_gstn', 'gstn', 'gstin', 'gst', 'tax_id', 'taxid']:
        if cand in cols:
            gst_col = cols[cand]
            break
            
    if not (code_col and name_col and gst_col):
        # Fallback: rename first 3 columns
        if len(df.columns) >= 3:
            return df.rename(columns={
                df.columns[0]: 'Vendor',
                df.columns[1]: 'Vendor Name',
                df.columns[2]: 'Vendor GSTN'
            })
        raise ValueError("File must contain at least 3 columns for Vendor Code, Vendor Name, and Vendor GSTN.")
        
    return df.rename(columns={
        code_col: 'Vendor',
        name_col: 'Vendor Name',
        gst_col: 'Vendor GSTN'
    })

def get_status_details():
    """
    Aggregates scraper status, progress bar counts, active vendor logs, and log stream.
    """
    global scraper_process
    running = scraper_process is not None and scraper_process.poll() is None
    
    total_vendors = 0
    vendors_preview = []
    filename = "None"
    
    # Read last uploaded filename if cached
    if os.path.exists("last_uploaded_filename.txt"):
        try:
            with open("last_uploaded_filename.txt", "r", encoding="utf-8") as fn_file:
                filename = fn_file.read().strip()
        except Exception:
            pass
            
    # Only load vendor counts and list if a recorded upload session exists
    if filename != "None":
        for fname in ["vendorList_cleaned.csv", "vendorList.csv"]:
            if os.path.exists(fname):
                try:
                    df = pd.read_csv(fname, dtype=str)
                    df = df.fillna("")
                    total_vendors = len(df)
                    # Keep preview of top 5
                    vendors_preview = df.head(5).to_dict(orient="records")
                    break
                except Exception:
                    pass
                
    processed_count = 0
    success_count = 0
    mismatch_count = 0
    nomatch_count = 0
    error_count = 0
    
    if os.path.exists("vendor_est_matches.json"):
        try:
            with open("vendor_est_matches.json", "r", encoding="utf-8") as f:
                results = json.load(f)
            processed_count = len(results)
            for v in results.values():
                status = v.get("status")
                if status == "success":
                    # Replicate dashboard mismatch logic: mismatch if target prefix != allowed prefix AND total search results >= 3
                    allowed = v.get("allowed_state_codes", [])
                    target = v.get("target_establishment_id")
                    list_est = v.get("list_establishment_ids", [])
                    if target:
                        is_match = any(target.startswith(s.upper()) for s in allowed)
                        if is_match or len(list_est) < 3:
                            success_count += 1
                        else:
                            mismatch_count += 1
                    else:
                        mismatch_count += 1
                elif status == "no_match_found":
                    nomatch_count += 1
                else:
                    error_count += 1
        except Exception:
            pass
            
    # Read console output logs
    log_tail = ""
    active_vendor = "Idle"
    if os.path.exists("scraper_run.log"):
        try:
            with open("scraper_run.log", "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            log_tail = "".join(lines[-100:])  # Grab last 100 log lines
            
            # Search backwards for active vendor signature
            for line in reversed(lines):
                match = re.search(r'========== Processing Vendor (\d+) \(Code: (\w+)\) ==========', line)
                if match:
                    active_vendor = f"Processing Vendor #{match.group(1)} (Code: {match.group(2)})"
                    # Match name line printed directly after
                    idx = lines.index(line)
                    if idx + 1 < len(lines) and "Vendor Name:" in lines[idx+1]:
                        name_match = re.search(r'Vendor Name:\s*(.*?)\s*\|', lines[idx+1])
                        if name_match:
                            active_vendor += f" - {name_match.group(1)}"
                    break
        except Exception:
            pass
            
    if running and active_vendor == "Idle":
        active_vendor = "Starting Playwright browser and crawler context..."
    elif not running and processed_count > 0:
        if processed_count >= total_vendors and total_vendors > 0:
            active_vendor = "Completed successfully!"
        else:
            active_vendor = "Stopped / Interrupted"
            
    return {
        "running": running,
        "active_vendor": active_vendor,
        "total_count": total_vendors,
        "filename": filename,
        "processed_count": processed_count,
        "success_count": success_count,
        "mismatch_count": mismatch_count,
        "nomatch_count": nomatch_count,
        "error_count": error_count,
        "log_tail": log_tail,
        "vendors_preview": vendors_preview
    }


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Disable caching and enable CORS to prevent browser state issues
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_POST(self):
        global scraper_process
        parsed_url = urlparse(self.path)
        
        # 1. POST /api/upload - Handle Excel/CSV file upload
        if parsed_url.path == '/api/upload':
            try:
                query = parse_qs(parsed_url.query)
                filename = query.get('filename', ['vendorList.xlsx'])[0]
                
                content_length = int(self.headers.get('Content-Length', 0))
                file_bytes = self.rfile.read(content_length)
                
                save_path = "vendorList.xlsx" if filename.endswith('.xlsx') else "vendorList.csv"
                with open(save_path, "wb") as f:
                    f.write(file_bytes)
                
                # Convert spreadsheet to standard CSV if needed
                if save_path.endswith('.xlsx'):
                    df = pd.read_excel(save_path, dtype=str)
                    df = standardize_columns(df)
                    df = df.fillna("")
                    df.to_csv("vendorList.csv", index=False)
                else:
                    df = pd.read_csv(save_path, dtype=str)
                    df = standardize_columns(df)
                    df = df.fillna("")
                    df.to_csv("vendorList.csv", index=False)
                
                # Save filename to a cache file
                try:
                    with open("last_uploaded_filename.txt", "w", encoding="utf-8") as fn_file:
                        fn_file.write(filename)
                except Exception:
                    pass
                
                # Clean up existing status logs to avoid confusion
                if os.path.exists("scraper_run.log"):
                    try: os.remove("scraper_run.log")
                    except Exception: pass
                if os.path.exists("vendorList_cleaned.csv"):
                    try: os.remove("vendorList_cleaned.csv")
                    except Exception: pass
                
                response_data = {
                    "status": "success",
                    "filename": filename,
                    "count": len(df),
                    "columns": list(df.columns),
                    "preview": df.head(5).to_dict(orient="records")
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
            
        # 2. POST /api/start - Start scraper subprocess
        elif parsed_url.path == '/api/start':
            if scraper_process and scraper_process.poll() is None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Scraper is already running."}).encode())
                return
                
            try:
                # Read start configs from request headers
                headless_str = self.headers.get('X-Headless', 'true')
                sleep_val = self.headers.get('X-Sleep', '10')
                api_key = self.headers.get('X-Api-Key', '')
                
                cmd = [sys.executable, "vendor_scraper.py", "-i", "vendorList.csv", "--sleep", sleep_val]
                if headless_str.lower() == 'true':
                    cmd.append("--headless")
                if api_key:
                    cmd.extend(["-k", api_key])
                
                print(f"[*] Starting scraper subprocess: {' '.join(cmd)}")
                
                # Truncate old run log
                log_file = open("scraper_run.log", "w", encoding="utf-8")
                
                scraper_process = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True
                )
                log_file.close()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "started", "pid": scraper_process.pid}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        # 3. POST /api/stop - Terminate scraper process
        elif parsed_url.path == '/api/stop':
            if not scraper_process or scraper_process.poll() is not None:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Scraper is not running."}).encode())
                return
                
            try:
                print(f"[*] Terminating scraper subprocess (PID: {scraper_process.pid})...")
                scraper_process.terminate()
                
                # Wait up to 5 seconds for clean exit
                for _ in range(10):
                    if scraper_process.poll() is not None:
                        break
                    time.sleep(0.5)
                    
                if scraper_process.poll() is None:
                    print("[!] Force killing scraper subprocess...")
                    scraper_process.kill()
                    scraper_process.wait()
                
                # Append stop notice to log
                with open("scraper_run.log", "a", encoding="utf-8") as f:
                    f.write("\n[!] Execution stopped manually by the user via Dashboard.\n")
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "stopped"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        # 4. POST /api/upload_matches - Handle matches JSON file upload
        elif parsed_url.path == '/api/upload_matches':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                file_bytes = self.rfile.read(content_length)
                
                # Verify that it is valid JSON
                data = json.loads(file_bytes.decode('utf-8'))
                
                # Save to vendor_est_matches.json
                with open("vendor_est_matches.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                    
                response_data = {
                    "status": "success",
                    "filename": "vendor_est_matches.json",
                    "count": len(data)
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
            
        super().do_POST()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        # 1. GET /api/status - Fetch current progress
        if parsed_url.path == '/api/status':
            try:
                status = get_status_details()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(status).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
            
        # 2. GET /api/files - List workspace outputs & sheets
        elif parsed_url.path == '/api/files':
            try:
                file_list = []
                # Check output directories
                for root_file in ["vendorList.xlsx", "vendorList.csv", "vendorList_cleaned.csv", "vendor_est_matches.json"]:
                    if os.path.exists(root_file):
                        stat = os.stat(root_file)
                        file_list.append({
                            "name": root_file,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime
                        })
                # Check worksheets downloads
                if os.path.exists("downloads"):
                    for fname in os.listdir("downloads"):
                        fpath = os.path.join("downloads", fname)
                        if os.path.isfile(fpath):
                            stat = os.stat(fpath)
                            file_list.append({
                                "name": f"downloads/{fname}",
                                "size": stat.st_size,
                                "mtime": stat.st_mtime
                            })
                            
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(file_list).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
            
        super().do_GET()


def run_server(port):
    handler = DashboardHandler
    socketserver.ThreadingTCPServer.allow_reuse_address = False
    httpd = None
    
    # Port finding loop
    while port < 8080:
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
            break
        except OSError as e:
            print(f"[-] Port {port} is busy ({e}). Trying port {port+1}...")
            port += 1
            
    if not httpd:
        print("[!] Could not find any free port to bind the server.")
        sys.exit(1)
        
    url = f"http://127.0.0.1:{port}/dashboard.html"
    print(f"\n[+] Local dashboard server started at: {url}")
    print("[*] Press Ctrl+C in this terminal to stop the server.")
    
    # Open browser in a thread after server is up
    def open_browser():
        try:
            time.sleep(0.5)
            webbrowser.open(url)
        except Exception as e:
            print(f"[!] Could not automatically open browser: {e}")
            
    threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Clean up active subprocesses on exit
        global scraper_process
        if scraper_process and scraper_process.poll() is None:
            print("\n[!] Stopping active scraper subprocess on server shutdown...")
            scraper_process.terminate()
            scraper_process.wait()
        print("\n[!] Stopping server...")
        sys.exit(0)
    finally:
        httpd.server_close()

if __name__ == "__main__":
    # Ensure working directory is the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"[*] Serving files from: {script_dir}")
    run_server(PORT)
