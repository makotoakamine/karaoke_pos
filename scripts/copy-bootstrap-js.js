// Copies Bootstrap's bundled JS (Popper included) into static/vendor so it is
// served locally by Django rather than from a CDN.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "node_modules", "bootstrap", "dist", "js", "bootstrap.bundle.min.js");
const DEST_DIR = path.join(__dirname, "..", "static", "vendor", "js");
const DEST = path.join(DEST_DIR, "bootstrap.bundle.min.js");

fs.mkdirSync(DEST_DIR, { recursive: true });
fs.copyFileSync(SRC, DEST);
console.log(`Copied ${path.relative(path.join(__dirname, ".."), SRC)} -> ${path.relative(path.join(__dirname, ".."), DEST)}`);