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
Object.defineProperty(exports, "__esModule", { value: true });
exports.detectProject = detectProject;
exports.getProjectName = getProjectName;
const fs = __importStar(require("fs/promises"));
const path = __importStar(require("path"));
const url_1 = require("url");
const __filename = (0, url_1.fileURLToPath)(import.meta.url);
const __dirname = path.dirname(__filename);
async function detectProject(rootDir = process.cwd()) {
    const checks = await Promise.all([
        fs.access(path.join(rootDir, 'package.json')).then(() => true).catch(() => false),
        fs.access(path.join(rootDir, 'pyproject.toml')).then(() => true).catch(() => false),
        fs.access(path.join(rootDir, 'requirements.txt')).then(() => true).catch(() => false),
        fs.access(path.join(rootDir, 'docker-compose.yml')).then(() => true).catch(() => false),
        fs.access(path.join(rootDir, 'docker-compose.yaml')).then(() => true).catch(() => false),
    ]);
    const [hasPackageJson, hasPyprojectToml, hasRequirementsTxt, hasDockerComposeYml, hasDockerComposeYaml] = checks;
    const hasDockerCompose = hasDockerComposeYml || hasDockerComposeYaml;
    let type = 'unknown';
    let packageManager = 'unknown';
    if (hasPackageJson && (hasPyprojectToml || hasRequirementsTxt)) {
        type = 'mixed';
        // Check package manager for node
        const packageJsonPath = path.join(rootDir, 'package.json');
        const packageJsonContent = await fs.readFile(packageJsonPath, 'utf-8').catch(() => '{}');
        const packageJson = JSON.parse(packageJsonContent);
        if (packageJson.packageManager) {
            const pm = packageJson.packageManager.toLowerCase();
            if (pm.startsWith('yarn'))
                packageManager = 'yarn';
            else if (pm.startsWith('pnpm'))
                packageManager = 'pnpm';
            else if (pm.startsWith('npm'))
                packageManager = 'npm';
        }
        else if (await fs.access(path.join(rootDir, 'yarn.lock')).then(() => true).catch(() => false)) {
            packageManager = 'yarn';
        }
        else if (await fs.access(path.join(rootDir, 'pnpm-lock.yaml')).then(() => true).catch(() => false)) {
            packageManager = 'pnpm';
        }
        else {
            packageManager = 'npm';
        }
    }
    else if (hasPackageJson) {
        type = 'node';
        const packageJsonPath = path.join(rootDir, 'package.json');
        const packageJsonContent = await fs.readFile(packageJsonPath, 'utf-8').catch(() => '{}');
        const packageJson = JSON.parse(packageJsonContent);
        if (packageJson.packageManager) {
            const pm = packageJson.packageManager.toLowerCase();
            if (pm.startsWith('yarn'))
                packageManager = 'yarn';
            else if (pm.startsWith('pnpm'))
                packageManager = 'pnpm';
            else if (pm.startsWith('npm'))
                packageManager = 'npm';
        }
        else if (await fs.access(path.join(rootDir, 'yarn.lock')).then(() => true).catch(() => false)) {
            packageManager = 'yarn';
        }
        else if (await fs.access(path.join(rootDir, 'pnpm-lock.yaml')).then(() => true).catch(() => false)) {
            packageManager = 'pnpm';
        }
        else {
            packageManager = 'npm';
        }
    }
    else if (hasPyprojectToml || hasRequirementsTxt) {
        type = 'python';
        if (await fs.access(path.join(rootDir, 'uv.lock')).then(() => true).catch(() => false)) {
            packageManager = 'uv';
        }
        else {
            packageManager = 'pip';
        }
    }
    return {
        type,
        hasPackageJson,
        hasPyprojectToml,
        hasRequirementsTxt,
        hasDockerCompose,
        packageManager,
        rootDir,
    };
}
async function getProjectName(rootDir = process.cwd()) {
    // Try package.json first
    const packageJsonPath = path.join(rootDir, 'package.json');
    try {
        const content = await fs.readFile(packageJsonPath, 'utf-8');
        const pkg = JSON.parse(content);
        if (pkg.name)
            return pkg.name;
    }
    catch { }
    // Try pyproject.toml
    const pyprojectPath = path.join(rootDir, 'pyproject.toml');
    try {
        const content = await fs.readFile(pyprojectPath, 'utf-8');
        const match = content.match(/name\s*=\s*["']([^"']+)["']/);
        if (match)
            return match[1];
    }
    catch { }
    // Fallback to directory name
    return path.basename(rootDir);
}
