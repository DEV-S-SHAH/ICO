import { Command } from 'commander';
import inquirer from 'inquirer';
import chalk from 'chalk';
import ora from 'ora';
import * as fs from 'fs/promises';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { spawn, ChildProcess } from 'child_process';
import { detectProject } from '../utils/project-detection.js';
import { readFileSafe, fileExists } from '../utils/file-utils.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

interface StartOptions {
  docker?: boolean;
  detach?: boolean;
  port?: number;
  config?: string;
}

async function checkDockerAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn('docker', ['version'], { stdio: 'ignore' });
    child.on('close', (code) => resolve(code === 0));
    child.on('error', () => resolve(false));
  });
}

async function checkDockerComposeAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn('docker', ['compose', 'version'], { stdio: 'ignore' });
    child.on('close', (code) => resolve(code === 0));
    child.on('error', () => resolve(false));
  });
}

async function checkPythonAvailable(): Promise<string | null> {
  const candidates = [process.env.PYTHON, 'python3.11', 'python3', 'python'].filter(Boolean) as string[];
  for (const cmd of candidates) {
    const available = await new Promise<boolean>((resolve) => {
      const child = spawn(cmd, ['--version'], { stdio: 'ignore' });
      child.on('close', (code) => resolve(code === 0));
      child.on('error', () => resolve(false));
    });
    if (available) return cmd;
  }
  return null;
}

async function checkNodeAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn('node', ['--version'], { stdio: 'ignore' });
    child.on('close', (code) => resolve(code === 0));
    child.on('error', () => resolve(false));
  });
}

async function loadEnvFile(envPath: string): Promise<Record<string, string>> {
  const content = await readFileSafe(envPath);
  if (!content) return {};
  
  const env: Record<string, string> = {};
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIndex = trimmed.indexOf('=');
    if (eqIndex > 0) {
      const key = trimmed.slice(0, eqIndex).trim();
      const value = trimmed.slice(eqIndex + 1).trim();
      env[key] = value;
    }
  }
  return env;
}

async function startWithDockerCompose(options: StartOptions): Promise<ChildProcess | null> {
  const composeFiles = ['docker-compose.yml'];
  const overrideFile = 'docker-compose.override.yml';
  
  if (await fileExists(overrideFile)) {
    composeFiles.push(overrideFile);
  }

  const args = ['compose'];
  for (const file of composeFiles) {
    args.push('-f', file);
  }
  args.push('up');
  if (options.detach) args.push('-d');

  const spinner = ora(`Starting with Docker Compose (${composeFiles.join(', ')})`).start();
  
  const child = spawn('docker', args, {
    stdio: options.detach ? 'ignore' : 'inherit',
    env: { ...process.env },
  });

  return new Promise((resolve) => {
    child.on('spawn', () => {
      spinner.succeed(chalk.green('Docker Compose started'));
      if (options.detach) {
        console.log(chalk.gray('Running in background. Use `docker compose logs -f` to view logs.'));
      }
      resolve(child);
    });
    child.on('error', (err) => {
      spinner.fail(chalk.red('Failed to start Docker Compose'));
      console.error(chalk.red(err.message));
      resolve(null);
    });
    child.on('close', (code) => {
      if (code !== 0 && !options.detach) {
        console.log(chalk.yellow(`Docker Compose exited with code ${code}`));
      }
      resolve(child);
    });
  });
}

async function startWithPython(options: StartOptions, pythonCmd: string = 'python3'): Promise<ChildProcess | null> {
  const projectInfo = await detectProject();
  
  // Check for main.py or similar entry point
  const possibleEntryPoints = [
    'examples/real-rag-demo/src/main.py',
    'apps/financial-rag-demo/api/main.py',
    'api/main.py',
    'main.py',
    'src/main.py',
  ];

  let entryPoint = '';
  for (const ep of possibleEntryPoints) {
    if (await fileExists(ep)) {
      entryPoint = ep;
      break;
    }
  }

  if (!entryPoint) {
    console.log(chalk.yellow('No Python entry point found. Looking for ico-cache-py installation...'));
    
    // Try to run ico-cache directly if installed
    const { spawn } = await import('child_process');
    const child = spawn(pythonCmd, ['-m', 'ico_cache'], {
      stdio: options.detach ? 'ignore' : 'inherit',
      env: { ...process.env },
    });
    
    return new Promise((resolve) => {
      child.on('spawn', () => resolve(child));
      child.on('error', () => resolve(null));
    });
  }

  // Load .env file
  const env = await loadEnvFile('.env');
  const mergedEnv = { ...process.env, ...env };

  const spinner = ora(`Starting Python API (${entryPoint})`).start();
  
  const child = spawn(pythonCmd, [entryPoint], {
    stdio: options.detach ? 'ignore' : 'inherit',
    env: mergedEnv,
  });

  return new Promise((resolve) => {
    child.on('spawn', () => {
      spinner.succeed(chalk.green(`Python API started on http://localhost:${options.port || 8000}`));
      resolve(child);
    });
    child.on('error', (err) => {
      spinner.fail(chalk.red('Failed to start Python API'));
      console.error(chalk.red(err.message));
      resolve(null);
    });
  });
}

