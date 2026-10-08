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
exports.initCommand = void 0;
const commander_1 = require("commander");
const inquirer_1 = __importDefault(require("inquirer"));
const chalk_1 = __importDefault(require("chalk"));
const ora_1 = __importDefault(require("ora"));
const path = __importStar(require("path"));
const url_1 = require("url");
const project_detection_js_1 = require("../utils/project-detection.js");
const config_generator_js_1 = require("../utils/config-generator.js");
const file_utils_js_1 = require("../utils/file-utils.js");
const __filename = (0, url_1.fileURLToPath)(import.meta.url);
const __dirname = path.dirname(__filename);
const PROVIDER_TEMPLATES = (0, config_generator_js_1.getProviderTemplates)();
async function selectProvider(options) {
    if (options.provider && PROVIDER_TEMPLATES[options.provider]) {
        const template = PROVIDER_TEMPLATES[options.provider];
        const model = options.model || template.defaultModel;
        return {
            provider: options.provider,
            model,
        };
    }
    const { provider } = await inquirer_1.default.prompt([
        {
            type: 'list',
            name: 'provider',
            message: 'Select your LLM provider:',
            choices: Object.entries(PROVIDER_TEMPLATES).map(([key, value]) => ({
                name: `${key.charAt(0).toUpperCase() + key.slice(1)} (${value.defaultModel})`,
                value: key,
            })),
            default: 'gemini',
        },
    ]);
    const template = PROVIDER_TEMPLATES[provider];
    let model = options.model;
    if (!model) {
        const { selectedModel } = await inquirer_1.default.prompt([
            {
                type: 'list',
                name: 'selectedModel',
                message: `Select ${provider} model:`,
                choices: template.models.map(m => ({ name: m, value: m })),
                default: template.defaultModel,
            },
        ]);
        model = selectedModel;
    }
    let baseUrl;
    if (provider === 'custom' || provider === 'ollama') {
        const { customUrl } = await inquirer_1.default.prompt([
            {
                type: 'input',
                name: 'customUrl',
                message: provider === 'ollama' ? 'Ollama base URL:' : 'Custom API base URL:',
                default: provider === 'ollama' ? 'http://localhost:11434' : 'https://api.example.com/v1',
            },
        ]);
        baseUrl = customUrl;
    }
    return { provider: provider, model: model, baseUrl };
}
async function selectGatewayConfig(options, projectInfo) {
    const port = options.gatewayPort || 8000;
    const host = options.gatewayHost || 'localhost';
    // Generate a secure API key
    const crypto = await import('crypto');
    const apiKey = crypto.randomBytes(32).toString('hex');
    const tenantId = 'default';
    const { enableGateway } = await inquirer_1.default.prompt([
        {
            type: 'confirm',
            name: 'enableGateway',
            message: 'Enable ICO-Cache Gateway (REST API for caching)?',
            default: true,
        },
    ]);
    return {
        enabled: enableGateway,
        port,
        host,
        apiKeys: { [apiKey]: tenantId },
    };
}
async function confirmOverwrites(files, force) {
    if (force)
        return true;
    const existingFiles = [];
    for (const file of files) {
        if (await (0, file_utils_js_1.fileExists)(file)) {
            existingFiles.push(file);
        }
    }
    if (existingFiles.length === 0)
        return true;
    console.log(chalk_1.default.yellow('\nThe following files already exist:'));
    for (const file of existingFiles) {
        console.log(`  ${chalk_1.default.cyan(file)}`);
    }
    const { confirm } = await inquirer_1.default.prompt([
        {
            type: 'confirm',
            name: 'confirm',
            message: 'Overwrite existing files?',
            default: false,
        },
    ]);
    return confirm;
}
exports.initCommand = new commander_1.Command('init')
    .description('Initialize ICO-Cache in your project')
    .option('-p, --provider <provider>', 'LLM provider (openai, anthropic, gemini, ollama, custom)')
    .option('-m, --model <model>', 'Model name')
    .option('--gateway-port <port>', 'Gateway port', '8000')
    .option('--gateway-host <host>', 'Gateway host', 'localhost')
    .option('-y, --yes', 'Skip prompts and use defaults')
    .option('-f, --force', 'Overwrite existing files without prompting')
    .action(async (options) => {
    const spinner = (0, ora_1.default)('Detecting project...').start();
    try {
        const projectInfo = await (0, project_detection_js_1.detectProject)();
        const projectName = await (0, project_detection_js_1.getProjectName)();
        spinner.succeed(chalk_1.default.green(`Detected ${projectInfo.type} project: ${projectName}`));
        if (projectInfo.type === 'unknown') {
            console.log(chalk_1.default.yellow('Warning: Could not detect project type. Proceeding with generic configuration.'));
        }
        // Show project info
        console.log(chalk_1.default.gray('\nProject Details:'));
        console.log(chalk_1.default.gray(`  Type: ${projectInfo.type}`));
        console.log(chalk_1.default.gray(`  Package Manager: ${projectInfo.packageManager}`));
        console.log(chalk_1.default.gray(`  Has Docker Compose: ${projectInfo.hasDockerCompose ? 'Yes' : 'No'}`));
        // Select provider
        const providerConfig = await selectProvider(options);
        // Select gateway config
        const gatewayConfig = await selectGatewayConfig(options, projectInfo);
        // Build init config
        const initConfig = {
            projectName,
            projectType: projectInfo.type,
            provider: providerConfig,
            gateway: gatewayConfig,
            envExample: '',
            dockerCompose: '',
            integrationCode: '',
        };
        // Generate configs
        initConfig.envExample = (0, config_generator_js_1.generateEnvExample)(initConfig);
        initConfig.dockerCompose = (0, config_generator_js_1.generateDockerCompose)(initConfig);
        initConfig.integrationCode = (0, config_generator_js_1.generateIntegrationCode)(initConfig, projectInfo.type);
        const gatewayConfigJson = (0, config_generator_js_1.generateGatewayConfig)(initConfig);
        // Files to create
        const filesToCreate = [
            { path: '.env.example', content: initConfig.envExample },
            { path: 'docker-compose.override.yml', content: initConfig.dockerCompose },
            { path: 'ico-cache.config.json', content: gatewayConfigJson },
        ];
        // Add integration example based on project type
        if (projectInfo.type === 'python' || projectInfo.type === 'mixed') {
            filesToCreate.push({
                path: 'ico_cache_integration.py',
                content: initConfig.integrationCode,
            });
        }
        if (projectInfo.type === 'node' || projectInfo.type === 'mixed') {
            filesToCreate.push({
                path: 'ico_cache_integration.js',
                content: initConfig.integrationCode,
            });
        }
        // Confirm overwrites
        const filePaths = filesToCreate.map(f => f.path);
        const canOverwrite = await confirmOverwrites(filePaths, options.force);
        if (!canOverwrite) {
            console.log(chalk_1.default.yellow('Init cancelled. No files were modified.'));
            return;
        }
        // Write files
        const writeSpinner = (0, ora_1.default)('Writing configuration files...').start();
        for (const file of filesToCreate) {
            await (0, file_utils_js_1.writeFileSafe)(file.path, file.content);
        }
        writeSpinner.succeed(chalk_1.default.green('Configuration files created!'));
        // Summary
        console.log(chalk_1.default.bold('\n✅ ICO-Cache initialized successfully!'));
        console.log(chalk_1.default.gray('\nCreated files:'));
        for (const file of filesToCreate) {
            console.log(chalk_1.default.gray(`  ${file.path}`));
        }
        console.log(chalk_1.default.bold('\n📋 Next steps:'));
        console.log(chalk_1.default.gray('  1. Copy .env.example to .env and fill in your API keys:'));
        console.log(chalk_1.default.cyan('     cp .env.example .env'));
        console.log(chalk_1.default.gray('  2. Edit .env with your API keys'));
        console.log(chalk_1.default.gray('  3. Start ICO-Cache locally:'));
        console.log(chalk_1.default.cyan('     ico-cache start'));
        console.log(chalk_1.default.gray('  4. Or start with Docker Compose:'));
        console.log(chalk_1.default.cyan('     docker compose -f docker-compose.yml -f docker-compose.override.yml up -d'));
        console.log(chalk_1.default.gray('  5. Test the integration:'));
        if (projectInfo.type === 'python' || projectInfo.type === 'mixed') {
            console.log(chalk_1.default.cyan('     python ico_cache_integration.py'));
        }
        if (projectInfo.type === 'node' || projectInfo.type === 'mixed') {
            console.log(chalk_1.default.cyan('     node ico_cache_integration.js'));
        }
        console.log(chalk_1.default.bold('\n📚 Documentation:'));
        console.log(chalk_1.default.gray('  - QUICKSTART.md - 5-minute quickstart guide'));
        console.log(chalk_1.default.gray('  - CLI_IMPLEMENTATION.md - CLI implementation details'));
    }
    catch (error) {
        spinner.fail(chalk_1.default.red('Failed to initialize ICO-Cache'));
        console.error(chalk_1.default.red(error instanceof Error ? error.message : String(error)));
        process.exit(1);
    }
});
