"""Cross-Platform Orchestration & Execution CLI (Windows & macOS & Linux).

Usage:
    python run.py                # Run both FastAPI server and Streamlit dashboard
    python run.py --api          # Start only FastAPI API server
    python run.py --dashboard    # Start only Streamlit dashboard
    python run.py --test         # Run full test suite (79 tests)
    python run.py --benchmark    # Run architecture benchmark (No cache vs Exact vs Semantic)
    python run.py --evaluate-docs# Run PDF and Text document evaluation
    python run.py --cost         # Run cost analysis on the 50-query benchmark results
    python run.py --check        # Run system and environment health check
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).parent.resolve()


def print_banner(title: str):
    print("=" * 80)
    print(f"  {title.center(76)}")
    print("=" * 80)


def check_environment():
    print_banner("SYSTEM & ENVIRONMENT HEALTH CHECK")
    print(f"Platform:        {sys.platform} ({os.name})")
    print(f"Python Executable: {sys.executable}")
    print(f"Python Version:    {sys.version.split()[0]}")
    print(f"Project Root:      {ROOT_DIR}")

    # Check key packages
    packages = ["intelligent_cache", "fastapi", "uvicorn", "pydantic", "numpy", "pypdf", "pytest"]
    print("\nPackage Status:")
    for pkg in packages:
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "installed")
            print(f"  [OK] {pkg:<20}: {ver}")
        except ImportError:
            print(f"  [MISSING] {pkg:<20}: Not installed")

    # Check data files
    print("\nDocument Data Files:")
    data_dir = ROOT_DIR / "data"
    if data_dir.exists():
        for f in sorted(data_dir.iterdir()):
            if f.is_file():
                size_kb = f.stat().st_size / 1024.0
                print(f"  - {f.name:<30} ({size_kb:.1f} KB)")
    else:
        print("  [WARNING] data/ directory not found")

    print("\nEnvironment is ready for execution.")


def run_tests():
    print_banner("RUNNING FULL TEST SUITE")
    cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
    res = subprocess.run(cmd, cwd=str(ROOT_DIR))
    sys.exit(res.returncode)


def run_benchmark():
    print_banner("RUNNING BENCHMARK COMPARISON")
    script = ROOT_DIR / "scripts" / "benchmark_comparison.py"
    res = subprocess.run([sys.executable, str(script)], cwd=str(ROOT_DIR))
    sys.exit(res.returncode)


def run_doc_evaluation():
    print_banner("RUNNING PDF & TEXT DOCUMENT EVALUATIONS")
    script = ROOT_DIR / "scripts" / "evaluate_documents.py"
    res = subprocess.run([sys.executable, str(script)], cwd=str(ROOT_DIR))
    sys.exit(res.returncode)


def run_cost_analysis():
    print_banner("RUNNING COST ANALYSIS (50-QUERY BENCHMARK)")
    script = ROOT_DIR / "scripts" / "cost_analysis.py"
    res = subprocess.run([sys.executable, str(script)], cwd=str(ROOT_DIR))
    sys.exit(res.returncode)


def run_api(port: int = 8000):
    print_banner(f"STARTING FASTAPI SERVER ON PORT {port}")
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]
    subprocess.run(cmd, cwd=str(ROOT_DIR))


def run_dashboard(port: int = 8501):
    print_banner(f"STARTING STREAMLIT DASHBOARD ON PORT {port}")
    dashboard_script = ROOT_DIR / "dashboard" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(dashboard_script),
        "--server.address", "0.0.0.0",
        "--server.port", str(port),
    ]
    subprocess.run(cmd, cwd=str(ROOT_DIR))


def run_all(api_port: int = 8000, dashboard_port: int = 8501):
    print_banner("STARTING INTELLIGENT CACHE SERVICE & DASHBOARD")
    print(f"API Server: http://localhost:{api_port} (Docs: http://localhost:{api_port}/docs)")
    print(f"Dashboard:  http://localhost:{dashboard_port}")
    print("\nPress Ctrl+C to stop all services.\n")

    api_cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(api_port),
    ]
    dashboard_script = ROOT_DIR / "dashboard" / "app.py"
    dashboard_cmd = [
        sys.executable, "-m", "streamlit", "run", str(dashboard_script),
        "--server.address", "0.0.0.0",
        "--server.port", str(dashboard_port),
    ]

    p_api = subprocess.Popen(api_cmd, cwd=str(ROOT_DIR))
    time.sleep(1.5)
    p_dash = subprocess.Popen(dashboard_cmd, cwd=str(ROOT_DIR))

    def cleanup(sig=None, frame=None):
        print("\nShutting down services...")
        try:
            p_api.terminate()
            p_dash.terminate()
            p_api.wait(timeout=3)
            p_dash.wait(timeout=3)
        except Exception:
            p_api.kill()
            p_dash.kill()
        print("All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        while True:
            time.sleep(0.5)
            if p_api.poll() is not None or p_dash.poll() is not None:
                cleanup()
    except KeyboardInterrupt:
        cleanup()


def main():
    parser = argparse.ArgumentParser(
        description="Intelligent Cache Optimization Cross-Platform Runner (Windows, macOS, Linux)"
    )
    parser.add_argument("--api", action="store_true", help="Run only the FastAPI API server")
    parser.add_argument("--dashboard", action="store_true", help="Run only the Streamlit dashboard")
    parser.add_argument("--test", action="store_true", help="Run full test suite (pytest)")
    parser.add_argument("--benchmark", action="store_true", help="Run architecture benchmark")
    parser.add_argument("--evaluate-docs", action="store_true", help="Run PDF and text document evaluations")
    parser.add_argument("--cost", action="store_true", help="Run cost analysis on the 50-query benchmark results")
    parser.add_argument("--check", action="store_true", help="Run system and environment health check")
    parser.add_argument("--api-port", type=int, default=8000, help="Port for FastAPI (default: 8000)")
    parser.add_argument("--dashboard-port", type=int, default=8501, help="Port for Streamlit (default: 8501)")

    args = parser.parse_args()

    if args.check:
        check_environment()
    elif args.test:
        run_tests()
    elif args.benchmark:
        run_benchmark()
    elif args.evaluate_docs:
        run_doc_evaluation()
    elif args.cost:
        run_cost_analysis()
    elif args.api:
        run_api(args.api_port)
    elif args.dashboard:
        run_dashboard(args.dashboard_port)
    else:
        run_all(args.api_port, args.dashboard_port)


if __name__ == "__main__":
    main()
