// HISTORICAL UI SCRIPT: retired selectors. Current release instructions and selectors: docs/browser-release-qa.js.
// Explicitly submits two synthetic reports via the real UI/API. May make two billed calls.
// Run after opening the local app with playwright-cli. Never runs automatically.
async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({width: 1440, height: 1000});
  const origin = page.url().split('/').slice(0, 3).join('/');
  const get = async path => (await page.request.get(origin + '/api/v1/' + path)).json();
  const before = await get('perception/usage');
  await page.getByRole('button', {name: 'New observation', exact: true}).click();
  await page.getByRole('textbox', {name: 'Operator', exact: true}).fill('Phase 2A synthetic UI verification');
  await page.getByRole('textbox', {name: 'Reviewed road segment label'}).fill('UI verification segment');
  await page.getByRole('checkbox', {name: 'I reviewed the source', exact: false}).check();
  await page.getByRole('checkbox', {name: 'This is a synthetic test', exact: false}).check();
  const texts = ['في مية واقفة جنب الرصيف من 90 دقيقة وفي شقوق واضحة في الأسفلت',
                 'الأسفلت متشقق والمية لسه متجمعة جنب الرصيف'];
  const jobs = [];
  for (const text of texts) {
    await page.getByRole('textbox', {name: 'Report text', exact: true}).fill(text);
    const currentUsage = await get('perception/usage');
    if (currentUsage.total_api_requests !== (jobs.length ? jobs[0].requestsAfter : before.total_api_requests)) throw new Error('Unexpected API call while typing');
    const posted = page.waitForResponse(r => r.url().endsWith('/api/v1/signals') && r.request().method() === 'POST');
    await page.getByRole('button', {name: 'Submit for text analysis', exact: true}).click();
    const initial = await (await posted).json();
    await page.getByRole('status').filter({hasText: 'Processed'}).waitFor({timeout: 45000});
    const job = await get(`signals/${initial.signal_id}/processing`);
    if (job.status !== 'processed' || job.latest.extraction.standing_water !== 'present') throw new Error('Valid UI report failed extraction');
    const usage = await get('perception/usage');
    jobs.push({...job, requestsAfter: usage.total_api_requests});
  }
  if (jobs[0].disposition !== 'watch' || jobs[1].disposition !== 'candidate') throw new Error('Watch to candidate transition failed');
  await page.screenshot({path: 'output/playwright/phase2a-live-candidate.png', fullPage: true});
  // Explicit repeat uses cache. Refresh is read-only and must not re-extract.
  const beforeCache = await get('perception/usage');
  await page.getByRole('button', {name: 'Retry primary / use cache', exact: true}).click();
  await page.getByText('Cached AI extraction', {exact: true}).waitFor({timeout: 15000});
  const afterCache = await get('perception/usage');
  if (afterCache.total_api_requests !== beforeCache.total_api_requests || afterCache.cache_hits !== beforeCache.cache_hits + 1) throw new Error('Cache made a provider request');
  await page.getByRole('button', {name: 'Correct extraction', exact: true}).click();
  await page.getByLabel('Correct road damage', {exact: true}).selectOption('not_mentioned');
  await page.getByRole('textbox', {name: 'Correction reason', exact: true}).fill('Synthetic correction workflow check: withhold the damage assertion pending review.');
  await page.getByRole('button', {name: 'Save reviewed revision', exact: true}).click();
  await page.getByText('Human reviewed', {exact: true}).waitFor({timeout: 15000});
  const reviewed = await get(`signals/${jobs[1].signal_id}/processing`);
  if (reviewed.original.text !== texts[1] || reviewed.revisions.length !== 3 || reviewed.latest.source !== 'manual' || reviewed.latest.extraction.road_damage !== 'not_mentioned') throw new Error('Review history failed');
  await page.screenshot({path: 'output/playwright/phase2a-human-review.png', fullPage: true});
  await page.reload();
  const afterRefresh = await get('perception/usage');
  if (afterRefresh.total_api_requests !== afterCache.total_api_requests) throw new Error('Refresh triggered extraction');
  if (errors.length) throw new Error(errors.join('; '));
  return {passed: true, reportOrigins: 'synthetic UI reports, real OpenAI inference',
    first: {signal_id: jobs[0].signal_id, disposition: jobs[0].disposition, source: jobs[0].latest.source},
    second: {signal_id: jobs[1].signal_id, disposition: jobs[1].disposition, source: jobs[1].latest.source},
    reviewRevision: reviewed.revision, originalPreserved: true, refreshRequests: 0,
    apiRequestDelta: afterRefresh.total_api_requests - before.total_api_requests,
    cacheHitDelta: afterRefresh.cache_hits - before.cache_hits, browserErrors: errors};
}
