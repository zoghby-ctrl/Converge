// Image workflow smoke check. This is intentionally read-only by default: selecting a
// fixture and rendering its preview does not call OpenAI or create a saved observation.
// Set CONVERGE_IMAGE_LIVE=1 for an end-to-end upload. damage-01 is in the locked
// image-1.2 cache, so this path is safe with the server API key deliberately blank.
import path from 'node:path'

const fixture = path.resolve(process.cwd(), 'fixtures', 'images', 'damage-01.jpg')
const runLive = process.env.CONVERGE_IMAGE_LIVE === '1'

export default async (page) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({width: 1440, height: 1000})
  await page.getByRole('button', {name: 'New observation', exact: true}).click()
  await page.getByRole('textbox', {name: 'Operator', exact: true}).fill('Phase 2B image UI verification')
  await page.getByRole('textbox', {name: 'Reviewed road segment label'}).fill('Image verification segment')
  await page.getByLabel('Infrastructure image', {exact: true}).setInputFiles(fixture)
  await page.getByAltText('Selected infrastructure preview').waitFor({timeout: 5000})
  if (await page.getByText('analysis starts only after submit', {exact: false}).count() !== 1) throw new Error('Image preview did not render')

  if (!runLive) return {passed: errors.length === 0, live: false, fixture, browserErrors: errors}

  await page.getByLabel('Image source', {exact: false}).selectOption('public_source')
  await page.getByRole('textbox', {name: 'Public source reference'}).fill('https://commons.wikimedia.org/wiki/File:Pothole_in_an_asphalt_pavement.jpg')
  await page.getByRole('textbox', {name: 'License / permission'}).fill('CC BY-SA 4.0')
  await page.getByRole('checkbox', {name: /assert this capture is independent/}).check()
  const posted = page.waitForResponse(r => r.url().endsWith('/api/v1/images') && r.request().method() === 'POST')
  await page.getByRole('button', {name: 'Submit image and report', exact: true}).click()
  const response = await posted
  if (!response.ok()) throw new Error(`Image upload rejected (${response.status()})`)
  await page.getByRole('status').filter({hasText: /Needs review|Processed/}).waitFor({timeout: 15000})
  if (await page.getByText('Cached AI extraction', {exact: false}).count() !== 1) throw new Error('Expected cached extraction label')
  if (await page.getByAltText('Saved infrastructure source').count() !== 1) throw new Error('Saved source image missing')
  await page.getByRole('button', {name: 'Correct image labels'}).click()
  await page.getByRole('textbox', {name: 'Correction reason'}).fill('Browser pixel review confirmed the visible labels')
  await page.getByRole('button', {name: 'Save reviewed image labels'}).click()
  await page.getByText('Human reviewed', {exact: false}).first().waitFor({timeout: 10000})
  await page.screenshot({path: 'output/playwright/phase2b-image-ui.png', fullPage: true})
  if (errors.length) throw new Error(errors.join('; '))
  return {passed: true, live: true, fixture, status: await page.getByRole('status').innerText(), browserErrors: errors}
}
