import json

with open("vendor_est_matches.json", "r", encoding="utf-8") as f:
    results = json.load(f)

for code in ["352712", "611222", "0000352712", "0000611222"]:
    if code in results:
        print(f"\nRecord for {code}:")
        print(json.dumps(results[code], indent=2))
