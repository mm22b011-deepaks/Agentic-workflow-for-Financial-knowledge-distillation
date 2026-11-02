import type {ValidateFunction} from 'ajv';
import type {Registry} from './Registry';
import type {IndexSnapshot} from './IndexSnapshot';
export const validRegistry:ValidateFunction<Registry>;
export const validIndex:ValidateFunction<IndexSnapshot>;
