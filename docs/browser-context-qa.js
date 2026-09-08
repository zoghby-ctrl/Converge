// HISTORICAL UI SCRIPT: retired selectors. Current release instructions and selectors: docs/browser-release-qa.js.
// Run against a disposable local runtime with the OpenAI key blank.
async (page) => {
  const externalRequests = [], consoleErrors = [], failures = [];
  page.on('pageerror', e => consoleErrors.push(e.message));
  page.on('console', m => {if (m.type() === 'error') consoleErrors.push(m.text());});
  await page.context().route('**/*', route => {
    if (/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?\//.test(route.request().url())) return route.continue();
    externalRequests.push(route.request().url());
    return route.abort('internetdisconnected');
  });
  await page.reload();
  await page.setViewportSize({width: 1280, height: 720});
  const click = async name => {
    const [response] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/demo/replay') && r.request().method() === 'POST'),
      page.getByRole('button', {name, exact: true}).click()
    ]);
    if (!response.ok()) throw new Error(await response.text());
    const state = await response.json();
    await page.getByText(`Step ${state.step} / ${state.total_steps} · availability controls replay`, {exact: true}).waitFor();
    return state;
  };
  const states = [];
  for (const scenario of ['context_signature', 'context_archive']) {
    await page.getByRole('combobox', {name: 'Scenario', exact: true}).selectOption(scenario);
    await click('Reset');
    let state = await click('Start replay');
    while (state.step < state.total_steps) state = await click('Advance');
    const candidate = state.incidents.find(i => i.status === 'candidate');
    if (candidate.risk.display !== '68' || candidate.independent_capture_count !== 3) failures.push('Candidate result');
    await page.getByRole('button', {name: /Ali Amin Street 68/}).click();
    await page.getByText('Local vector map ready', {exact: true}).waitFor();
    await page.getByRole('link', {name: '© OpenStreetMap contributors · ODbL', exact: true}).waitFor();
    await page.getByText('Rainfall / road context', {exact: true}).scrollIntoViewIfNeeded();
    if (scenario === 'context_archive') {
      await page.getByRole('link', {name: 'Open-Meteo / ERA5 · CC BY 4.0', exact: true}).waitFor();
      if (!(await page.getByText(/Retrospective context in a synthetic replay; not available as-issued/).isVisible())) failures.push('Retrospective disclosure');
    }
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) failures.push('Horizontal overflow');
    await page.screenshot({path: `output/playwright/phase3-${scenario}.png`, fullPage: true});
    states.push({scenario, captures: candidate.independent_capture_count, risk: candidate.risk.display,
      rainfall: candidate.features.rainfall_context.value, road: candidate.road_name});
  }
  await page.getByRole('checkbox', {name: 'Hide image evidence', exact: true}).check();
  await page.getByRole('button', {name: /Ali Amin Street 52–83/}).waitFor();
  await page.getByRole('checkbox', {name: 'Hide image evidence', exact: true}).uncheck();
  await page.getByRole('button', {name: /Ali Amin Street 68/}).waitFor();
  await page.getByRole('checkbox', {name: 'Add 10 duplicates', exact: true}).check();
  await page.getByText('Sandbox comparison · all families · 10 added copies. Original replay remains intact.', {exact: true}).waitFor();
  await page.getByRole('button', {name: /Ali Amin Street 68/}).waitFor();
  await page.getByRole('checkbox', {name: 'Add 10 duplicates', exact: true}).uncheck();
  await page.reload();
  await page.getByRole('button', {name: /Ali Amin Street 68/}).waitFor();
  if (externalRequests.length || consoleErrors.length) failures.push('External request or console error');
  if (failures.length) throw new Error(JSON.stringify({failures, consoleErrors, externalRequests}));
  return {states, checks: ['two sourced replays', 'OSM map rendered', 'attribution', 'retrospective/weather provenance',
    '1280x720 overflow', 'image ablation', 'duplicate invariance', 'reload persistence', 'external network blocked'],
    failures, consoleErrors, externalRequests};
}
