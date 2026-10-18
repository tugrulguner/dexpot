import { expect, test } from '@playwright/test';
for (const width of [768,390,320]) for (const mode of ['light','dark','auto']) {
 test(`compact social menu remains complete at ${width}px ${mode}`,async({page})=>{
  await page.setViewportSize({width,height:900});
  await page.goto('/quick-start/?private=DO_NOT_TRANSFER#DO_NOT_TRANSFER');
  await page.locator('header starlight-theme-select select').selectOption(mode);
  await page.locator('.family-menu-button').click();
  const menu=page.locator('#family-mobile-menu');
  for(const[label,href]of[['LinkedIn','https://www.linkedin.com/in/tugrulguner/'],['X','https://x.com/Tugrul_Guner']]){
   const a=menu.getByRole('link',{name:new RegExp('^'+label+' \\(')});
   await expect(a).toBeVisible();await expect(a).toHaveAttribute('href',href);await expect(a).toHaveAttribute('target','_blank');await expect(a).toHaveAttribute('rel','noopener noreferrer');
   await a.scrollIntoViewIfNeeded();const r=await a.boundingBox();expect(r.width).toBeGreaterThanOrEqual(44);expect(r.height).toBeGreaterThanOrEqual(44);
   expect(await a.evaluate(e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return h===e||e.contains(h);})).toBe(true);
   await a.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await expect(a).toBeFocused();expect(await a.evaluate(e=>getComputedStyle(e).outlineStyle)).not.toBe('none');
  }
  for(const a of await menu.locator('a[href*="issues/new"]').all())expect(await a.getAttribute('href')).not.toContain('DO_NOT_TRANSFER');
  await page.keyboard.press('Escape');await expect(menu).toBeHidden();
 });
}
