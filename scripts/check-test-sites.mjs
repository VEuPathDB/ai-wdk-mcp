#!/usr/bin/env node
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export const ALLOWED = [
  "README.md",
  "data/catalogs/",
  "docs/",
  "fixtures-production-backup-2026-10-09/",
];

export const SITE_DOMAINS = [
  "veupathdb",
  "eupathdb",
  "plasmodb",
  "toxodb",
  "cryptodb",
  "giardiadb",
  "amoebadb",
  "microsporidiadb",
  "piroplasmadb",
  "tritrypdb",
  "trichdb",
  "fungidb",
  "vectorbase",
  "hostdb",
  "orthomcl",
];

const SKIPPED_DIRS = new Set([
  ".git",
  ".venv",
  "node_modules",
  "__pycache__",
  ".mypy_cache",
  ".ruff_cache",
  ".pytest_cache",
  ".hypothesis",
  "dist",
  "build",
]);

const HOST = new RegExp(
  String.raw`(?<![A-Za-z0-9.-])((?:[A-Za-z0-9-]+\.)*)(${SITE_DOMAINS.join("|")})\.org\b`,
  "gi",
);
const QA_PREFIX = /(?:^|\.)(?:qa|q2)\.$/i;

export function productionHosts(text) {
  const found = [];
  text.split("\n").forEach((line, index) => {
    for (const match of line.matchAll(HOST)) {
      if (!QA_PREFIX.test(match[1])) {
        found.push({ line: index + 1, host: match[0].toLowerCase() });
      }
    }
  });
  return found;
}

export function isAllowed(path) {
  return ALLOWED.some((entry) => (entry.endsWith("/") ? path.startsWith(entry) : path === entry));
}

export function ignoredNames(gitignore) {
  return gitignore
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "" && !line.startsWith("#") && !line.slice(0, -1).includes("/"))
    .map((line) => line.replace(/\/$/, ""));
}

function matchesName(name, patterns) {
  return patterns.some((pattern) =>
    pattern.startsWith("*") ? name.endsWith(pattern.slice(1)) : name === pattern,
  );
}

export function scannedPaths(root, ignored) {
  const paths = [];
  const walk = (directory) => {
    for (const name of readdirSync(directory).sort()) {
      const full = join(directory, name);
      const path = relative(root, full).split(sep).join("/");
      const isDirectory = statSync(full).isDirectory();
      if (isDirectory && SKIPPED_DIRS.has(name)) continue;
      if (matchesName(name, ignored)) continue;
      if (isAllowed(isDirectory ? `${path}/` : path)) continue;
      if (isDirectory) walk(full);
      else paths.push(path);
    }
  };
  walk(root);
  return paths;
}

export function offencesIn(files) {
  const offences = [];
  for (const [path, text] of files) {
    for (const { line, host } of productionHosts(text)) {
      offences.push(`${path}:${line}: names the production host ${host}; a test, a recorder and a default reach the QA sites only`);
    }
  }
  return offences;
}

function main() {
  let gitignore = "";
  try {
    gitignore = readFileSync(join(ROOT, ".gitignore"), "utf8");
  } catch {
    gitignore = "";
  }
  const paths = scannedPaths(ROOT, ignoredNames(gitignore));
  const offences = offencesIn(paths.map((path) => [path, readFileSync(join(ROOT, path), "utf8")]));
  for (const offence of offences) console.error(offence);
  if (offences.length > 0) {
    console.error(`check-test-sites: ${offences.length} production host(s) outside ${ALLOWED.join(", ")}`);
    process.exit(1);
  }
  console.log(`check-test-sites: ${paths.length} file(s), no production host outside ${ALLOWED.join(", ")}`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
