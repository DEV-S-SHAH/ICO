import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs/promises';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { detectProject, getProjectName } from '../src/utils/project-detection.js';
import { 
  generateEnvExample, 
  generateDockerCompose, 
  generateIntegrationCode,
  generateGatewayConfig,
  getProviderTemplates,
  ProviderConfig,
  GatewayConfig,
  InitConfig 
} from '../src/utils/config-generator.js';
import { writeFileSafe, readFileSafe, fileExists } from '../src/utils/file-utils.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Project Detection', () => {
  const testDir = path.join(__dirname, 'fixtures', 'test-project-detection');
  
  beforeEach(async () => {
    await fs.rm(testDir, { recursive: true, force: true });
    await fs.mkdir(testDir, { recursive: true });
  });

  afterEach(async () => {
    await fs.rm(testDir, { recursive: true, force: true });
  });

  it('detects Node.js project with package.json', async () => {
    await fs.writeFile(path.join(testDir, 'package.json'), JSON.stringify({ name: 'test-project' }));
    
    const info = await detectProject(testDir);
    expect(info.type).toBe('node');
    expect(info.hasPackageJson).toBe(true);
    expect(info.packageManager).toBe('npm');
  });

  it('detects Python project with pyproject.toml', async () => {
    await fs.writeFile(path.join(testDir, 'pyproject.toml'), 'name = "test-project"\nversion = "1.0.0"');
    
    const info = await detectProject(testDir);
    expect(info.type).toBe('python');
    expect(info.hasPyprojectToml).toBe(true);
    expect(info.packageManager).toBe('pip');
  });

  it('detects Python project with requirements.txt', async () => {
    await fs.writeFile(path.join(testDir, 'requirements.txt'), 'requests\n');
    
    const info = await detectProject(testDir);
    expect(info.type).toBe('python');
    expect(info.hasRequirementsTxt).toBe(true);
  });

  it('detects mixed project', async () => {
    await fs.writeFile(path.join(testDir, 'package.json'), JSON.stringify({ name: 'test-project' }));
    await fs.writeFile(path.join(testDir, 'pyproject.toml'), 'name = "test-project"\nversion = "1.0.0"');
    
    const info = await detectProject(testDir);
    expect(info.type).toBe('mixed');
  });

  it('detects yarn from yarn.lock', async () => {
    await fs.writeFile(path.join(testDir, 'package.json'), JSON.stringify({ name: 'test-project' }));
    await fs.writeFile(path.join(testDir, 'yarn.lock'), '# yarn lockfile');
    
    const info = await detectProject(testDir);
    expect(info.packageManager).toBe('yarn');
  });

  it('detects pnpm from pnpm-lock.yaml', async () => {
    await fs.writeFile(path.join(testDir, 'package.json'), JSON.stringify({ name: 'test-project' }));
    await fs.writeFile(path.join(testDir, 'pnpm-lock.yaml'), '# pnpm lockfile');
    
    const info = await detectProject(testDir);
    expect(info.packageManager).toBe('pnpm');
  });

  it('detects uv from uv.lock', async () => {
    await fs.writeFile(path.join(testDir, 'pyproject.toml'), 'name = "test-project"\nversion = "1.0.0"');
    await fs.writeFile(path.join(testDir, 'uv.lock'), '# uv lockfile');
    
    const info = await detectProject(testDir);
    expect(info.packageManager).toBe('uv');
  });

  it('gets project name from package.json', async () => {
    await fs.writeFile(path.join(testDir, 'package.json'), JSON.stringify({ name: 'my-awesome-project' }));
    
    const name = await getProjectName(testDir);
    expect(name).toBe('my-awesome-project');
  });

  it('gets project name from pyproject.toml', async () => {
    await fs.writeFile(path.join(testDir, 'pyproject.toml'), 'name = "my-python-project"\nversion = "1.0.0"');
    
    const name = await getProjectName(testDir);
    expect(name).toBe('my-python-project');
  });

  it('falls back to directory name', async () => {
    await fs.mkdir(path.join(testDir, 'fallback-project'), { recursive: true });
    
    const name = await getProjectName(path.join(testDir, 'fallback-project'));
    expect(name).toBe('fallback-project');
  });
});

