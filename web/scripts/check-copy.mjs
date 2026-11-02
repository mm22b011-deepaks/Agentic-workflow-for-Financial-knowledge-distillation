import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const errors = [];
async function inspect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) await inspect(path);
    else if (path.endsWith(".tsx")) {
      const source = ts.createSourceFile(
        path,
        await readFile(path, "utf8"),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      function visit(node) {
        if (ts.isJsxText(node) && /[\p{L}\p{N}]/u.test(node.text))
          errors.push(path);
        if (
          ts.isJsxAttribute(node) &&
          ["placeholder", "title", "alt", "aria-label"].includes(
            node.name.getText(source),
          ) &&
          node.initializer &&
          ts.isStringLiteral(node.initializer) &&
          /[\p{L}\p{N}]/u.test(node.initializer.text)
        )
          errors.push(path);
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
}
await inspect(fileURLToPath(new URL("../src", import.meta.url)));
if (errors.length) {
  console.error([...new Set(errors)].join("\n"));
  process.exitCode = 1;
}
