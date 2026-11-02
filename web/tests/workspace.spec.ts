import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fixture from '../src/index-fixture.json' with {type:'json'};

test('live controls, graph, themes, accessibility and schema rejection',async({page},testInfo)=>{
 await page.goto('/');
 await expect(page.getByRole('heading',{name:'From release to signal.'})).toBeVisible();
 await expect(page.getByRole('button',{name:/Run workflow/})).toBeEnabled();
 await page.getByRole('combobox',{name:'Workflow'}).selectOption('production');
 await expect(page.getByRole('button',{name:/Aggregate index proxies/})).toBeVisible();
 await page.getByRole('button',{name:/Extract and validate/}).click();
 await expect(page.getByRole('heading',{name:'Extract and validate'})).toBeVisible();
 await page.getByRole('combobox',{name:'Workflow'}).selectOption('demo');
 for(const theme of ['light','dark']) {
  if(theme==='dark') await page.getByRole('button',{name:'Dark appearance'}).click();
  const result=await new AxeBuilder({page}).analyze();
  expect(result.violations).toEqual([]);
  await page.screenshot({path:`../data/screenshots/${testInfo.project.name}-${theme}.png`,fullPage:true});
 }
 await page.getByLabel('Load replay').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"snapshots":[],"private":"CIK"}')});
 await expect(page.getByRole('alert')).toContainText('Replay schema rejected');
 await page.getByLabel('Load replay').setInputFiles({name:'identifiers.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({version:'v1',label:'index-level proxies',snapshots:[{cik:'0000000001'}]}))});
 await expect(page.getByRole('alert')).toContainText('Replay schema rejected');
 await page.getByLabel('Load replay').setInputFiles({name:'index.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
 await expect(page.getByText('REPLAY · NO EXECUTION')).toBeVisible();
 await expect(page.getByRole('button',{name:/Run workflow/})).toHaveCount(0);
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export Index JSON ↓'}).click();
 expect((await download).suggestedFilename()).toBe('tresata-index.json');
 await page.getByRole('button',{name:'Return to live'}).click();
 await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:/Optimise/}).click();
 await expect(page.getByRole('heading',{name:'Request efficiency'})).toBeVisible();
});

test('live job survives reload and cancels through the worker',async({page})=>{
 await page.goto('/');
 const run=page.getByRole('button',{name:/Run workflow/});
 await expect(run).toBeEnabled();
 await run.click();
 await expect(page.getByRole('button',{name:'Cancel between items'})).toBeVisible();
 await page.reload();
 await page.getByRole('button',{name:'Cancel between items'}).click();
 await expect(page.locator('.stats strong').first()).toHaveText('cancelled',{timeout:45000});
 await expect(page.locator('.events')).toContainText('cancelled');
});
