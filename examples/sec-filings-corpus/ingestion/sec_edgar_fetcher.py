import os
import json
import time
import requests
from pathlib import Path

# SEC User-Agent requirement: "Sample Company Name AdminContact@<sample company domain>.com"
HEADERS = {
    "User-Agent": "ICO-Agent-Project devshah16@gmail.com",
    "Accept-Encoding": "gzip, deflate"
}

COMPANIES = {
    "Tech": {"AAPL": "0000320193", "MSFT": "0000789019", "GOOGL": "0001652044"},
    "Finance": {"JPM": "0000019617", "GS": "0000886982", "BAC": "0000070858"},
    "Retail": {"WMT": "0000104169", "TGT": "0000027419", "COST": "0000909832"},
    "Healthcare": {"JNJ": "0000200406", "PFE": "0000078003", "UNH": "0000731766"}
}

RAW_DIR = Path("data/raw")

def fetch_filings():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    for sector, companies in COMPANIES.items():
        for ticker, cik in companies.items():
            print(f"Fetching data for {ticker} ({cik})...")
            
            # Fetch submissions
            submissions_url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
            try:
                resp = requests.get(submissions_url, headers=HEADERS)
                if resp.status_code != 200:
                    print(f"Failed to fetch {ticker}: {resp.status_code} {resp.text}")
                    time.sleep(0.5)
                    continue
            except Exception as e:
                print(f"Error fetching submissions for {ticker}: {e}")
                time.sleep(0.5)
                continue

            data = resp.json()
            filings = data.get("filings", {}).get("recent", {})
            if not filings:
                print(f"No recent filings found for {ticker}")
                continue
            
            # We want the latest 10-K and latest 10-Q
            fetched_10k = False
            fetched_10q = False
            
            for i in range(len(filings.get("form", []))):
                form_type = filings["form"][i]
                if form_type in ["10-K", "10-Q"]:
                    if form_type == "10-K" and fetched_10k:
                        continue
                    if form_type == "10-Q" and fetched_10q:
                        continue
                    
                    accession = filings["accessionNumber"][i]
                    primary_doc = filings["primaryDocument"][i]
                    report_date = filings["reportDate"][i]
                    
                    if not primary_doc:
                        continue
                        
                    acc_no_dash = accession.replace("-", "")
                    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dash}/{primary_doc}"
                    
                    print(f"  -> Downloading {form_type} from {report_date}")
                    doc_resp = requests.get(doc_url, headers=HEADERS)
                    if doc_resp.status_code == 200:
                        file_ext = primary_doc.split(".")[-1]
                        filename = f"{ticker}_{form_type}_{report_date}.{file_ext}"
                        filepath = RAW_DIR / filename
                        with open(filepath, "wb") as f:
                            f.write(doc_resp.content)
                        
                        if form_type == "10-K":
                            fetched_10k = True
                        if form_type == "10-Q":
                            fetched_10q = True
                            
                    time.sleep(0.15) # SEC rate limit is 10 requests/second
                
                if fetched_10k and fetched_10q:
                    break
                    
            time.sleep(0.15)
            
if __name__ == "__main__":
    fetch_filings()
