import { ProjectInfo } from './project-detection.js';
export interface ProviderConfig {
    provider: 'openai' | 'anthropic' | 'gemini' | 'ollama' | 'custom';
    model: string;
    apiKey?: string;
    baseUrl?: string;
}
export interface GatewayConfig {
    enabled: boolean;
    port: number;
    host: string;
    apiKeys: Record<string, string>;
}
export interface InitConfig {
    projectName: string;
    projectType: ProjectInfo['type'];
    provider: ProviderConfig;
    gateway: GatewayConfig;
    envExample: string;
    dockerCompose: string;
    integrationCode: string;
}
export declare function getProviderTemplates(): Record<string, {
    models: string[];
    defaultModel: string;
    envVar: string;
}>;
export declare function generateEnvExample(config: InitConfig): string;
export declare function generateDockerCompose(config: InitConfig): string;
export declare function generateIntegrationCode(config: InitConfig, projectType: ProjectInfo['type']): string;
export declare function generateGatewayConfig(config: InitConfig): string;
