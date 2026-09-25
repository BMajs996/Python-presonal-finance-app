import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("frontend/vendor", { recursive: true });
for (const [source, target] of [
  ["dist/chart.umd.js", "chart.umd.js"],
  ["LICENSE.md", "Chart.js.LICENSE.md"],
]) {
  copyFileSync("node_modules/chart.js/" + source, "frontend/vendor/" + target);
}
