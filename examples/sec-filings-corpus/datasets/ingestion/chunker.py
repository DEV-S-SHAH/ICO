import os
import json
import uuid
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter

PROCESSED_DIR = Path("datasets/processed")
CHUNKS_DIR = Path("datasets/chunks")

def main():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Approx 700 tokens, ~15% is ~105
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name="gpt-4",
        chunk_size=700,
        chunk_overlap=105,
    )
    
    all_chunks = []
    
    for filename in os.listdir(PROCESSED_DIR):
        if not filename.endswith(".json"): continue
        
        filepath = PROCESSED_DIR / filename
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        ticker = data["ticker"]
        form_type = data["form_type"]
        report_date = data["report_date"] # YYYY-MM-DD
        year = report_date.split("-")[0]
        
        month = int(report_date.split("-")[1])
        if form_type == "10-K":
            fiscal_quarter = "FY"
        else:
            fiscal_quarter = f"CQ{(month-1)//3 + 1}" # Calendar Quarter as best estimate
        
        for section, text in data.get("sections", {}).items():
            if not text: continue
            
            chunks = text_splitter.split_text(text)
            for i, chunk_text in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                metadata = {
                    "company": ticker, # using ticker as company name for simplicity
                    "ticker": ticker,
                    "filing_type": form_type,
                    "fiscal_quarter": fiscal_quarter,
                    "fiscal_year": year,
                    "section": section,
                    "chunk_index": i
                }
                
                all_chunks.append({
                    "id": chunk_id,
                    "text": chunk_text,
                    "metadata": metadata
                })
                
    print(f"Total chunks created: {len(all_chunks)}")
    
    with open(CHUNKS_DIR / "all_chunks.jsonl", "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk) + "\n")

if __name__ == "__main__":
    main()
