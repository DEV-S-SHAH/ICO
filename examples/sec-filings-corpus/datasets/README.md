# ICO-Agent Dataset

## Overview
This dataset contains real SEC filings (10-K and 10-Q) for 12 companies across 4 sectors. The raw HTML files were stripped and chunked into ~700-token chunks with ~15% overlap, preserving metadata regarding the company, filing type, report date, and item section.

## Companies
**Tech**
- AAPL
- MSFT
- GOOGL

**Finance**
- JPM
- GS
- BAC

**Retail**
- WMT
- TGT
- COST

**Healthcare**
- JNJ
- PFE
- UNH

## Fetch Date
2026-09-19

## Chunking Rationale
We used a structure-aware approach via `RecursiveCharacterTextSplitter`. The text is first isolated to core SEC Items (Item 1, 1A, 7) before chunking, ensuring that chunks do not bleed across completely unrelated sections. The ~700 token size is chosen to fit comfortably in standard LLM context windows while providing enough surrounding context to accurately answer RAG queries.

## Corpus Size and Chunk Count
- **Raw Files**: 114 MB
- **Processed Sections**: 1.5 MB
- **Chunks**: 560 (~700 tokens each)
