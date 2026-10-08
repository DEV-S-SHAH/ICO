# ICO-Cache Quickstart (5 minutes)

Get semantic caching for your LLM application in 5 minutes.

## Prerequisites

- Node.js 20+ or Python 3.11+
- An LLM API key (OpenAI, Anthropic, Gemini, or Ollama)

---

## 1. Initialize ICO-Cache

```bash
npx ico-cache init
```

This will:
- Detect your project type (Node.js, Python, or mixed)
- Prompt for your LLM provider and model
- Generate configuration files:
  - `.env.example` - Environment template
  - `docker-compose.override.yml` - Local Docker config
  - `ico-cache.config.json` - Gateway config
  - `ico_cache_integration.py` / `ico_cache_integration.js` - Example code

---

## 2. Configure API Keys

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required variables:
```bash
# Choose one provider
OPENAI_API_KEY=sk-...          # OpenAI
ANTHROPIC_API_KEY=sk-ant-...   # Anthropic
GEMINI_API_KEY=...             # Google Gemini
OLLAMA_BASE_URL=http://localhost:11434  # Ollama (local)

# Gateway (auto-generated)
API_KEYS={"your-gateway-key": "default"}
```

---

## 3. Start ICO-Cache

### Option A: Docker Compose (Recommended)

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
```

### Option B: Local Python

```bash
pip install ico-cache
python -m ico_cache
```

### Option C: CLI Auto-detect

```bash
ico-cache start
```

The gateway will be available at **http://localhost:8000**

---

## 4. Connect Your Application

### Option A: OpenAI-Compatible Proxy (Drop-in)

```bash
ico-cache connect
```

This generates:
- `openai_proxy.py` / `openai_proxy.js` - Proxy client
- `ico_cache_openai.py` / `ico_cache_openai.js` - Wrapper

**In your existing code, just change:**

```python
# Before
from openai import OpenAI
client = OpenAI(api_key="sk-...", base_url="https://api.openai.com/v1")

# After
from openai import OpenAI
client = OpenAI(api_key="your-gateway-key", base_url="http://localhost:8000/v1/openai")
```

```javascript
// Before
import OpenAI from 'openai';
const client = new OpenAI({ apiKey: 'sk-...', baseURL: 'https://api.openai.com/v1' });

// After
import OpenAI from 'openai';
const client = new OpenAI({ apiKey: 'your-gateway-key', baseURL: 'http://localhost:8000/v1/openai' });
```

### Option B: Direct SDK Integration

```python
# Python
from ico_cache import IcoCache

cache = IcoCache(base_url="http://localhost:8000", api_key="your-gateway-key")

async def call_llm():
    # Your existing LLM call
    return await openai_client.chat.completions.create(...)

response = await cache.resolve("Your prompt", "context", call_llm)
```

```javascript
// Node.js
import { icoCache } from 'ico-cache-js';

const cache = icoCache({ baseUrl: 'http://localhost:8000', apiKey: 'your-gateway-key' });

async function callLLM() {
  // Your existing LLM call
  return await openaiClient.chat.completions.create(...);
}

const response = await cache.resolve('Your prompt', 'context', callLLM);
```

---

## 5. Verify It Works

```bash
# Test the gateway
curl http://localhost:8000/v1/health

# Run the example
python ico_cache_integration.py
# or
node ico_cache_integration.js
```

You should see:
- First request: Cache MISS (calls LLM, stores result)
- Second request: Cache HIT (instant, no LLM call)

---

## What You Get

| Layer | Description | Speedup |
|-------|-------------|---------|
| **L1 Exact** | Identical prompt + context | ~1000x |
| **L2 Semantic** | Similar meaning (embeddings) | ~100x |
| **L3 Context** | Context-aware retrieval | ~10x |

---

## Next Steps

- **Production**: See `deploy/helm/ico-cache/` for Kubernetes deployment
- **Dashboard**: Run `cd apps/dashboard && npm run dev` for monitoring UI
- **RAG**: Add documents via `POST /v1/ingest` for L3 context-aware caching
- **Multi-tenancy**: Configure `API_KEYS` with multiple keys for isolation

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `docker compose` not found | Install Docker Desktop or `docker-compose` plugin |
| Port 8000 in use | Change `GATEWAY_PORT` in `.env` |
| Redis/Qdrant connection failed | Ensure Docker services are healthy: `docker compose ps` |
| API key invalid | Check `API_KEYS` in `.env` matches gateway config |
| Python import error | Run `pip install ico-cache` |

---

## Help

```bash
ico-cache --help           # All commands
ico-cache init --help      # Init options
ico-cache start --help     # Start options
ico-cache connect --help   # Connect options
```