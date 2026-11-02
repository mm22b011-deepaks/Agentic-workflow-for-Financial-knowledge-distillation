import {compile} from 'json-schema-to-typescript';
import {readFile,writeFile} from 'node:fs/promises';
const names=['Registry','RunRequest','RunStatus','RunEvent','IndexSnapshot'];
for(const name of names) {
 const schema=JSON.parse(await readFile(new URL(`../../schemas/${name}.json`,import.meta.url),'utf8'));
 await writeFile(new URL(`../src/${name}.d.ts`,import.meta.url),await compile(schema,name));
}
const {default:Ajv2020}=await import('ajv/dist/2020.js');
const {default:standaloneModule}=await import('ajv/dist/standalone/index.js');
const ajv=new Ajv2020({strict:false,code:{source:true,esm:true}});
for(const name of ['Registry','IndexSnapshot']) {
 const schema=JSON.parse(await readFile(new URL(`../../schemas/${name}.json`,import.meta.url),'utf8'));
 ajv.addSchema(schema,name);
}
const standalone=typeof standaloneModule==='function'?standaloneModule:standaloneModule.default;
await writeFile(new URL('../src/validators.js',import.meta.url),standalone(ajv,{validRegistry:'Registry',validIndex:'IndexSnapshot'}));
await writeFile(new URL('../src/validators.d.ts',import.meta.url),`import type {ValidateFunction} from 'ajv';
import type {Registry} from './Registry';
import type {IndexSnapshot} from './IndexSnapshot';
export const validRegistry:ValidateFunction<Registry>;
export const validIndex:ValidateFunction<IndexSnapshot>;
`);
