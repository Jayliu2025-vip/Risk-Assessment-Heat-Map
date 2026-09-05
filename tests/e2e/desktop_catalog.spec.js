const { test, expect } = require('@playwright/test');

test('desktop catalog selects two reports and creates one evidenced risk', async ({ page }) => {
  await page.addInitScript(() => {
    const dims = ['imp_financial','imp_compliance','imp_operation','imp_reputation','imp_fraud','imp_strategy','imp_data','imp_hse'];
    const domains = ['战略与投资','治理与决策','资金活动','财务报告与税务','资产管理','采购与外包','合同管理','工程项目','人力资源','信息系统','合规与法律','安全环保'];
    const reports = [
      {report_id:'REP-A',recognition_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',audit_project:'采购专项审计',upload_date:'2026-09-04',uploaded_at:'2026-09-04T08:00:00Z',report_date:'2026-08-28',report_title:'采购管理专项审计报告',file_name:'a.pdf',file_hash:'a'.repeat(64),model_profile:'合成模型',extraction_method:'text',status:'已完成',finding_count:1,record_path:'projects/a/report-v1.json'},
      {report_id:'REP-B',recognition_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',audit_project:'供应链内控审计',upload_date:'2026-08-18',uploaded_at:'2026-08-18T08:00:00Z',report_date:'2026-08-12',report_title:'供应链内部控制审计报告',file_name:'b.pdf',file_hash:'b'.repeat(64),model_profile:'合成模型',extraction_method:'ocr',status:'已完成',finding_count:1,record_path:'projects/b/report-v1.json'},
    ];
    const finding = (id, title, source) => ({task_id:'BATCH-1',finding_id:id,title,fact_summary:`${title}的虚构事实`,source_page:source,source_excerpt:`${title}的虚构关键摘录`,matched_risk_id:'R001',domain:'采购与外包',likelihood:3,impact_scores:Object.fromEntries(dims.map(dim=>[dim,2])),rationale:`${title}的独立依据`,needs_review:true,review_status:'已接受',merged_finding_ids:[],merged_into:''});
    let findings = [finding('F-1-1','准入资料缺少关联关系声明','采购管理专项审计报告｜第 12 页'),finding('F-2-1','供应商背景复核未形成闭环记录','供应链内部控制审计报告｜第 7 页')];
    let loadControls = 0;
    window.pywebview = { api: {
      get_bootstrap: async () => ({profiles:[{name:'合成模型',base_url:'https://model.example.test',model:'synthetic',supports_vision:false}],domains,dimensions:dims,dimension_labels:{},workspace:{schema_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',created_at:'2026-09-04T08:00:00Z'},catalog_root:'C:/synthetic/catalog',catalog_reports:reports,capabilities:{desktop:true,source_preview:true,report_catalog:true}}),
      choose_report: async purpose => purpose === 'workbook' ? {selection_token:'BOOK',basename:'register.xlsx',purpose} : {selection_token:'REPORT',basename:'report.pdf',purpose},
      create_catalog_batch: async (ids, book, period) => {
        if (ids.join('|') !== 'REP-A|REP-B' || book !== 'BOOK' || period !== '2026H2') throw {code:'INVALID_BATCH'};
        return {task:{task_id:'BATCH-1',file_name:'catalog-batch.json',file_hash:'c'.repeat(64),created_at:'2026-09-04T08:30:00Z',status:'待复核',model_profile:'catalog',extraction_method:'catalog'},findings,reports,report_refs:reports,risk_catalog:[{risk_id:'R001',name:'供应商准入与围标串标',domain:'采购与外包',description:'虚构风险',owner_dept:'采购部',period:'2026H2'}],period};
      },
      merge_findings: async (_task, ids, payload) => { findings=findings.map(item=>item.finding_id===ids[0]?{...item,...payload,merged_finding_ids:ids.slice(1)}:item.finding_id===ids[1]?{...item,merged_into:ids[0]}:item);return {findings}; },
      save_finding: async (_task,id,payload) => { findings=findings.map(item=>item.finding_id===id?{...item,...payload}:item);return {finding:findings.find(item=>item.finding_id===id)}; },
      preview_commit: async (_task, book, period, decisions, stage, confirmed) => {
        if(book!=='BOOK'||period!=='2026H2') throw {code:'STALE'};
        if(stage==='load_controls'){loadControls++;return {controls_by_decision:decisions.map(item=>({...item,controls:[{description:'供应商准入复核',score:3,key:true}]}))};}
        if(!confirmed) throw {code:'PENDING_REVIEW'};
        return {commit_token:'TOKEN',new_risks:[],updated_risks:[{risk_id:'R001'}],new_controls:[],excluded_count:0,warnings:[]};
      },
      commit_to_workbook: async () => ({batch_id:'BATCH-1',workbook_path:'C:/synthetic/audit_risk_register_20260904_1430.xlsx',export_dir:'C:/synthetic/export',period_data:{period:'2026H2',risks:[{risk_id:'R001',name:'供应商准入与围标串标',domain:'采购与外包',description:'虚构风险',owner_dept:'采购部',period:'2026H2',likelihood:3,...Object.fromEntries(dims.map(dim=>[dim,2])),rationale:'两份报告的独立证据'}],controls:[{control_id:'C001',risk_id:'R001',period:'2026H2',description:'供应商准入复核',score:3,key:'是'}]}}),
      get_source_preview: async (_task,id) => ({kind:'text',source_report_title:id==='F-1-1'?'采购管理专项审计报告':'供应链内部控制审计报告',source_upload_date:id==='F-1-1'?'2026-09-04':'2026-08-18',source_audit_project:id==='F-1-1'?'采购专项审计':'供应链内控审计',source_page:id==='F-1-1'?'第 12 页':'第 7 页',source_excerpt:'虚构关键摘录'}),
    }};
  });

  await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
  await page.setViewportSize({width:1440,height:920});
  await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));

  await expect(page.getByRole('heading', {name:'报告目录'})).toBeVisible();
  await expect(page.getByText('当前主体：虚构主体甲')).toBeVisible();
  await expect(page.locator('#btn-sample')).toBeHidden();
  await expect(page.locator('#tbl-prio')).toBeHidden();
  await expect(page.locator('[data-catalog-report-id]')).toHaveCount(2);

  await page.getByLabel('选择 采购管理专项审计报告').check();
  await page.getByLabel('选择 供应链内部控制审计报告').check();
  await expect(page.getByText('已选择 2 份报告')).toBeVisible();
  await page.screenshot({path:'output/playwright/desktop-catalog-selected-1440x920.png'});
  await page.getByRole('button', {name:'形成风险评估图谱'}).click();
  await page.getByRole('button', {name:'选择当前正式工作簿'}).click();
  await page.getByLabel('目标评估期间').fill('2026H2');
  await page.getByRole('button', {name:'载入所选报告'}).click();

  await expect(page.getByRole('heading', {name:'相似发现处理'})).toBeVisible();
  await expect(page.getByText('这 2 条发现可能指向同一项风险')).toBeVisible();
  await expect(page.getByLabel('为同一风险的两条证据')).toBeChecked();
  await page.screenshot({path:'output/playwright/desktop-catalog-similar-1440x920.png'});
  await page.getByRole('button', {name:'确认发现关系并继续'}).click();

  await page.getByLabel('整改状态 F-1-1').selectOption('整改中');
  await page.getByRole('button', {name:'载入控制点'}).click();
  await expect(page.getByLabel('控制点 F-1-1|F-2-1')).toHaveValue('供应商准入复核');
  await page.getByLabel('已确认当前控制措施').check();
  await page.getByRole('button', {name:'生成变更预览'}).click();
  await page.getByRole('button', {name:'确认并生成版本化工作簿'}).click();

  await expect(page.getByRole('heading', {name:'风险图谱 · 2026H2'})).toBeVisible();
  await expect(page.locator('#tbl-prio')).toContainText('供应商准入与围标串标');
  await page.screenshot({path:'output/playwright/desktop-catalog-dashboard-1440x920.png'});
  await page.setViewportSize({width:1120,height:720});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('desktop catalog requires an invalid historic risk id to be remapped', async ({ page }) => {
  await page.addInitScript(() => {
    const dims=['imp_financial','imp_compliance','imp_operation','imp_reputation','imp_fraud','imp_strategy','imp_data','imp_hse'];
    const report={report_id:'REP-OLD',recognition_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',audit_project:'历史采购审计',upload_date:'2026-07-01',uploaded_at:'2026-07-01T08:00:00Z',report_date:'',report_title:'历史采购审计报告',file_name:'old.pdf',file_hash:'a'.repeat(64),model_profile:'合成模型',extraction_method:'text',status:'已完成',finding_count:1,record_path:'projects/old/report-v1.json'};
    let finding={task_id:'BATCH-OLD',finding_id:'F-1-1',title:'供应商准入资料缺失',fact_summary:'虚构事实',source_page:'历史采购审计报告｜第 3 页',source_excerpt:'虚构摘录',matched_risk_id:'',domain:'采购与外包',likelihood:3,impact_scores:Object.fromEntries(dims.map(dim=>[dim,2])),rationale:'虚构依据',needs_review:true,review_status:'待确认',merged_finding_ids:[],merged_into:''};
    window.pywebview={api:{
      get_bootstrap:async()=>({profiles:[],domains:['采购与外包'],dimensions:dims,dimension_labels:{},workspace:{schema_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',created_at:'x'},catalog_root:'C:/synthetic/catalog',catalog_reports:[report],capabilities:{desktop:true,source_preview:true,report_catalog:true}}),
      choose_report:async()=>({selection_token:'BOOK',basename:'register.xlsx',purpose:'workbook'}),
      create_catalog_batch:async()=>({task:{task_id:'BATCH-OLD',status:'待复核',extraction_method:'catalog'},findings:[finding],reports:[report],report_refs:[report],risk_catalog:[{risk_id:'R001',name:'供应商准入与围标串标',domain:'采购与外包',description:'虚构风险',owner_dept:'采购部',period:'2026H2'}],period:'2026H2'}),
      save_finding:async(_task,_id,payload)=>{finding={...finding,...payload};return{finding};},
      get_source_preview:async()=>({kind:'text',source_report_title:'历史采购审计报告',source_page:'第 3 页',source_excerpt:'虚构摘录'}),
    }};
  });
  await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
  await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
  await page.getByLabel('选择 历史采购审计报告').check();
  await page.getByRole('button',{name:'形成风险评估图谱'}).click();
  await page.getByRole('button',{name:'选择当前正式工作簿'}).click();
  await page.getByLabel('目标评估期间').fill('2026H2');
  await page.getByRole('button',{name:'载入所选报告'}).click();
  await expect(page.getByLabel('匹配当前风险 F-1-1')).toBeVisible();
  await page.getByLabel('匹配当前风险 F-1-1').selectOption('R001');
  await page.getByRole('button',{name:'确认发现关系并继续'}).click();
  await expect(page.getByLabel('责任部门 F-1-1')).toHaveValue('采购部');
});

test('desktop mode never unlocks the heatmap from browser sample state', async ({ page }) => {
  await page.addInitScript(() => {
    window.pywebview={api:{get_bootstrap:async()=>({profiles:[],domains:[],dimensions:[],dimension_labels:{},workspace:{schema_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',created_at:'x'},catalog_root:'C:/synthetic/catalog',catalog_reports:[],capabilities:{desktop:true,source_preview:true,report_catalog:true}})}};
  });
  await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
  await page.locator('#btn-sample').click();
  await expect(page.locator('#tbl-prio tbody tr')).not.toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
  await expect(page.getByRole('button',{name:'▦　风险图谱'})).toBeDisabled();
  await expect(page.locator('#tbl-prio')).toBeHidden();
});

test('temporarily skipped evidence does not enter current risk decisions', async ({ page }) => {
  await page.addInitScript(() => {
    const dims=['imp_financial','imp_compliance','imp_operation','imp_reputation','imp_fraud','imp_strategy','imp_data','imp_hse'];
    const report={report_id:'REP-SKIP',recognition_version:1,entity_id:'ENT-1',entity_name:'虚构主体甲',audit_project:'采购审计',upload_date:'2026-09-04',uploaded_at:'x',report_date:'',report_title:'采购审计报告',file_name:'x.pdf',file_hash:'a'.repeat(64),model_profile:'m',extraction_method:'text',status:'已完成',finding_count:1,record_path:'x'};
    let finding={task_id:'BATCH-SKIP',finding_id:'F-1-1',title:'暂不处理的发现',fact_summary:'虚构事实',source_page:'采购审计报告｜第 1 页',source_excerpt:'虚构摘录',matched_risk_id:'R001',domain:'采购与外包',likelihood:3,impact_scores:Object.fromEntries(dims.map(dim=>[dim,2])),rationale:'虚构依据',needs_review:true,review_status:'已接受',merged_finding_ids:[],merged_into:''};
    window.pywebview={api:{
      get_bootstrap:async()=>({profiles:[],domains:['采购与外包'],dimensions:dims,dimension_labels:{},workspace:{entity_id:'ENT-1',entity_name:'虚构主体甲'},catalog_root:'C:/synthetic/catalog',catalog_reports:[report]}),
      choose_report:async()=>({selection_token:'BOOK',basename:'register.xlsx'}),
      create_catalog_batch:async()=>({task:{task_id:'BATCH-SKIP',status:'待复核',extraction_method:'catalog'},findings:[finding],reports:[report],report_refs:[report],risk_catalog:[{risk_id:'R001',name:'供应商风险',owner_dept:'采购部',period:'2026H2'}],period:'2026H2'}),
      save_finding:async(_task,_id,payload)=>{finding={...finding,...payload};return{finding};},
    }};
  });
  await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
  await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
  await page.getByLabel('选择 采购审计报告').check();
  await page.getByRole('button',{name:'形成风险评估图谱'}).click();
  await page.getByRole('button',{name:'选择当前正式工作簿'}).click();
  await page.getByLabel('目标评估期间').fill('2026H2');
  await page.getByRole('button',{name:'载入所选报告'}).click();
  await page.getByLabel('本次暂不处理').check();
  await page.getByRole('button',{name:'确认发现关系并继续'}).click();
  await expect(page.locator('#report-risk-decisions .decision-card')).toHaveCount(0);
});
