# ICO-Cache CLI Implementation

## Overview

The ICO-Cache CLI (`ico-cache`) provides a developer-friendly installation and configuration experience for the ICO-Cache semantic caching middleware. It enables developers to initialize, configure, start, and connect applications to ICO-Cache in minutes.

## Architecture

```
ico-cache-js/
├── src/
│   ├── cli.ts                 # Entry point, command registration
│   ├── index.ts               # Public SDK (IcoCache class)
│   ├── commands/
│   │   ├── init.ts            # Project initialization
│   │   ├── start.ts           # Local startup
│   │   └── connect.ts         # OpenAI-compatible app connection
│   ├── utils/
│   │   ├── project-detection.ts  # Project type detection
│   │   ├── config-generator.ts   # Config file generation
│   │   └── file-utils.ts         # File I/O utilities
│   └── templates/             # Template files (future)
├── tests/
│   └── cli.test.ts           # Unit tests
├── package.json
├── tsconfig.json
├── vitest.config.ts
├── QUICKSTART.md
└── CLI_IMPLEMENTATION.md
```

## Commands

### `ico-cache init`

Initializes ICO-Cache in the current project.

**Features:**
- Auto-detects project type (Node.js, Python, mixed, unknown)
- Detects package manager (npm, yarn, pnpm, uv, pip)
- Interactive provider/model selection
- Generates secure API keys
- Creates configuration files idempotently
- Prompts before overwriting existing files

**Options:**
```bash
ico-cache init [options]
  -p, --provider <provider>     LLM provider (openai, anthropic, gemini, ollama, custom)
  -m, --model <model>           Model name
  --gateway-port <port>         Gateway port (default: 8000)
  --gateway-host <host>         Gateway host (default: localhost)
  -y, --yes                     Skip prompts, use defaults
  -f, --force                   Overwrite existing files
```

**Generated Files:**
| File | Purpose |
|------|---------|
| `.env.example` | Environment variable template |
| `docker-compose.override.yml` | Docker Compose override for local dev |
| `ico-cache.config.json` | Gateway configuration |
| `ico_cache_integration.py` | Python integration example |
| `ico_cache_integration.js` | Node.js integration example |

**Project Detection Logic:**
1. Check for `package.json` → Node.js project
2. Check for `pyproject.toml` or `requirements.txt` → Python project
3. Both → Mixed project
4. Check lockfiles for package manager:
   - `yarn.lock` → yarn
   - `pnpm-lock.yaml` → pnpm
   - `uv.lock` → uv
   - Default → npm/pip

### `ico-cache start`

Starts ICO-Cache locally.

**Features:**
- Prefers Docker Compose if available
- Falls back to Python (ico-cache-py) or Node.js
- Loads `.env` file for configuration
- Supports detached/background mode

**Options:**
```bash
ico-cache start [options]
  -d, --docker               Use Docker Compose
  --detach                   Run in background
  -p, --port <port>          Gateway port (default: 8000)
  -c, --config <config>      Config file path
```

**Startup Priority:**
1. Docker Compose (if `docker-compose.yml` exists and Docker available)
2. Python (`python -m ico_cache` or entry point)
3. Node.js (local server entry point)

### `ico-cache connect`

Connects an existing OpenAI-compatible application to ICO-Cache.

**Features:**
- Generates OpenAI-compatible proxy endpoint
- Creates drop-in client wrappers
- Updates `.env.example` with gateway API key
- Supports all major providers (OpenAI, Anthropic, Gemini, Ollama, Custom)

**Options:**
```bash
ico-cache connect [options]
  -p, --provider <provider>   LLM provider
  -m, --model <model>         Model name
  --base-url <url>            Provider base URL
  -k, --api-key <key>         Provider API key
  -g, --gateway-url <url>     ICO-Cache gateway URL (default: http://localhost:8000)
  -y, --yes                   Skip prompts
```

**Generated Files:**
| File | Purpose |
|------|---------|
| `openai_proxy.py` / `openai_proxy.js` | Proxy client example |
| `ico_cache_openai.py` / `ico_cache_openai.js` | Drop-in OpenAI wrapper |
| Updated `.env.example` | Gateway API key added |

**Integration Pattern:**
```python
# Replace this:
client = OpenAI(api_key="sk-...", base_url="https://api.openai.com/v1")

# With this:
client = OpenAI(api_key="gateway-key", base_url="http://localhost:8000/v1/openai")
```

