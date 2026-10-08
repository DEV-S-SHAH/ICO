export interface IcoCacheOptions {
    baseUrl: string;
    apiKey?: string;
    semanticThreshold?: number;
}
export declare class IcoCache {
    private baseUrl;
    private apiKey?;
    constructor(options: IcoCacheOptions);
    private request;
    resolve<T>(query: string, context: string | null, callback: () => Promise<T>): Promise<T>;
    query(query: string, context?: string | null): Promise<{
        source: string;
        response: unknown;
    }>;
    ingest(query: string, context: string | null, response: unknown): Promise<void>;
    health(): Promise<{
        status: string;
        backends: Record<string, string>;
    }>;
}
export declare function icoCache(options: IcoCacheOptions): IcoCache;
