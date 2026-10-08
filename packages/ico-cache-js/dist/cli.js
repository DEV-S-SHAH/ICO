#!/usr/bin/env node
import { program } from 'commander';
import { initCommand } from './commands/init.js';
import { startCommand } from './commands/start.js';
import { connectCommand } from './commands/connect.js';
import * as fs from 'fs/promises';
import * as path from 'path';
import { fileURLToPath } from 'url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const packageJson = JSON.parse(await fs.readFile(path.join(__dirname, '..', 'package.json'), 'utf-8'));
const version = packageJson.version;
program
    .name('ico-cache')
    .description('ICO-Cache CLI - Semantic caching middleware for LLM applications')
    .version(version)
    .helpOption('-h, --help', 'Display help for command');
program.addCommand(initCommand);
program.addCommand(startCommand);
program.addCommand(connectCommand);
program.parseAsync(process.argv).catch((err) => {
    console.error(err);
    process.exit(1);
});
