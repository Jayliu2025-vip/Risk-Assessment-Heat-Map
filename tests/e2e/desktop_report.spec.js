const { test, expect } = require('@playwright/test');

test.describe('synthetic desktop audit report workflow', () => {
  test('desktop workflow commits reviewed synthetic findings into the existing heatmap', async ({ page }) => {
    await page.addInitScript(() => {
      const dims = ['imp_financial','imp_compliance','imp_operation','imp_reputation','imp_fraud','imp_strategy','imp_data','imp_hse'];
      const domains = ['战略与投资','治理与决策','资金活动','财务报告与税务','资产管理','采购与外包','合同管理','工程项目','人力资源','信息系统','合规与法律','安全环保'];
      const finding = (id, title) => ({ finding_id:id, title, fact_summary:'合成事实', source_page:'第 1 页', source_excerpt:'合成摘录', matched_risk_id:'R001', domain:'采购与外包', likelihood:3, impact_scores:Object.fromEntries(dims.map(d => [d, 2])), rationale:'合成依据', needs_review:true, review_status:'待确认' });
      let findings = [finding('F-1','第一项'), finding('F-2','第二项'), finding('F-3','第三项')];
      let poll = 0;
      let startCalls = 0;
      let workbookCalls = 0;
      let loadCalls = 0;
      window.__desktopPollCount = () => poll;
      window.__desktopStartCalls = () => startCalls;
      window.__desktopWorkbookCalls = () => workbookCalls;
      window.__desktopLoadCalls = () => loadCalls;
      window.pywebview = { api: {
        get_bootstrap: async () => ({ profiles:[{name:'合成模型',base_url:'https://model.example.test',model:'synthetic',supports_vision:false}], domains }),
        choose_report: async purpose => { if(purpose !== 'workbook') return {selection_token:'report',basename:'synthetic.pdf'}; workbookCalls++; await new Promise(resolve => setTimeout(resolve, 100)); return {selection_token:'BOOK-A',basename:'synthetic.xlsx'}; },
        save_model_profile: async ({ name, base_url, model, supports_vision }) => ({ profile:{ name, base_url, model, supports_vision } }),
        test_model_profile: async () => ({ hostname:'model.example.test' }),
        start_analysis: async () => { startCalls++; await new Promise(resolve => setTimeout(resolve, 80)); return { task:{task_id:'T-1',status:'提取中',extraction_method:'text'} }; },
        get_task: async () => ({ task:{task_id:'T-1',status: ++poll < 2 ? '分析中' : '待复核', extraction_method:'text'} }),
        get_findings: async () => ({ findings }),
        get_source_preview: async (_task, id) => { if(id === 'F-1') await new Promise(resolve => setTimeout(resolve, 180)); return id === 'F-2' ? ({ kind:'pdf',source_page:'第 2 页',image_data_url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlVw5sAAAAASUVORK5CYII=' }) : ({ kind:'text',source_page:'第 1 页',source_excerpt:'合成摘录' }); },
        save_finding: async (_task, id, payload) => { if(dims.some(dim => Object.hasOwn(payload, dim)) || Object.keys(payload.impact_scores || {}).length !== dims.length) throw {code:'INVALID_PAYLOAD'}; findings = findings.map(item => item.finding_id === id ? {...payload, finding_id:id} : item); return { finding: findings.find(item => item.finding_id === id) }; },
        merge_findings: async (_task, ids, payload) => { if(dims.some(dim => Object.hasOwn(payload, dim)) || Object.keys(payload.impact_scores || {}).length !== dims.length) throw {code:'INVALID_PAYLOAD'}; const changed = []; findings = findings.map(item => { const next = item.finding_id === ids[1] ? {...item,review_status:'已排除'} : item.finding_id === ids[0] ? {...payload,finding_id:ids[0]} : item; if(ids.includes(item.finding_id)) changed.push(next); return next; }); return {findings:changed}; },
        split_finding: async (_task, id, payloads) => ({findings:[{...findings.find(item => item.finding_id === id),review_status:'已排除'},...payloads]}),
        preview_commit: async (_task, workbookToken, selectedPeriod, decisions, stage, controlsConfirmed) => { if(stage === 'load_controls') { loadCalls++; await new Promise(resolve => setTimeout(resolve, 100)); return {controls_by_decision:decisions.map(item => ({...item,controls:item.action === 'merge' ? [{description:`CONTROL-${workbookToken}`,score:4,key:true}] : []}))}; } const included = decisions.filter(item => item.action !== 'exclude').flatMap(item => item.finding_ids); if(!controlsConfirmed || findings.some(item => included.includes(item.finding_id) && item.review_status !== '已接受')) throw {code:'PENDING_REVIEW'}; if(workbookToken !== 'BOOK-A' || selectedPeriod !== '2026H2' || decisions.some(item => item.action !== 'exclude' && (item.period !== selectedPeriod || item.domain !== '信息系统' || !item.controls.some(control => control.description === 'CONTROL-BOOK-A（已复核）' && control.score === 4 && control.key)))) throw {code:'STALE'}; return {commit_token:'once',new_risks:[{risk_id:'R900'}],updated_risks:[],new_controls:[],excluded_count:2,warnings:[]}; },
        commit_to_workbook: async (_task, _book, selectedPeriod, decisions) => ({workbook_path:'C:/synthetic/out.xlsx',export_dir:'C:/synthetic/export',period_data:{period:selectedPeriod,risks:[{risk_id:'R900',name:'确认风险',domain:'信息系统',description:'合成描述',owner_dept:'审计部',period:selectedPeriod,likelihood:3,...Object.fromEntries(dims.map(d => [d, 2])),rationale:'合成依据'}],controls:[]}})
      }};
    });
    await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
    await page.setViewportSize({width:1440,height:920});
    await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
    await page.locator('#desktop-report-nav').click();
    await page.getByRole('button', { name:'选择报告' }).click();
    await page.getByLabel('评估期间').fill('2026H2');
    await page.locator('#report-step-upload details summary').click();
    await page.getByRole('button', { name:'测试连接' }).click();
    await page.getByRole('button', { name:'开始本地提取' }).dblclick();
    await expect.poll(() => page.evaluate(() => window.__desktopStartCalls())).toBe(1);
    await expect(page.locator('#report-step-review')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-finding-id]')).toHaveCount(3);
    await expect(page.locator('[data-finding-field="domain"] option')).toHaveCount(12);
    await page.locator('[data-finding-id="F-1"]').click();
    await page.locator('[data-finding-id="F-2"]').click();
    await expect(page.locator('#report-source-viewer img')).toHaveAttribute('alt', '来源页 第 2 页');
    const terminalPollCount = await page.evaluate(() => window.__desktopPollCount());
    await page.waitForTimeout(900);
    expect(await page.evaluate(() => window.__desktopPollCount())).toBe(terminalPollCount);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path:'output/playwright/desktop-1440x920.png' });
    await page.locator('[data-finding-id="F-1"]').click();
    await page.locator('[data-finding-field="title"]').fill('已编辑第一项');
    await page.locator('[data-finding-field="domain"]').selectOption('信息系统');
    await page.getByRole('button', { name:'保存发现' }).click();
    await page.getByRole('button', { name:'接受' }).click();
    await page.locator('[data-finding-id="F-2"]').click();
    await expect(page.locator('#report-source-viewer img')).toHaveAttribute('alt', '来源页 第 2 页');
    await page.locator('[data-finding-id="F-1"]').click();
    await expect(page.locator('#report-source-viewer')).toContainText('合成摘录');
    await page.locator('[data-finding-id="F-2"]').click({ modifiers:['Control'] });
    await page.getByRole('button', { name:'合并所选' }).click();
    await expect(page.locator('[data-finding-id]')).toHaveCount(3);
    await page.locator('[data-finding-id="F-3"]').click();
    await page.getByRole('button', { name:'排除', exact:true }).click();
    await page.getByRole('button', { name:'进入风险评估' }).click();
    await page.getByRole('button', { name:'选择工作簿并预览' }).dblclick();
    await expect.poll(() => page.evaluate(() => window.__desktopWorkbookCalls())).toBe(1);
    await expect.poll(() => page.evaluate(() => window.__desktopLoadCalls())).toBe(1);
    await expect(page.getByLabel('控制点 F-1')).toHaveValue('CONTROL-BOOK-A');
    await page.screenshot({ path:'output/playwright/desktop-step4-controls-1440x920.png' });
    await page.getByLabel('控制点 F-1').fill('CONTROL-BOOK-A（已复核）');
    await page.getByLabel('控制点 F-1').press('Tab');
    await page.getByLabel('已确认当前控制措施').check();
    await page.getByRole('button', { name:'选择工作簿并预览' }).click();
    await page.getByRole('button', { name:'提交到工作簿' }).click();
    await expect(page.locator('#tbl-prio')).toContainText('确认风险');
    await expect(page.getByRole('button', { name:'提交到工作簿' })).toBeDisabled();
  });

  test('browser mode stays unchanged and invalid commit data is atomic', async ({ page }) => {
    await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
    await expect(page.locator('#desktop-report-nav')).toBeHidden();
    await page.locator('#btn-sample').click();
    await expect(page.locator('#tbl-prio')).not.toBeEmpty();
    const before = await page.evaluate(() => JSON.stringify(window.__RAHMDesktopTestState()));
    const invalid = await page.evaluate(() => window.RAHMDesktop.loadPeriodData('bad/period', [], []));
    const after = await page.evaluate(() => JSON.stringify(window.__RAHMDesktopTestState()));
    expect(invalid).toBe(false); expect(after).toBe(before);
    await page.setViewportSize({width:1120,height:720});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path:'output/playwright/browser-1120x720.png' });
  });
});
