import { expect, test } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
const routes = ['/', '/quick-start/', '/playground/'];
const widths = [1280, 768, 390];
const palette = { light: 'rgb(0, 107, 143)', dark: 'rgb(102, 217, 255)' };
const contrast = (a, b) => {
  const lum = rgb => rgb.slice(0,3).map(c=>c/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4).reduce((s,c,i)=>s+c*[.2126,.7152,.0722][i],0);
  const values=[lum(a),lum(b)].sort((x,y)=>y-x);return(values[0]+.05)/(values[1]+.05);
};
async function sample(page) {
  return page.evaluate(() => {
    const root=getComputedStyle(document.documentElement);
    const primary=document.querySelector('.framework-action.primary');
    const link=document.querySelector('.installation-strip a, .playground-context a, .sl-markdown-content a[href^="/route-contract/"]');
    const suffix=document.querySelector('.site-title .wordmark-suffix');
    if(!link||!suffix)throw new Error('Missing intended branded link or wordmark');
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');
    const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return[...ctx.getImageData(0,0,1,1).data];};
    const surface=node=>{for(let el=node;el;el=el.parentElement){const bg=rgba(getComputedStyle(el).backgroundColor);if(bg[3]===255)return bg;}return[255,255,255,255];};
    const read=node=>node?{color:getComputedStyle(node).color,fg:rgba(getComputedStyle(node).color),bg:surface(node),background:getComputedStyle(node).backgroundColor}:null;
    return{mode:document.documentElement.dataset.theme,suffix:getComputedStyle(suffix).color,link:read(link),primary:read(primary),selected:read(document.querySelector('.sidebar a[aria-current="page"]')),error:root.getPropertyValue('--mp-error-'+document.documentElement.dataset.theme).trim()};
  });
}
test('cyan link and action contrast stays valid in explicit themes opposite OS and live Auto',async({page},info)=>{
  const samples=[];
  for(const route of routes)for(const width of widths){
    await page.setViewportSize({width,height:900});await page.goto(route);await page.evaluate(()=>document.fonts.ready);
    const theme=page.locator('starlight-theme-select select:visible').first();
    for(const choice of ['explicit','auto'])for(const mode of ['light','dark']){
      await page.emulateMedia({colorScheme:choice==='explicit'?(mode==='light'?'dark':'light'):mode});
      await theme.selectOption(choice==='auto'?'auto':mode);
      await expect.poll(()=>page.locator('html').getAttribute('data-theme')).toBe(mode);
      const actual=await sample(page);samples.push({route,width,choice,...actual});
      expect(actual.suffix).toBe(palette[mode]);expect(actual.link.color).toBe(palette[mode]);
      expect(await page.locator('.site-title > span:not(.wordmark-suffix)').evaluate(el=>getComputedStyle(el).color)).toBe(mode==='light'?'rgb(24, 26, 29)':'rgb(237, 239, 242)');
      expect(contrast(actual.link.fg,actual.link.bg)).toBeGreaterThanOrEqual(4.5);
      if(actual.selected)expect(contrast(actual.selected.fg,actual.selected.bg)).toBeGreaterThanOrEqual(4.5);
      if(route==='/quick-start/')expect(actual.selected).not.toBeNull();
      expect(actual.error).toBe(mode==='light'?'#a4262b':'#ff9b9b');
      if(route==='/'){
        expect(actual.primary.background).toBe(palette[mode]);expect(contrast(actual.primary.fg,actual.primary.bg)).toBeGreaterThanOrEqual(4.5);
        const button=page.locator('.framework-action.primary');await button.focus();expect(await button.evaluate(el=>getComputedStyle(el).outlineColor)).toBe(palette[mode]);
        await button.hover();await page.screenshot({path:info.outputPath(`cyan-${width}-${choice}-${mode}.png`)});
      }
    }
  }
  expect(samples).toHaveLength(routes.length*widths.length*4);
  await writeFile(info.outputPath('cyan-palette-matrix.json'),JSON.stringify(samples,null,2));
});
