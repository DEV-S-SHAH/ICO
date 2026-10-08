import * as fs from 'fs/promises';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export type ProjectType = 'python' | 'node' | 'mixed' | 'unknown';

export interface ProjectInfo {
  type: ProjectType;
  hasPackageJson: boolean;
  hasPyprojectToml: boolean;
  hasRequirementsTxt: boolean;
  hasDockerCompose: boolean;
  packageManager: 'npm' | 'yarn' | 'pnpm' | 'uv' | 'pip' | 'unknown';
  rootDir: string;
}

export async function detectProject(rootDir: string = process.cwd()): Promise<ProjectInfo> {
  const checks = await Promise.all([
    fs.access(path.join(rootDir, 'package.json')).then(() => true).catch(() => false),
    fs.access(path.join(rootDir, 'pyproject.toml')).then(() => true).catch(() => false),
    fs.access(path.join(rootDir, 'requirements.txt')).then(() => true).catch(() => false),
    fs.access(path.join(rootDir, 'docker-compose.yml')).then(() => true).catch(() => false),
    fs.access(path.join(rootDir, 'docker-compose.yaml')).then(() => true).catch(() => false),
  ]);

  const [hasPackageJson, hasPyprojectToml, hasRequirementsTxt, hasDockerComposeYml, hasDockerComposeYaml] = checks;
  const hasDockerCompose = hasDockerComposeYml || hasDockerComposeYaml;

  let type: ProjectType = 'unknown';
  let packageManager: ProjectInfo['packageManager'] = 'unknown';

  if (hasPackageJson && (hasPyprojectToml || hasRequirementsTxt)) {
    type = 'mixed';
    // Check package manager for node
    const packageJsonPath = path.join(rootDir, 'package.json');
    const packageJsonContent = await fs.readFile(packageJsonPath, 'utf-8').catch(() => '{}');
    const packageJson = JSON.parse(packageJsonContent);
    
    if (packageJson.packageManager) {
      const pm = packageJson.packageManager.toLowerCase();
      if (pm.startsWith('yarn')) packageManager = 'yarn';
      else if (pm.startsWith('pnpm')) packageManager = 'pnpm';
      else if (pm.startsWith('npm')) packageManager = 'npm';
    } else if (await fs.access(path.join(rootDir, 'yarn.lock')).then(() => true).catch(() => false)) {
      packageManager = 'yarn';
    } else if (await fs.access(path.join(rootDir, 'pnpm-lock.yaml')).then(() => true).catch(() => false)) {
      packageManager = 'pnpm';
    } else {
      packageManager = 'npm';
    }
  } else if (hasPackageJson) {
    type = 'node';
    const packageJsonPath = path.join(rootDir, 'package.json');
    const packageJsonContent = await fs.readFile(packageJsonPath, 'utf-8').catch(() => '{}');
    const packageJson = JSON.parse(packageJsonContent);
    
    if (packageJson.packageManager) {
      const pm = packageJson.packageManager.toLowerCase();
      if (pm.startsWith('yarn')) packageManager = 'yarn';
      else if (pm.startsWith('pnpm')) packageManager = 'pnpm';
      else if (pm.startsWith('npm')) packageManager = 'npm';
    } else if (await fs.access(path.join(rootDir, 'yarn.lock')).then(() => true).catch(() => false)) {
      packageManager = 'yarn';
    } else if (await fs.access(path.join(rootDir, 'pnpm-lock.yaml')).then(() => true).catch(() => false)) {
      packageManager = 'pnpm';
    } else {
      packageManager = 'npm';
    }
  } else if (hasPyprojectToml || hasRequirementsTxt) {
    type = 'python';
    if (await fs.access(path.join(rootDir, 'uv.lock')).then(() => true).catch(() => false)) {
      packageManager = 'uv';
    } else {
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

export async function getProjectName(rootDir: string = process.cwd()): Promise<string> {
  // Try package.json first
  const packageJsonPath = path.join(rootDir, 'package.json');
  try {
    const content = await fs.readFile(packageJsonPath, 'utf-8');
    const pkg = JSON.parse(content);
    if (pkg.name) return pkg.name;
  } catch {}

  // Try pyproject.toml
  const pyprojectPath = path.join(rootDir, 'pyproject.toml');
  try {
    const content = await fs.readFile(pyprojectPath, 'utf-8');
    const match = content.match(/name\s*=\s*["']([^"']+)["']/);
    if (match) return match[1];
  } catch {}

  // Fallback to directory name
  return path.basename(rootDir);
}