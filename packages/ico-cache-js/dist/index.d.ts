export interface IcoCacheOptions {
    baseUrl: string;
    semanticThreshold?: number;
}
export declare class IcoCache {
    private baseUrl;
    constructor(options: IcoCacheOptions);
    resolve<T>(query: string, context: string | null, callback: () => Promise<T>): Promise<T>;
}
export declare function icoCache(options: IcoCacheOptions): IcoCache;
