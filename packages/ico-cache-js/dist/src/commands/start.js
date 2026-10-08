"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.startCommand = void 0;
const commander_1 = require("commander");
const inquirer_1 = __importDefault(require("inquirer"));
const chalk_1 = __importDefault(require("chalk"));
const ora_1 = __importDefault(require("ora"));
const path = __importStar(require("path"));
const url_1 = require("url");
const child_process_1 = require("child_process");
const project_detection_js_1 = require("../utils/project-detection.js");
const file_utils_js_1 = require("../utils/file-utils.js");
const __filename = (0, url_1.fileURLToPath)(import.meta.url);
const __dirname = path.dirname(__filename);
async function checkDockerAvailable() {
    return new Promise((resolve) => {
        const child = (0, child_process_1.spawn)('docker', ['version'], { stdio: 'ignore' });
        child.on('close', (code) => resolve(code === 0));
        child.on('error', () => resolve(false));
    });
}
async function checkDockerComposeAvailable() {
    return new Promise((resolve) => {
        const child = (0, child_process_1.spawn)('docker', ['compose', 'version'], { stdio: 'ignore' });
        child.on('close', (code) => resolve(code === 0));
        child.on('error', () => resolve(false));
    });
}
async function checkPythonAvailable() {
    return new Promise((resolve) => {
        const child = (0, child_process_1.spawn)('python3', ['--version'], { stdio: 'ignore' });
        child.on('close', (code) => resolve(code === 0));
        child.on('error', () => resolve(false));
    });
}
async function checkNodeAvailable() {
    return new Promise((resolve) => {
        const child = (0, child_process_1.spawn)('node', ['--version'], { stdio: 'ignore' });
        child.on('close', (code) => resolve(code === 0));
        child.on('error', () => resolve(false));
    });
}
async function loadEnvFile(envPath) {
    const content = await (0, file_utils_js_1.readFileSafe)(envPath);
    if (!content)
        return {};
    const env = {};
    for (const line of content.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#'))
            continue;
        const eqIndex = trimmed.indexOf('=');
        if (eqIndex > 0) {
            const key = trimmed.slice(0, eqIndex).trim();
            const value = trimmed.slice(eqIndex + 1).trim();
            env[key] = value;
        }
    }
    return env;
}
async function startWithDockerCompose(options) {
    const composeFiles = ['docker-compose.yml'];
    const overrideFile = 'docker-compose.override.yml';
    if (await (0, file_utils_js_1.fileExists)(overrideFile)) {
        composeFiles.push(overrideFile);
    }
    const args = ['compose'];
    for (const file of composeFiles) {
        args.push('-f', file);
    }
    args.push('up');
    if (options.detach)
        args.push('-d');
    const spinner = (0, ora_1.default)(`Starting with Docker Compose (${composeFiles.join(', ')})`).start();
    const child = (0, child_process_1.spawn)('docker', args, {
        stdio: options.detach ? 'ignore' : 'inherit',
        env: { ...process.env },
    });
    return new Promise((resolve) => {
        child.on('spawn', () => {
            spinner.succeed(chalk_1.default.green('Docker Compose started'));
            if (options.detach) {
                console.log(chalk_1.default.gray('Running in background. Use `docker compose logs -f` to view logs.'));
            }
            resolve(child);
        });
        child.on('error', (err) => {
            spinner.fail(chalk_1.default.red('Failed to start Docker Compose'));
            console.error(chalk_1.default.red(err.message));
            resolve(null);
        });
        child.on('close', (code) => {
            if (code !== 0 && !options.detach) {
                console.log(chalk_1.default.yellow(`Docker Compose exited with code ${code}`));
            }
            resolve(child);
        });
    });
}
async function startWithPython(options) {
    const projectInfo = await (0, project_detection_js_1.detectProject)();
    // Check for main.py or similar entry point
    const possibleEntryPoints = [
        'apps/financial-rag-demo/api/main.py',
        'api/main.py',
        'main.py',
        'src/main.py',
    ];
    let entryPoint = '';
    for (const ep of possibleEntryPoints) {
        if (await (0, file_utils_js_1.fileExists)(ep)) {
            entryPoint = ep;
            break;
        }
    }
    if (!entryPoint) {
        console.log(chalk_1.default.yellow('No Python entry point found. Looking for ico-cache-py installation...'));
        // Try to run ico-cache directly if installed
        const { spawn } = await import('child_process');
        const child = spawn('python', ['-m', 'ico_cache'], {
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
    const spinner = (0, ora_1.default)(`Starting Python API (${entryPoint})`).start();
    const child = (0, child_process_1.spawn)('python3', [entryPoint], {
        stdio: options.detach ? 'ignore' : 'inherit',
        env: mergedEnv,
    });
    return new Promise((resolve) => {
        child.on('spawn', () => {
            spinner.succeed(chalk_1.default.green(`Python API started on http://localhost:${options.port || 8000}`));
            resolve(child);
        });
        child.on('error', (err) => {
            spinner.fail(chalk_1.default.red('Failed to start Python API'));
            console.error(chalk_1.default.red(err.message));
            resolve(null);
        });
    });
}
async function startWithNode(options) {
    // Check for a Node.js entry point
    const possibleEntryPoints = [
        'dist/index.js',
        'build/index.js',
        'src/index.ts',
        'index.js',
    ];
    let entryPoint = '';
    for (const ep of possibleEntryPoints) {
        if (await (0, file_utils_js_1.fileExists)(ep)) {
            entryPoint = ep;
            break;
        }
    }
    if (!entryPoint) {
        console.log(chalk_1.default.yellow('No Node.js entry point found.'));
        return null;
    }
    const env = await loadEnvFile('.env');
    const mergedEnv = { ...process.env, ...env };
    const spinner = (0, ora_1.default)(`Starting Node.js server (${entryPoint})`).start();
    const isTypeScript = entryPoint.endsWith('.ts');
    const command = isTypeScript ? 'npx' : 'node';
    const args = isTypeScript ? ['tsx', entryPoint] : [entryPoint];
    const child = (0, child_process_1.spawn)(command, args, {
        stdio: options.detach ? 'ignore' : 'inherit',
        env: mergedEnv,
    });
    return new Promise((resolve) => {
        child.on('spawn', () => {
            spinner.succeed(chalk_1.default.green(`Node.js server started`));
            resolve(child);
        });
        child.on('error', (err) => {
            spinner.fail(chalk_1.default.red('Failed to start Node.js server'));
            console.error(chalk_1.default.red(err.message));
            resolve(null);
        });
    });
}
exports.startCommand = new commander_1.Command('start')
    .description('Start ICO-Cache locally')
    .option('-d, --docker', 'Use Docker Compose (default if docker-compose.yml exists)')
    .option('--detach', 'Run in background')
    .option('-p, --port <port>', 'Port for the gateway', '8000')
    .option('-c, --config <config>', 'Path to config file')
    .action(async (options) => {
    console.log(chalk_1.default.bold('\n🚀 Starting ICO-Cache...\n'));
    const projectInfo = await (0, project_detection_js_1.detectProject)();
    const hasDockerCompose = await (0, file_utils_js_1.fileExists)('docker-compose.yml');
    const hasOverride = await (0, file_utils_js_1.fileExists)('docker-compose.override.yml');
    const hasEnv = await (0, file_utils_js_1.fileExists)('.env');
    if (!hasEnv) {
        console.log(chalk_1.default.yellow('Warning: .env file not found. Copy .env.example to .env and configure your API keys.'));
        const { continueAnyway } = await inquirer_1.default.prompt([
            {
                type: 'confirm',
                name: 'continueAnyway',
                message: 'Continue anyway?',
                default: false,
            },
        ]);
        if (!continueAnyway) {
            console.log(chalk_1.default.gray('Run `ico-cache init` to generate configuration files.'));
            process.exit(0);
        }
    }
    // Determine start method
    let useDocker = options.docker;
    if (!useDocker && hasDockerCompose) {
        const dockerAvailable = await checkDockerAvailable();
        const composeAvailable = await checkDockerComposeAvailable();
        if (dockerAvailable && composeAvailable) {
            const { useDockerCompose } = await inquirer_1.default.prompt([
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
            console.log(chalk_1.default.red('Docker or Docker Compose not available. Falling back to local start.'));
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
        const child = await startWithPython(options);
        if (child) {
            // Wait for child if not detached
            if (!options.detach) {
                await new Promise((resolve) => {
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
                await new Promise((resolve) => {
                    child.on('close', () => resolve());
                });
            }
            return;
        }
    }
    console.log(chalk_1.default.red('Could not start ICO-Cache. No suitable runtime found.'));
    console.log(chalk_1.default.gray('Please ensure you have either:'));
    console.log(chalk_1.default.gray('  - Docker and Docker Compose installed'));
    console.log(chalk_1.default.gray('  - Python 3.11+ with ico-cache installed (pip install ico-cache)'));
    console.log(chalk_1.default.gray('  - Node.js 20+ with a compatible server'));
    process.exit(1);
});
