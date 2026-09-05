const { test, expect } = require('@playwright/test');

test('report catalog prototype keeps selection action usable through the batch flow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/docs/prototypes/report-catalog-batch-demo.html');

  await expect(page.getByRole('heading', { name: '还没有可用于风险评估的报告' })).toBeVisible();
  await expect(page.locator('#catalogTableWrap')).toBeHidden();

  await page.getByRole('button', { name: '载入界面演示记录' }).click();
  await page.getByLabel('选择 采购管理专项审计报告').check();
  await page.getByLabel('选择 供应链内部控制审计报告').check();
  await expect(page.locator('#selectionBar')).toHaveClass(/show/);

  const overlap = await page.evaluate(() => {
    const action = document.querySelector('#createBatch').getBoundingClientRect();
    const consoleBox = document.querySelector('.prototype-console').getBoundingClientRect();
    return !(action.right <= consoleBox.left || action.left >= consoleBox.right ||
      action.bottom <= consoleBox.top || action.top >= consoleBox.bottom);
  });
  expect(overlap).toBe(false);
  await page.screenshot({ path: 'output/playwright/prototype-report-catalog-selected.png' });

  await page.getByRole('button', { name: '✓ 识别与复核' }).click();
  await expect(page.getByRole('heading', { name: '报告识别与复核' })).toBeVisible();
  await expect(page.getByRole('button', { name: '接受并下一条' })).toBeVisible();
  await expect(page.locator('#selectionBar')).not.toHaveClass(/show/);
  expect(await page.evaluate(() => {
    const actions = document.querySelector('.sticky-actions').getBoundingClientRect();
    return actions.top >= 0 && actions.bottom <= window.innerHeight;
  })).toBe(true);
  const reviewOverlap = await page.evaluate(() => {
    const actions = document.querySelector('.sticky-actions').getBoundingClientRect();
    const consoleBox = document.querySelector('.prototype-console').getBoundingClientRect();
    return !(actions.right <= consoleBox.left || actions.left >= consoleBox.right ||
      actions.bottom <= consoleBox.top || actions.top >= consoleBox.bottom);
  });
  expect(reviewOverlap).toBe(false);
  await page.screenshot({ path: 'output/playwright/prototype-report-catalog-review.png' });
  await page.getByRole('button', { name: '▤ 报告目录' }).click();

  await page.getByRole('button', { name: '形成风险评估图谱 →' }).click();
  await expect(page.getByRole('heading', { name: '新建风险评估批次' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '相似发现处理' })).toBeVisible();
  const similarFindings = page.locator('.risk-cluster').filter({ hasText: 'R004 供应商准入与围标串标' });
  await expect(similarFindings.getByText('这 2 条发现可能指向同一项风险')).toBeVisible();
  await expect(similarFindings.getByLabel('为同一风险的两条证据')).toBeChecked();
  await expect(similarFindings.getByLabel('分别作为两项风险')).toBeVisible();
  await expect(similarFindings.getByLabel('本次暂不处理')).toBeVisible();
  await expect(similarFindings.getByText('不会删除原始发现，也不会平均建议评分。')).toBeVisible();
  await page.screenshot({ path: 'output/playwright/prototype-report-catalog-batch.png' });
  await page.getByRole('button', { name: '生成变更预览' }).click();
  await expect(page.locator('#previewBox')).toHaveClass(/show/);
  await page.getByRole('button', { name: '确认并生成版本化工作簿' }).click();
  await expect(page.getByRole('heading', { name: '风险图谱 · 2026H2' })).toBeVisible();
  await expect(page.getByRole('button', { name: '▦ 风险图谱' })).toBeEnabled();
  await page.screenshot({ path: 'output/playwright/prototype-report-catalog-heatmap.png' });

  await page.setViewportSize({ width: 1120, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'output/playwright/prototype-report-catalog-compact.png' });
});
