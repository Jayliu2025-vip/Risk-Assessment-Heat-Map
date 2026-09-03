const { test, expect } = require('@playwright/test');

test.describe('synthetic desktop audit report workflow', () => {
  test('desktop workflow commits reviewed synthetic findings into the existing heatmap', async ({ page }) => {
    await page.addInitScript(() => {
      const dims = ['imp_financial','imp_compliance','imp_operation','imp_reputation','imp_fraud','imp_strategy','imp_data','imp_hse'];
      const finding = (id, title) => ({ finding_id:id, title, fact_summary:'合成事实', source_page:'第 1 页', source_excerpt:'合成摘录', matched_risk_id:'R001', domain:'采购与外包', likelihood:3, impact_scores:Object.fromEntries(dims.map(d => [d, 2])), rationale:'合成依据', needs_review:true, review_status:'待确认' });
      let findings = [finding('F-1','第一项'), finding('F-2','第二项'), finding('F-3','第三项')];
      let poll = 0;
      window.__desktopPollCount = () => poll;
      window.pywebview = { api: {
        get_bootstrap: async () => ({ profiles:[{name:'合成模型',base_url:'https://model.example.test',model:'synthetic',supports_vision:false}], domains:['采购与外包'] }),
        choose_report: async purpose => ({ selection_token: purpose === 'workbook' ? 'book' : 'report', basename: purpose === 'workbook' ? 'synthetic.xlsx' : 'synthetic.pdf' }),
        save_model_profile: async ({ name, base_url, model, supports_vision }) => ({ profile:{ name, base_url, model, supports_vision } }),
        test_model_profile: async () => ({ hostname:'model.example.test' }),
        start_analysis: async () => ({ task:{task_id:'T-1',status:'提取中',extraction_method:'text'} }),
        get_task: async () => ({ task:{task_id:'T-1',status: ++poll < 2 ? '分析中' : '待复核', extraction_method:'text'} }),
        get_findings: async () => ({ findings }),
        get_source_preview: async () => ({ kind:'text',source_page:'第 1 页',source_excerpt:'合成摘录' }),
        save_finding: async (_task, id, payload) => { findings = findings.map(item => item.finding_id === id ? {...payload, finding_id:id} : item); return { finding: findings.find(item => item.finding_id === id) }; },
        merge_findings: async (_task, ids, payload) => { findings = findings.map(item => item.finding_id === ids[1] ? {...item,review_status:'已排除'} : item.finding_id === ids[0] ? {...payload,finding_id:ids[0]} : item); return {findings}; },
        split_finding: async () => ({findings}),
        preview_commit: async () => ({commit_token:'once',new_risks:[{risk_id:'R900'}],updated_risks:[],control_replacements:[],excluded_findings:['F-3'],warnings:[],period:'2026H2'}),
        commit_to_workbook: async () => ({workbook_path:'C:/synthetic/out.xlsx',periods:['2026H2'],assessed_risks:[{risk_id:'R900',name:'确认风险',domain:'采购与外包',description:'合成描述',owner_dept:'审计部',period:'2026H2',likelihood:3,...Object.fromEntries(dims.map(d => [d, 2])),rationale:'合成依据'}],controls:[]})
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
    await page.getByRole('button', { name:'开始本地提取' }).click();
    await expect(page.locator('#report-step-review')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-finding-id]')).toHaveCount(3);
    const terminalPollCount = await page.evaluate(() => window.__desktopPollCount());
    await page.waitForTimeout(900);
    expect(await page.evaluate(() => window.__desktopPollCount())).toBe(terminalPollCount);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path:'output/playwright/desktop-1440x920.png' });
    await page.locator('[data-finding-id="F-1"]').click();
    await page.locator('[data-finding-field="title"]').fill('已编辑第一项');
    await page.getByRole('button', { name:'保存发现' }).click();
    await page.locator('[data-finding-id="F-2"]').click({ modifiers:['Control'] });
    await page.getByRole('button', { name:'合并所选' }).click();
    await page.locator('[data-finding-id="F-3"]').click();
    await page.getByRole('button', { name:'排除', exact:true }).click();
    await page.getByRole('button', { name:'进入风险评估' }).click();
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
