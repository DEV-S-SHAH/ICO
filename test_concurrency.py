import concurrent.futures
import requests
import time

def send_query(i):
    url = "http://127.0.0.1:8000/query"
    payload = {"query": f"concurrency test query {i}"}
    resp = requests.post(url, json=payload)
    if resp.status_code != 200:
        return False
    return True

for threads in [20, 50, 100]:
    print(f"Testing {threads} concurrent threads...")
    start_time = time.time()
    success = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(send_query, 42) for _ in range(threads)] # SAME QUERY so only 1 generation!
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                success += 1
    duration = time.time() - start_time
    print(f"  {success}/{threads} succeeded in {duration:.2f}s (Errors: {threads - success})")
    if threads - success > 0:
        raise RuntimeError(f"Concurrency test failed: {threads - success} errors out of {threads}")
