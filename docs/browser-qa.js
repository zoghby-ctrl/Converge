// HISTORICAL UI SCRIPT: retired selectors. Current release instructions and selectors: docs/browser-release-qa.js.
// Run with playwright-cli run-code --filename docs/browser-qa.js after opening the app.
async (page) => {
  const failures = [];
  const externalRequests = [];
  const consoleErrors = [];
  const failedResources = [];
  page.on('pageerror', e => consoleErrors.push(e.message));
  page.on('console', message => {if (message.type() === 'error') consoleErrors.push(message.text());});
  page.context().on('response', response => {if (response.status() >= 400) failedResources.push(response.url() + ' ' + response.status());});
  await page.context().route('**/*', route => {
    const url = route.request().url();
    if (/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?\//.test(url)) return route.continue();
    externalRequests.push(url);
    return route.abort('internetdisconnected');
  });
  await page.goto(page.url().split('/').slice(0, 3).join('/'));
  await page.getByRole('button', {name: 'Reset', exact: true}).waitFor();
  const click = async name => {
    const [response] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/demo/replay') && r.request().method() === 'POST'),
      page.getByRole('button', {name, exact: true}).click()
    ]);
    if (!response.ok()) throw new Error(await response.text());
    const result = await response.json();
    await page.getByText(`Step ${result.step} / ${result.total_steps} · availability controls replay`, {exact: true}).waitFor();
    return result;
  };
  await click('Reset');
  let state = await click('Start replay');
  if (state.signals.length !== 1) failures.push('Start revealed future observations');
  state = await click('Advance');
  await page.getByRole('button', {name: 'Location A 25–75 /100 water observation 1 capture · 8 records Limited · provisional', exact: true}).waitFor();
  while (state.step < state.total_steps) state = await click('Advance');
  const candidate = state.incidents.find(i => i.status === 'candidate');
  if (candidate.risk.display !== '68' || candidate.independent_capture_count !== 3) failures.push('Signature result');
  await page.getByRole('button', {name: 'Location B 68 /100 water + road condition 3 captures · 3 records Moderate · inspect first', exact: true}).click();
  await page.getByText('Local vector map ready', {exact: true}).waitFor();
  await page.getByRole('button', {name: 'Select map Location A', exact: true}).click();
  await page.getByRole('heading', {name: 'Location A · simulated study segment', exact: true}).waitFor();
  await page.getByRole('button', {name: 'Select map Location B', exact: true}).click();
  await page.getByRole('heading', {name: 'Location B · simulated study segment', exact: true}).waitFor();
  await page.setViewportSize({width: 1440, height: 900});
  await page.screenshot({path: 'output/playwright/phase1-signature-1440.png', fullPage: true});
  await page.setViewportSize({width: 1280, height: 720});
  await page.screenshot({path: 'output/playwright/phase1-signature-1280.png', fullPage: true});
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) failures.push('Horizontal overflow at 1280');
  const change = async (name, checked) => {
    const [response] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/demo/compare')),
      page.getByRole('checkbox', {name, exact: true}).setChecked(checked)
    ]);
    if (!response.ok()) throw new Error(await response.text());
    return response.json();
  };
  let comparison = await change('Hide image evidence', true);
  let b = comparison.incidents.find(i => i.status === 'candidate');
  if (b.risk.display !== '52–83' || b.evidence_strength !== 'Limited') failures.push('Image ablation');
  await page.getByRole('button', {name: 'Location B 52–83 /100 water observation 2 captures · 2 records Limited · provisional', exact: true}).waitFor();
  await page.screenshot({path: 'output/playwright/phase1-ablation-1280.png', fullPage: true});
  await change('Hide image evidence', false);
  comparison = await change('Add 10 duplicates', true);
  for (const before of comparison.baseline) {
    const after = comparison.incidents.find(i => i.incident_id === before.incident_id);
    if (JSON.stringify(before.risk) !== JSON.stringify(after.risk) ||
        JSON.stringify(before.hypotheses) !== JSON.stringify(after.hypotheses) ||
        before.independent_capture_count !== after.independent_capture_count) failures.push('Duplicate inflation');
  }
  await change('Add 10 duplicates', false);
  await page.getByRole('button', {name: 'Open record b-water-first', exact: true}).click();
  await page.getByText('في مياه متجمعة جنب الرصيف ومش عارفين سببها.', {exact: true}).waitFor();
  await page.getByRole('button', {name: 'Close record', exact: true}).click();
  const reset = await click('Reset');
  if (reset.signals.length || reset.incidents.length || reset.step) failures.push('Reset did not clear replay');
  state = await click('Start replay');
  while (state.step < state.total_steps) state = await click('Advance');
  await page.reload();
  await page.getByText('Step 6 / 6 · availability controls replay', {exact: true}).waitFor();
  await page.getByRole('button', {name: 'Location B 68 /100 water + road condition 3 captures · 3 records Moderate · inspect first', exact: true}).waitFor();
  const mapCanvas = page.getByRole('region', {name: 'Map', exact: true});
  if (!(await mapCanvas.isVisible())) failures.push('Map not visible');
  if (externalRequests.length) failures.push('External asset request attempted');
  if (consoleErrors.length) failures.push('Browser console errors');
  if (failedResources.length) failures.push('Failed local resources');
  const report = {checks: ['start', 'stepwise complete replay', 'eight copies at A', 'B candidate', 'C separate', 'map selection',
      '1280 layout', 'image ablation', 'ten-duplicate invariance', 'Arabic original record', 'reset', 'repeat replay',
      'production reload', 'external network blocked', 'local map visible'],
      failures, externalRequests, consoleErrors, failedResources, finalStep: state.step};
  if (failures.length) throw new Error(failures.join('; '));
  return report;
}
