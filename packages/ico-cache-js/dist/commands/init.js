import { Command } from 'commander';
import inquirer from 'inquirer';
import chalk from 'chalk';
import ora from 'ora';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { detectProject, getProjectName } from '../utils/project-detection.js';
import { generateEnvExample, generateDockerCompose, generateIntegrationCode, generateGatewayConfig, getProviderTemplates } from '../utils/config-generator.js';
import { writeFileSafe, fileExists } from '../utils/file-utils.js';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROVIDER_TEMPLATES = getProviderTemplates();
async function selectProvider(options) {
    if (options.provider && PROVIDER_TEMPLATES[options.provider]) {
        const template = PROVIDER_TEMPLATES[options.provider];
        const model = options.model || template.defaultModel;
        return {
            provider: options.provider,
            model,
        };
    }
    const { provider } = await inquirer.prompt([
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
        const { selectedModel } = await inquirer.prompt([
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
        const { customUrl } = await inquirer.prompt([
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
    const { enableGateway } = await inquirer.prompt([
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
        if (await fileExists(file)) {
            existingFiles.push(file);
        }
    }
    if (existingFiles.length === 0)
        return true;
    console.log(chalk.yellow('\nThe following files already exist:'));
    for (const file of existingFiles) {
        console.log(`  ${chalk.cyan(file)}`);
    }
    const { confirm } = await inquirer.prompt([
        {
            type: 'confirm',
            name: 'confirm',
            message: 'Overwrite existing files?',
            default: false,
        },
    ]);
    return confirm;
}
export const initCommand = new Command('init')
    .description('Initialize ICO-Cache in your project')
    .option('-p, --provider <provider>', 'LLM provider (openai, anthropic, gemini, ollama, custom)')
    .option('-m, --model <model>', 'Model name')
    .option('--gateway-port <port>', 'Gateway port', '8000')
    .option('--gateway-host <host>', 'Gateway host', 'localhost')
    .option('-y, --yes', 'Skip prompts and use defaults')
    .option('-f, --force', 'Overwrite existing files without prompting')
    .action(async (options) => {
    const spinner = ora('Detecting project...').start();
    try {
        const projectInfo = await detectProject();
        const projectName = await getProjectName();
        spinner.succeed(chalk.green(`Detected ${projectInfo.type} project: ${projectName}`));
        if (projectInfo.type === 'unknown') {
            console.log(chalk.yellow('Warning: Could not detect project type. Proceeding with generic configuration.'));
        }
        // Show project info
        console.log(chalk.gray('\nProject Details:'));
        console.log(chalk.gray(`  Type: ${projectInfo.type}`));
        console.log(chalk.gray(`  Package Manager: ${projectInfo.packageManager}`));
        console.log(chalk.gray(`  Has Docker Compose: ${projectInfo.hasDockerCompose ? 'Yes' : 'No'}`));
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
        initConfig.envExample = generateEnvExample(initConfig);
        initConfig.dockerCompose = generateDockerCompose(initConfig);
        initConfig.integrationCode = generateIntegrationCode(initConfig, projectInfo.type);
        const gatewayConfigJson = generateGatewayConfig(initConfig);
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
        const canOverwrite = await confirmOverwrites(filePaths, options.force ?? false);
        if (!canOverwrite) {
            console.log(chalk.yellow('Init cancelled. No files were modified.'));
            return;
        }
        // Write files
        const writeSpinner = ora('Writing configuration files...').start();
        for (const file of filesToCreate) {
            await writeFileSafe(file.path, file.content);
        }
        writeSpinner.succeed(chalk.green('Configuration files created!'));
        // Summary
        console.log(chalk.bold('\n✅ ICO-Cache initialized successfully!'));
        console.log(chalk.gray('\nCreated files:'));
        for (const file of filesToCreate) {
            console.log(chalk.gray(`  ${file.path}`));
        }
        console.log(chalk.bold('\n📋 Next steps:'));
        console.log(chalk.gray('  1. Copy .env.example to .env and fill in your API keys:'));
        console.log(chalk.cyan('     cp .env.example .env'));
        console.log(chalk.gray('  2. Edit .env with your API keys'));
        console.log(chalk.gray('  3. Start ICO-Cache locally:'));
        console.log(chalk.cyan('     ico-cache start'));
        console.log(chalk.gray('  4. Or start with Docker Compose:'));
        console.log(chalk.cyan('     docker compose -f docker-compose.yml -f docker-compose.override.yml up -d'));
        console.log(chalk.gray('  5. Test the integration:'));
        if (projectInfo.type === 'python' || projectInfo.type === 'mixed') {
            console.log(chalk.cyan('     python ico_cache_integration.py'));
        }
        if (projectInfo.type === 'node' || projectInfo.type === 'mixed') {
            console.log(chalk.cyan('     node ico_cache_integration.js'));
        }
        console.log(chalk.bold('\n📚 Documentation:'));
        console.log(chalk.gray('  - QUICKSTART.md - 5-minute quickstart guide'));
        console.log(chalk.gray('  - CLI_IMPLEMENTATION.md - CLI implementation details'));
    }
    catch (error) {
        spinner.fail(chalk.red('Failed to initialize ICO-Cache'));
        console.error(chalk.red(error instanceof Error ? error.message : String(error)));
        process.exit(1);
    }
});
