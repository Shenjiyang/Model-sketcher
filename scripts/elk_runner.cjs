#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

function loadElk() {
  const explicit = process.env.ELKJS_MODULE;
  const candidates = [
    explicit,
    "elkjs/lib/elk.bundled.js",
    path.join(__dirname, "..", "vendor", "elk", "node_modules", "elkjs", "lib", "elk.bundled.js"),
  ].filter(Boolean);
  let lastError;
  for (const candidate of candidates) {
    try {
      const resolved = require.resolve(candidate);
      let directory = path.dirname(resolved);
      while (directory !== path.dirname(directory)) {
        const manifest = path.join(directory, "package.json");
        if (fs.existsSync(manifest)) {
          const metadata = JSON.parse(fs.readFileSync(manifest, "utf8"));
          if (metadata.name === "elkjs") {
            return {ELK: require(candidate), version: metadata.version};
          }
        }
        directory = path.dirname(directory);
      }
      throw new Error(`elkjs package metadata not found for ${resolved}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(
    `Unable to load elkjs. Install it locally or set ELKJS_MODULE. Last error: ${lastError?.message}`
  );
}

async function main() {
  if (process.argv.length !== 4) {
    throw new Error("usage: elk_runner.cjs INPUT.json OUTPUT.json");
  }
  const [inputPath, outputPath] = process.argv.slice(2);
  const graph = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const {ELK, version} = loadElk();
  const result = await new ELK().layout(graph);
  result._modelSketcherLayoutEngine = {name: "elk-layered", elkjsVersion: version};
  fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
}

main().catch((error) => {
  process.stderr.write(`ELK layout failed: ${error.stack || error.message}\n`);
  process.exitCode = 1;
});
