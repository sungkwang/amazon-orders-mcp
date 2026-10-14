// List one year of Amazon orders using the session saved by cookie_capture.py.
// Read-only: loads order-history pages and never clicks, buys, or changes anything.
// Usage: node tools/list-orders/list-orders-by-year.mjs <year> [output.json]
import fs from "fs";
import os from "os";
import path from "path";
import { chromium } from "patchright";

const year = process.argv[2];
if (!/^\d{4}$/.test(year || "")) {
  console.error("Usage: node list-orders-by-year.mjs <year> [output.json]");
  process.exit(1);
}
const out = process.argv[3] || `orders_${year}.json`;
const cookiesFile = path.join(os.homedir(), ".amazon-orders-mcp", "cookies.json");
const cookies = JSON.parse(fs.readFileSync(cookiesFile, "utf8"));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
await context.addCookies(cookies);
const page = await context.newPage();

const all = [];
const seen = new Set();
for (let start = 0; start < 1000; start += 10) {
  const url = `https://www.amazon.com/your-orders/orders?timeFilter=year-${year}&startIndex=${start}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(1500);
  if (/ap\/signin/.test(page.url())) {
    await browser.close();
    throw new Error("Amazon did not accept the saved session. Run cookie_capture.py again.");
  }
  const text = await page.evaluate(() => document.body.innerText);
  const chunks = text.split(/ORDER PLACED/).slice(1);
  let added = 0;
  for (const chunk of chunks) {
    const id = (chunk.match(/\d{3}-\d{7}-\d{7}/) || [])[0];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    added++;
    all.push({
      orderId: id,
      orderDate: (chunk.match(/^\s*([A-Z][a-z]+ \d{1,2}, \d{4})/) || [])[1] || "",
      total: (chunk.match(/TOTAL\s*\n?\s*(\$[\d,]+\.\d{2})/) || [])[1] || "",
      raw: chunk.slice(0, 5000),
    });
  }
  if (added === 0) break;
}
await browser.close();
fs.writeFileSync(out, JSON.stringify(all, null, 2));
console.log(`${all.length} orders written to ${out}`);
