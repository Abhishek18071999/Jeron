// Draws the Mermaid diagrams in the pandoc HTML, then prints it to an A4 PDF.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [html, out] = process.argv.slice(2);
  let page_html = fs.readFileSync(html, 'utf8');
  // pandoc writes ```mermaid blocks as <pre class="mermaid"><code>...</code></pre>
  page_html = page_html.replace(/<pre class="mermaid"><code>([\s\S]*?)<\/code><\/pre>/g,
    (_, body) => `<pre class="mermaid">${body}</pre>`);
  page_html = page_html.replace('</body>', `
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"></script>
<script>
  mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'loose',
    flowchart: { htmlLabels: true, useMaxWidth: true }, fontFamily: 'Segoe UI, sans-serif' });
  mermaid.run({ querySelector: 'pre.mermaid' }).then(() => { window.__done = true; })
    .catch(e => { window.__error = (e && (e.message || e.str)) || JSON.stringify(e); window.__done = true; });
</script></body>`);
  fs.writeFileSync(html, page_html);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + require('path').resolve(html), { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.__done === true, null, { timeout: 60000 });
  const err = await page.evaluate(() => window.__error);
  if (err) { console.error('Mermaid error: ' + err); process.exit(1); }
  const bad = await page.evaluate(() => document.querySelectorAll('pre.mermaid:not([data-processed])').length);
  if (bad) { console.error(bad + ' diagrams not drawn'); process.exit(1); }
  await page.pdf({ path: out, format: 'A4', printBackground: true,
    margin: { top: '18mm', bottom: '20mm', left: '16mm', right: '16mm' },
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:8px;color:#888;width:100%;text-align:center;">Jeron architecture · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>' });
  await browser.close();
  console.log('wrote ' + out);
})().catch(e => { console.error(e); process.exit(1); });
