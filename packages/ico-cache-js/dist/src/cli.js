#!/usr/bin/env node
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const commander_1 = require("commander");
const init_js_1 = require("./commands/init.js");
const start_js_1 = require("./commands/start.js");
const connect_js_1 = require("./commands/connect.js");
const package_json_1 = require("../package.json");
commander_1.program
    .name('ico-cache')
    .description('ICO-Cache CLI - Semantic caching middleware for LLM applications')
    .version(package_json_1.version)
    .helpOption('-h, --help', 'Display help for command');
commander_1.program.addCommand(init_js_1.initCommand);
commander_1.program.addCommand(start_js_1.startCommand);
commander_1.program.addCommand(connect_js_1.connectCommand);
commander_1.program.parseAsync(process.argv).catch((err) => {
    console.error(err);
    process.exit(1);
});