The `/v1/openai` endpoint on the gateway translates OpenAI-format requests to ICO-Cache's internal API.

## SDK (ico-cache-js)

The public SDK exported from `index.ts`:

```typescript
interface IcoCacheOptions {
  baseUrl: string;
  apiKey?: string;
  semanticThreshold?: number;
}

class IcoCache {
  constructor(options: IcoCacheOptions);
  async resolve<T>(query: string, context: string | null, callback: () => Promise<T>): Promise<T>;
  async query(query: string, context: string | null): Promise<{ source: string; response: unknown }>;
  async ingest(query: string, context: string | null, response: unknown): Promise<void>;
  async health(): Promise<{ status: string; backends: Record<string, string> }>;
}

function icoCache(options: IcoCacheOptions): IcoCache;
```

**Usage:**
```javascript
import { icoCache } from 'ico-cache-js';

const cache = icoCache({ 
  baseUrl: 'http://localhost:8000', 
  apiKey: 'your-gateway-key' 
});

const response = await cache.resolve(
  'What is the capital of France?',
  'Geography',
  async () => {
    // Your LLM call
    return await openai.chat.completions.create({...});
  }
);
```

## Configuration Files

### `.env.example`

Template for environment variables. Copy to `.env` and fill in values.

Sections:
- LLM Provider Configuration
- ICO-Cache Gateway Configuration
- Backend Services (Redis, Qdrant)
- Observability (Langfuse, OpenTelemetry)
- Environment

### `docker-compose.override.yml`

Docker Compose override for local development. Merged with base `docker-compose.yml`.

Services:
- `ico-cache-api` - Main API gateway
- `qdrant` - Vector database
- `redis` - Exact cache + rate limiting

### `ico-cache.config.json`

JSON configuration for the gateway.

```json
{
  "gateway": { "enabled": true, "host": "localhost", "port": 8000, "apiKeys": {...} },
  "provider": { "provider": "openai", "model": "gpt-4o-mini", "baseUrl": "" },
  "backends": { "redis": {...}, "qdrant": {...} }
}
```

## Security Considerations

1. **No hardcoded secrets** - All keys generated at runtime using `crypto.randomBytes(32)`
2. **Idempotent init** - Safe to run multiple times
3. **No overwrites without confirmation** - `--force` flag required to skip prompts
4. **API keys in .env.example are placeholders** - Real keys only in `.env` (gitignored)
5. **Gateway API keys** - Generated per `connect` command, unique per application

## Testing

```bash
# Run tests
npm test

# Run with UI
npm test:ui

# Type checking
npx tsc --noEmit

# Build
npm run build
```

Test coverage includes:
- Project detection (Node, Python, mixed, package managers)
- Config generation (.env.example, docker-compose, integration code)
- File utilities (read, write, exists)
- SDK exports

## Extending the CLI

### Adding a New Command

1. Create `src/commands/new-command.ts`
2. Export a `Command` instance
3. Register in `src/cli.ts`

```typescript
// src/commands/new-command.ts
import { Command } from 'commander';
import { newCommand } from './commands/new-command.js';

program.addCommand(newCommand);
```

### Adding a Provider

Update `PROVIDER_TEMPLATES` in `src/utils/config-generator.ts`:

```typescript
const PROVIDER_TEMPLATES = {
  // ... existing
  newprovider: {
    models: ['model-1', 'model-2'],
    defaultModel: 'model-1',
    envVar: 'NEWP_PROVIDER_API_KEY',
  },
};
```

### Adding Project Type Detection

Modify `detectProject()` in `src/utils/project-detection.ts`.

## Version Sync

The CLI version is synced with `ico-cache-py` via `package.json` version field. Both packages must have the same version (enforced by `test_version_sync.py`).

## Dependencies

| Package | Purpose |
|---------|---------|
| `commander` | CLI framework |
| `inquirer` | Interactive prompts |
| `chalk` | Terminal colors |
| `ora` | Spinners |
| `fs-extra` | Enhanced file I/O |
| `yaml` | YAML parsing (future) |
| `vitest` | Testing |
| `typescript` | Type checking |

## Future Enhancements

- [ ] `ico-cache config` - View/modify configuration
- [ ] `ico-cache logs` - View gateway logs
- [ ] `ico-cache status` - Check gateway health
- [ ] `ico-cache migrate` - Migrate configs between versions
- [ ] Shell completions (bash, zsh, fish)
- [ ] Template customization via `~/.ico-cache/templates/`