import * as fs from 'fs/promises';
import * as path from 'path';
import { fileURLToPath } from 'url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export async function fileExists(filePath) {
    try {
        await fs.access(filePath);
        return true;
    }
    catch {
        return false;
    }
}
export async function readFileSafe(filePath) {
    try {
        return await fs.readFile(filePath, 'utf-8');
    }
    catch {
        return null;
    }
}
export async function writeFileSafe(filePath, content) {
    const dir = path.dirname(filePath);
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(filePath, content, 'utf-8');
}
export async function copyTemplate(templateName, destination, replacements = {}) {
    const templatePath = path.join(__dirname, '..', 'templates', templateName);
    let content = await fs.readFile(templatePath, 'utf-8');
    for (const [key, value] of Object.entries(replacements)) {
        content = content.replace(new RegExp(`{{${key}}}`, 'g'), value);
    }
    await writeFileSafe(destination, content);
}
export async function confirmOverwrite(filePath) {
    const exists = await fileExists(filePath);
    if (!exists)
        return true;
    // This will be handled by inquirer in the actual command
    return false;
}
export function getTemplatePath(templateName) {
    return path.join(__dirname, '..', 'templates', templateName);
}
