const { test, expect } = require('@playwright/test');

test.describe('desktop report catalog ingestion', () => {
  test('reviewed report information is saved into the single-entity catalog', async ({ page }) => {
    await page.addInitScript(() => {
      const dims = ['imp_financial','imp_compliance','imp_operation','imp_reputation','imp_fraud','imp_strategy','imp_data','imp_hse'];
      const domains = ['战略与投资','治理与决策','资金活动','财务报告与税务','资产管理','采购与外包','合同管理','工程项目','人力资源','信息系统','合规与法律','安全环保'];
      const makeFinding = (id, title) => ({task_id:'TASK-1',finding_id:id,title,fact_summary:`${title}的虚构事实`,source_page:'第 1 页',source_excerpt:`${title}的虚构关键摘录`,matched_risk_id:'R001',domain:'采购与外包',likelihood:3,impact_scores:Object.fromEntries(dims.map(dim=>[dim,2])),rationale:`${title}的独立依据`,needs_review:true,review_status:'待确认',merged_finding_ids:[],merged_into:''});
      let findings = [makeFinding('F-1','准入资料复核缺失'),makeFinding('F-2','背景调查未闭环')];
      window.pywebview = { api: {
        get_bootstrap: async () => ({profiles:[{name:'合成模型',base_url:'https://model.example.test',model:'synthetic',supports_vision:false}],domains,dimensions:dims,dimension_labels:{},workspace:{schema_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',created_at:'2026-09-04T08:00:00Z'},catalog_root:'C:/synthetic/catalog',catalog_reports:[],capabilities:{desktop:true,source_preview:true,report_catalog:true}}),
        choose_report: async purpose => purpose==='report'?{selection_token:'REPORT',basename:'synthetic.pdf',purpose}:{selection_token:'WORKBOOK',basename:'register.xlsx',purpose},
        test_model_profile: async () => ({hostname:'model.example.test'}),
        start_analysis: async (report,book,period,profile) => {
          if(report!=='REPORT'||book!=='WORKBOOK'||period!=='CATALOG'||profile!=='合成模型') throw {code:'BINDING_INVALID'};
          return {task:{task_id:'TASK-1',file_name:'synthetic.pdf',file_hash:'a'.repeat(64),created_at:'2026-09-04T08:00:00Z',status:'提取中',model_profile:profile,extraction_method:'text'},risk_catalog:[{risk_id:'R001',name:'供应商准入风险',domain:'采购与外包',description:'虚构风险',owner_dept:'采购部'}],period};
        },
        get_task: async () => ({task:{task_id:'TASK-1',status:'待复核',extraction_method:'text'}}),
        get_findings: async () => ({findings}),
        get_source_preview: async () => ({kind:'text',source_page:'第 1 页',source_excerpt:'虚构关键摘录'}),
        save_finding: async (_task,id,payload) => { findings=findings.map(item=>item.finding_id===id?{...item,...payload}:item);return {finding:findings.find(item=>item.finding_id===id)}; },
        merge_findings: async (_task,ids,payload) => ({findings:findings.map(item=>item.finding_id===ids[0]?{...item,...payload,merged_finding_ids:ids.slice(1)}:item)}),
        split_finding: async () => ({findings}),
        save_report_to_catalog: async (_task,metadata) => ({report:{report_id:'REP-1',recognition_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',audit_project:metadata.audit_project,upload_date:'2026-09-04',uploaded_at:'2026-09-04T08:30:00Z',report_date:metadata.report_date,report_title:metadata.report_title,file_name:'synthetic.pdf',file_hash:'a'.repeat(64),model_profile:'合成模型',extraction_method:'text',status:'已完成',finding_count:2,record_path:'projects/rep/report-v1.json'}}),
      }};
    });

    await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
    await page.setViewportSize({width:1440,height:920});
    await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
    await expect(page.getByRole('heading',{name:'还没有可用于风险评估的报告'})).toBeVisible();
    await page.getByRole('button',{name:'＋ 添加审计报告'}).click();
    await page.locator('#report-audit-project').fill('采购专项审计');
    await page.locator('#report-title').fill('采购管理专项审计报告');
    await page.getByRole('button',{name:'选择报告',exact:true}).click();
    await page.getByRole('button',{name:'选择风险目录工作簿'}).click();
    await page.locator('#report-step-upload details summary').click();
    await page.getByRole('button',{name:'测试连接'}).click();
    await page.getByRole('button',{name:'开始本地提取与识别'}).click();
    await expect(page.locator('[data-finding-id]')).toHaveCount(2);
    await page.getByRole('button',{name:'接受并下一条'}).click();
    await page.getByRole('button',{name:'接受并下一条'}).click();
    await page.getByRole('button',{name:'保存到报告目录'}).click();
    await expect(page.getByRole('heading',{name:'报告目录'})).toBeVisible();
    await expect(page.locator('[data-catalog-report-id="REP-1"]')).toContainText('采购管理专项审计报告');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  });

  test('browser mode stays empty until the explicit sample action and rejects invalid desktop data atomically', async ({ page }) => {
    await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
    await expect(page.locator('#desktop-report-shell')).toBeHidden();
    expect(await page.evaluate(() => Object.keys(window.__RAHMDesktopTestState().data))).toEqual([]);
    await expect(page.locator('#tbl-prio tbody tr')).toHaveCount(0);
    await page.locator('#btn-sample').click();
    await expect(page.locator('#tbl-prio')).not.toBeEmpty();
    const before = await page.evaluate(() => JSON.stringify(window.__RAHMDesktopTestState()));
    const invalid = await page.evaluate(() => window.RAHMDesktop.loadPeriodData('bad/period', [], []));
    const after = await page.evaluate(() => JSON.stringify(window.__RAHMDesktopTestState()));
    expect(invalid).toBe(false);
    expect(after).toBe(before);
  });
});
