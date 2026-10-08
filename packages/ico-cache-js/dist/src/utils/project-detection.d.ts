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
export declare function detectProject(rootDir?: string): Promise<ProjectInfo>;
export declare function getProjectName(rootDir?: string): Promise<string>;
