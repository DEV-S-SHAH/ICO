import os
import re
import json
from pathlib import Path
from bs4 import BeautifulSoup

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")

SECTIONS = {
    "Item 1": re.compile(r"(?i)\n\s*item\s+1(?:\.|—|-|:|\s)*\s*business\b", re.IGNORECASE),
    "Item 1A": re.compile(r"(?i)\n\s*item\s+1a(?:\.|—|-|:|\s)*\s*risk\s+factors\b", re.IGNORECASE),
    "Item 7": re.compile(r"(?i)\n\s*item\s+7(?:\.|—|-|:|\s)*\s*management(?:'|’)?s\s+discussion\s+and\s+analysis\b", re.IGNORECASE),
    "Part I Item 2": re.compile(r"(?i)\n\s*item\s+2(?:\.|—|-|:|\s)*\s*management(?:'|’)?s\s+discussion\s+and\s+analysis\b", re.IGNORECASE),
    "Part II Item 1A": re.compile(r"(?i)\n\s*item\s+1a(?:\.|—|-|:|\s)*\s*risk\s+factors\b", re.IGNORECASE)
}

NEXT_SECTIONS = {
    "Item 1": re.compile(r"(?i)\n\s*item\s+1a(?:\.|—|-|:|\s)*\s*risk\s+factors\b", re.IGNORECASE),
    "Item 1A": re.compile(r"(?i)\n\s*item\s+1b(?:\.|—|-|:|\s)*\s*unresolved\b|\n\s*item\s+1c(?:\.|—|-|:|\s)*\s*cybersecurity\b|\n\s*item\s+2(?:\.|—|-|:|\s)*\s*properties\b", re.IGNORECASE),
    "Item 7": re.compile(r"(?i)\n\s*item\s+7a(?:\.|—|-|:|\s)*\s*quantitative\b|\n\s*item\s+8(?:\.|—|-|:|\s)*\s*financial\s+statements\b", re.IGNORECASE),
    "Part I Item 2": re.compile(r"(?i)\n\s*item\s+3(?:\.|—|-|:|\s)*\s*quantitative\b|\n\s*item\s+4(?:\.|—|-|:|\s)*\s*controls\b|\n\s*part\s+ii\b", re.IGNORECASE),
    "Part II Item 1A": re.compile(r"(?i)\n\s*item\s+2(?:\.|—|-|:|\s)*\s*unregistered\b|\n\s*item\s+3(?:\.|—|-|:|\s)*\s*defaults\b|\n\s*item\s+4(?:\.|—|-|:|\s)*\s*mine\b|\n\s*item\s+5(?:\.|—|-|:|\s)*\s*other\b|\n\s*item\s+6(?:\.|—|-|:|\s)*\s*exhibits\b", re.IGNORECASE)
}

def clean_html(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    soup = BeautifulSoup(content, "lxml")
    text = soup.get_text(separator="\n")
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text

def extract_sections(text, form_type, ticker=""):
    extracted = {}
    

    if ticker == "WMT" and form_type == "10-K":
        m_i1 = re.search(r"ITEM\s*1\.\s*BUSINESS\nGeneral\nWalmart Inc", text[30000:], flags=re.IGNORECASE)
        m_i1a = re.search(r"ITEM\s*1A\.\s*RISK FACTORS\nThe risks described", text[30000:], flags=re.IGNORECASE)
        m_i1b = re.search(r"ITEM\s*1B\.\s*UNRESOLVED", text[30000:], flags=re.IGNORECASE)
        
        if m_i1 and m_i1a and m_i1b:
            i1_start = 30000 + m_i1.start()
            i1a_start = 30000 + m_i1a.start()
            i1b_start = 30000 + m_i1b.start()
            extracted["Item 1"] = text[i1_start:i1a_start].strip()
            extracted["Item 1A"] = text[i1a_start:i1b_start].strip()
            return extracted

    if ticker == "MSFT" and form_type == "10-K":
        m_i1 = re.search(r"Note About Forward-Looking Statements", text[30000:])
        m_i1a = re.search(r"ITEM 1A\.\s*RIS(?:K|\nK)\s*FACTORS", text[30000:])
        m_i1b = re.search(r"ITEM 1B\.\s*UNRESOLVE", text[30000:])
        
        if m_i1 and m_i1a and m_i1b:
            i1_start = 30000 + m_i1.start()
            i1a_start = 30000 + m_i1a.start()
            i1b_start = 30000 + m_i1b.start()
            extracted["Item 1"] = text[i1_start:i1a_start].strip()
            extracted["Item 1A"] = text[i1a_start:i1b_start].strip()
            return extracted
            
    if ticker == "COST" and form_type == "10-K":
        m_i1 = re.search(r"(?i)Item\s*1\s*[-—]\s*Business", text[18000:])
        m_i1a = re.search(r"(?i)Item\s*1A\s*[-—]\s*Risk\s*Factors", text[18000:])
        m_i1b = re.search(r"(?i)Item\s*1B\s*[-—]\s*Unresolved", text[18000:])
        
        if m_i1 and m_i1a and m_i1b:
            i1_start = 18000 + m_i1.start()
            i1a_start = 18000 + m_i1a.start()
            i1b_start = 18000 + m_i1b.start()
            extracted["Item 1"] = text[i1_start:i1a_start].strip()
            extracted["Item 1A"] = text[i1a_start:i1b_start].strip()
            return extracted

    if form_type == "10-K":
        targets = ["Item 1", "Item 1A", "Item 7"]
    else: 
        targets = ["Part I Item 2", "Part II Item 1A"]
        
    for target in targets:
        start_pattern = SECTIONS[target]
        end_pattern = NEXT_SECTIONS[target]
        
        starts = list(start_pattern.finditer(text))
        if not starts:
            # specifically for Item 1 missing fallback
            if target in ["Item 1", "Item 1A"]:
                alt = list(re.finditer(r"(?i)\n\s*item\s+1a?\b", text))
                if alt: starts = alt
                else: continue
            else:
                continue
        
        start_match = starts[-1] 
        start_idx = start_match.start()
        
        end_match = None
        for m in end_pattern.finditer(text, start_idx + 100):
            end_match = m
            break
            
        if end_match:
            end_idx = end_match.start()
        else:
            end_idx = start_idx + 15000  # much safer fallback
            
        extracted[target] = text[start_idx:end_idx].strip()
        
    final_sections = {}
    if form_type == "10-K":
        final_sections = extracted
    else:
        if "Part I Item 2" in extracted: final_sections["Item 7"] = extracted["Part I Item 2"]
        if "Part II Item 1A" in extracted: final_sections["Item 1A"] = extracted["Part II Item 1A"]
        
    return final_sections

def main():
    PROCESSED_DIR.mkdir(exist_ok=True)
    for raw_file in RAW_DIR.glob("*.htm"):
        print(f"Cleaning {raw_file.name}...")
        text = clean_html(raw_file)
        parts = raw_file.stem.split("_")
        ticker = parts[0]
        form_type = parts[1]
        
        sections = extract_sections(text, form_type, ticker)
        
        data = {
            "ticker": ticker,
            "form_type": form_type,
            "report_date": parts[2],
            "sections": sections
        }
        
        out_file = PROCESSED_DIR / f"{raw_file.stem}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

if __name__ == "__main__":
    main()
