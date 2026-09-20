import json
import random
from pathlib import Path

QUERIES_DIR = Path("datasets/queries")
QUERIES_DIR.mkdir(parents=True, exist_ok=True)

companies = ["AAPL", "MSFT", "GOOGL", "JPM", "GS", "BAC", "WMT", "TGT", "COST", "JNJ", "PFE", "UNH"]
topics = ["revenue", "risk factors", "supply chain", "margins", "R&D", "competition"]

exact_duplicates = []
for i in range(150):
    c = random.choice(companies)
    t = random.choice(topics)
    q = f"What are the main concerns regarding {t} for {c} in the latest fiscal year?"
    exact_duplicates.append({"query_1": q, "query_2": q, "label": True})

paraphrases = []
templates_1 = [
    "How did {c} perform in terms of {t}?",
    "Can you detail the {t} status for {c}?",
    "What were the key takeaways about {t} from {c}'s recent filings?"
]
templates_2 = [
    "Tell me about {c}'s {t} performance.",
    "I need details on {c} and their {t}.",
    "Summarize {t} for {c}."
]

for i in range(150):
    c = random.choice(companies)
    t = random.choice(topics)
    q1 = random.choice(templates_1).format(c=c, t=t)
    q2 = random.choice(templates_2).format(c=c, t=t)
    paraphrases.append({"query_1": q1, "query_2": q2, "label": True})

context_dependent = []
for i in range(100):
    t = random.choice(topics)
    q = f"What did they say about {t}?"
    c1 = random.choice(companies)
    c2 = random.choice(companies)
    label = (c1 == c2)
    context_dependent.append({
        "query": q,
        "context_1": f"The user is asking about {c1}.",
        "context_2": f"The user is asking about {c2}.",
        "label": label
    })

near_miss_negatives = []
for i in range(100):
    # Same company, different topic
    if random.random() < 0.33:
        c = random.choice(companies)
        t1, t2 = random.sample(topics, 2)
        q1 = f"What is the {t1} of {c}?"
        q2 = f"What is the {t2} of {c}?"
    # Same topic, different company
    elif random.random() < 0.5:
        c1, c2 = random.sample(companies, 2)
        t = random.choice(topics)
        q1 = f"What is the {t} of {c1}?"
        q2 = f"What is the {t} of {c2}?"
    # Same topic, different quarter
    else:
        c = random.choice(companies)
        t = random.choice(topics)
        q1 = f"What was {c}'s {t} in Q1?"
        q2 = f"What was {c}'s {t} in Q2?"
    
    near_miss_negatives.append({"query_1": q1, "query_2": q2, "label": False})

def write_jsonl(filename, data):
    with open(QUERIES_DIR / filename, "w") as f:
        for d in data:
            f.write(json.dumps(d) + "\n")

write_jsonl("exact_duplicates.jsonl", exact_duplicates)
write_jsonl("paraphrases.jsonl", paraphrases)
write_jsonl("context_dependent.jsonl", context_dependent)
write_jsonl("near_miss_negatives.jsonl", near_miss_negatives)