describe('Config Generator', () => {
  const mockInitConfig: InitConfig = {
    projectName: 'test-project',
    projectType: 'node',
    provider: {
      provider: 'openai',
      model: 'gpt-4o-mini',
    },
    gateway: {
      enabled: true,
      port: 8000,
      host: 'localhost',
      apiKeys: { 'test-key-123': 'default' },
    },
    envExample: '',
    dockerCompose: '',
    integrationCode: '',
  };

  it('generates .env.example with all required sections', () => {
    const envExample = generateEnvExample(mockInitConfig);
    
    expect(envExample).toContain('LLM_PROVIDER=openai');
    expect(envExample).toContain('LLM_MODEL=gpt-4o-mini');
    expect(envExample).toContain('OPENAI_API_KEY=your-api-key-here');
    expect(envExample).toContain('GATEWAY_ENABLED=true');
    expect(envExample).toContain('GATEWAY_HOST=localhost');
    expect(envExample).toContain('GATEWAY_PORT=8000');
    expect(envExample).toContain('API_KEYS=');
    expect(envExample).toContain('REDIS_HOST=localhost');
    expect(envExample).toContain('QDRANT_HOST=localhost');
    expect(envExample).toContain('LANGFUSE_HOST=');
    expect(envExample).toContain('ENVIRONMENT=development');
  });

  it('generates .env.example for ollama without API key', () => {
    const config = { ...mockInitConfig, provider: { provider: 'ollama', model: 'llama3.1' } };
    const envExample = generateEnvExample(config);
    
    expect(envExample).toContain('LLM_PROVIDER=ollama');
    expect(envExample).toContain('LLM_MODEL=llama3.1');
    expect(envExample).toContain('OLLAMA_BASE_URL=http://localhost:11434');
    expect(envExample).not.toContain('API_KEY=');
  });

  it('generates .env.example with custom base URL', () => {
    const config = { 
      ...mockInitConfig, 
      provider: { provider: 'custom', model: 'custom', baseUrl: 'https://api.custom.com/v1' } 
    };
    const envExample = generateEnvExample(config);
    
    expect(envExample).toContain('LLM_BASE_URL=https://api.custom.com/v1');
  });

  it('generates docker-compose.yml', () => {
    const dockerCompose = generateDockerCompose(mockInitConfig);
    
    expect(dockerCompose).toContain('ico-cache-api:');
    expect(dockerCompose).toContain('image: ico-cache-api:latest');
    expect(dockerCompose).toContain('qdrant:');
    expect(dockerCompose).toContain('redis:');
    expect(dockerCompose).toContain('ports:');
    expect(dockerCompose).toContain('8000:8000');
    expect(dockerCompose).toContain('volumes:');
  });

  it('generates Node.js integration code', () => {
    const integrationCode = generateIntegrationCode(mockInitConfig, 'node');
    
    expect(integrationCode).toContain('ico-cache-js');
    expect(integrationCode).toContain('icoCache');
    expect(integrationCode).toContain('baseUrl');
    expect(integrationCode).toContain('apiKey');
    expect(integrationCode).toContain('resolve');
  });

  it('generates Python integration code', () => {
    const integrationCode = generateIntegrationCode(mockInitConfig, 'python');
    
    expect(integrationCode).toContain('ico_cache');
    expect(integrationCode).toContain('IcoCache');
    expect(integrationCode).toContain('base_url');
    expect(integrationCode).toContain('api_key');
    expect(integrationCode).toContain('resolve');
  });

  it('generates gateway config JSON', () => {
    const gatewayConfig = generateGatewayConfig(mockInitConfig);
    const parsed = JSON.parse(gatewayConfig);
    
    expect(parsed.gateway.enabled).toBe(true);
    expect(parsed.gateway.port).toBe(8000);
    expect(parsed.gateway.apiKeys).toEqual({ 'test-key-123': 'default' });
    expect(parsed.provider.provider).toBe('openai');
    expect(parsed.provider.model).toBe('gpt-4o-mini');
    expect(parsed.backends.redis.host).toBe('localhost');
    expect(parsed.backends.qdrant.host).toBe('localhost');
  });

  it('returns provider templates', () => {
    const templates = getProviderTemplates();
    
    expect(templates.openai).toBeDefined();
    expect(templates.anthropic).toBeDefined();
    expect(templates.gemini).toBeDefined();
    expect(templates.ollama).toBeDefined();
    expect(templates.custom).toBeDefined();
    
    expect(templates.openai.models).toContain('gpt-4o-mini');
    expect(templates.ollama.envVar).toBe('OLLAMA_BASE_URL');
  });
});

describe('File Utils', () => {
  const testDir = path.join(__dirname, 'fixtures', 'test-file-utils');
  
  beforeEach(async () => {
    await fs.rm(testDir, { recursive: true, force: true });
    await fs.mkdir(testDir, { recursive: true });
  });

  afterEach(async () => {
    await fs.rm(testDir, { recursive: true, force: true });
  });

  it('writes and reads files safely', async () => {
    const filePath = path.join(testDir, 'test.txt');
    const content = 'Hello, World!';
    
    await writeFileSafe(filePath, content);
    const readContent = await readFileSafe(filePath);
    
    expect(readContent).toBe(content);
  });

  it('creates parent directories', async () => {
    const filePath = path.join(testDir, 'nested', 'deep', 'test.txt');
    const content = 'Nested content';
    
    await writeFileSafe(filePath, content);
    const readContent = await readFileSafe(filePath);
    
    expect(readContent).toBe(content);
  });

  it('returns null for non-existent files', async () => {
    const content = await readFileSafe(path.join(testDir, 'nonexistent.txt'));
    expect(content).toBeNull();
  });

  it('checks file existence', async () => {
    const filePath = path.join(testDir, 'exists.txt');
    
    expect(await fileExists(filePath)).toBe(false);
    
    await writeFileSafe(filePath, 'content');
    
    expect(await fileExists(filePath)).toBe(true);
  });
});

describe('IcoCache SDK', () => {
  it('exports IcoCache class and icoCache function', async () => {
    const { IcoCache, icoCache } = await import('../src/index.js');
    
    expect(IcoCache).toBeDefined();
    expect(icoCache).toBeDefined();
  });

  it('creates instance with baseUrl and apiKey', async () => {
    const { IcoCache } = await import('../src/index.js');
    
    const cache = new IcoCache({ baseUrl: 'http://localhost:8000', apiKey: 'test-key' });
    expect(cache).toBeInstanceOf(IcoCache);
  });

  it('creates instance via factory function', async () => {
    const { icoCache } = await import('../src/index.js');
    
    const cache = icoCache({ baseUrl: 'http://localhost:8000', apiKey: 'test-key' });
    expect(cache).toBeInstanceOf(Object);
  });
});