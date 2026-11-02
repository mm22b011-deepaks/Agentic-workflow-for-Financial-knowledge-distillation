import { compile } from "json-schema-to-typescript";
import { readFile, writeFile } from "node:fs/promises";
import Ajv2020 from "ajv/dist/2020.js";
import standaloneModule from "ajv/dist/standalone/index.js";
const names = [
  "SettingsResponse",
  "SessionResponse",
  "KPIKnowledgeBase",
  "Registry",
  "CanvasRegistry",
  "GraphDocument",
  "StageSnapshot",
  "PaneResponse",
  "MetricSnapshot",
  "EvidenceResponse",
  "LabelRequest",
  "LabelResponse",
  "RunRequest",
  "RunStatus",
  "RunEvent",
  "IndexSnapshot",
  "ScheduleSnapshot",
];
const ajv = new Ajv2020({ strict: false, code: { source: true, esm: true } });
for (const name of names) {
  const schema = JSON.parse(
    await readFile(
      new URL(`../../schemas/${name}.json`, import.meta.url),
      "utf8",
    ),
  );
  await writeFile(
    new URL(`../src/${name}.d.ts`, import.meta.url),
    await compile(schema, name),
  );
  ajv.addSchema(schema, name);
}
const standalone =
  typeof standaloneModule === "function"
    ? standaloneModule
    : standaloneModule.default;
await writeFile(
  new URL("../src/validators.js", import.meta.url),
  standalone(
    ajv,
    Object.fromEntries(names.map((name) => ["valid" + name, name])),
  ),
);
await writeFile(
  new URL("../src/validators.d.ts", import.meta.url),
  `import type {ValidateFunction} from 'ajv';\n${names.map((name) => `import type {${name}} from './${name}';\nexport const valid${name}:ValidateFunction<${name}>;`).join("\n")}\n`,
);