async function startWithNode(options: StartOptions): Promise<ChildProcess | null> {
  // Check for a Node.js entry point
  const possibleEntryPoints = [
    'dist/index.js',
    'build/index.js',
    'src/index.ts',
    'index.js',
  ];

  let entryPoint = '';
  for (const ep of possibleEntryPoints) {
    if (await fileExists(ep)) {
      entryPoint = ep;
      break;
    }
  }

  if (!entryPoint) {
    console.log(chalk.yellow('No Node.js entry point found.'));
    return null;
  }

  const env = await loadEnvFile('.env');
  const mergedEnv = { ...process.env, ...env };

  const spinner = ora(`Starting Node.js server (${entryPoint})`).start();
  
  const isTypeScript = entryPoint.endsWith('.ts');
  const command = isTypeScript ? 'npx' : 'node';
  const args = isTypeScript ? ['tsx', entryPoint] : [entryPoint];

  const child = spawn(command, args, {
    stdio: options.detach ? 'ignore' : 'inherit',
    env: mergedEnv,
  });

  return new Promise((resolve) => {
    child.on('spawn', () => {
      spinner.succeed(chalk.green(`Node.js server started`));
      resolve(child);
    });
    child.on('error', (err) => {
      spinner.fail(chalk.red('Failed to start Node.js server'));
      console.error(chalk.red(err.message));
      resolve(null);
    });
  });
}

export const startCommand = new Command('start')
  .description('Start ICO-Cache locally')
  .option('-d, --docker', 'Use Docker Compose (default if docker-compose.yml exists)')
  .option('--detach', 'Run in background')
  .option('-p, --port <port>', 'Port for the gateway', '8000')
  .option('-c, --config <config>', 'Path to config file')
  .action(async (options: StartOptions) => {
    console.log(chalk.bold('\n🚀 Starting ICO-Cache...\n'));

    const projectInfo = await detectProject();
    const hasDockerCompose = await fileExists('docker-compose.yml');
    const hasOverride = await fileExists('docker-compose.override.yml');
    const hasEnv = await fileExists('.env');

    if (!hasEnv) {
      console.log(chalk.yellow('Warning: .env file not found. Copy .env.example to .env and configure your API keys.'));
      const { continueAnyway } = await inquirer.prompt([
        {
          type: 'confirm',
          name: 'continueAnyway',
          message: 'Continue anyway?',
          default: false,
        },
      ]);
      if (!continueAnyway) {
        console.log(chalk.gray('Run `ico-cache init` to generate configuration files.'));
        process.exit(0);
      }
    }

    // Determine start method
    let useDocker = options.docker;
    
    if (!useDocker && hasDockerCompose) {
      const dockerAvailable = await checkDockerAvailable();
      const composeAvailable = await checkDockerComposeAvailable();
      
      if (dockerAvailable && composeAvailable) {
        const { useDockerCompose } = await inquirer.prompt([
          {
            type: 'confirm',
            name: 'useDockerCompose',
            message: 'Docker Compose detected. Use it to start ICO-Cache?',
            default: true,
          },
        ]);
        useDocker = useDockerCompose;
      }
    }

    if (useDocker) {
      const dockerAvailable = await checkDockerAvailable();
      const composeAvailable = await checkDockerComposeAvailable();
      
      if (!dockerAvailable || !composeAvailable) {
        console.log(chalk.red('Docker or Docker Compose not available. Falling back to local start.'));
        useDocker = false;
      }
    }

    if (useDocker) {
      await startWithDockerCompose(options);
      return;
    }

    // Try Python first (since ico-cache-py is the main implementation)
    const pythonAvailable = await checkPythonAvailable();
    if (pythonAvailable) {
      const child = await startWithPython(options, pythonAvailable);
      if (child) {
        // Wait for child if not detached
        if (!options.detach) {
          await new Promise<void>((resolve) => {
            child.on('close', () => resolve());
          });
        }
        return;
      }
    }

    // Try Node.js
    const nodeAvailable = await checkNodeAvailable();
    if (nodeAvailable) {
      const child = await startWithNode(options);
      if (child) {
        if (!options.detach) {
          await new Promise<void>((resolve) => {
            child.on('close', () => resolve());
          });
        }
        return;
      }
    }

    console.log(chalk.red('Could not start ICO-Cache. No suitable runtime found.'));
    console.log(chalk.gray('Please ensure you have either:'));
    console.log(chalk.gray('  - Docker and Docker Compose installed'));
    console.log(chalk.gray('  - Python 3.11+ with ico-cache installed (pip install ico-cache)'));
    console.log(chalk.gray('  - Node.js 20+ with a compatible server'));
    process.exit(1);
  });