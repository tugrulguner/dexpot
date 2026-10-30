// Repository snapshots include third-party status badges unrelated to the
// content assertions. Callers still explicitly verify the assets they cover.
export async function gotoProjectPage(page, path) {
  await page.goto(path, { waitUntil: 'domcontentloaded' });
}
