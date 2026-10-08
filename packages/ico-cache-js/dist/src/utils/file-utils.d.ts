export declare function fileExists(filePath: string): Promise<boolean>;
export declare function readFileSafe(filePath: string): Promise<string | null>;
export declare function writeFileSafe(filePath: string, content: string): Promise<void>;
export declare function copyTemplate(templateName: string, destination: string, replacements?: Record<string, string>): Promise<void>;
export declare function confirmOverwrite(filePath: string): Promise<boolean>;
export declare function getTemplatePath(templateName: string): string;
