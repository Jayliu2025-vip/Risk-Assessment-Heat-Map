const { test, expect } = require('@playwright/test');

for (const preset of [
  {id:'glm',url:'https://open.bigmodel.cn/api/paas/v4',model:'glm-5'},
  {id:'kimi',url:'https://api.moonshot.cn/v1',model:'kimi-k2.5'},
]) {
  test(`${preset.id} preset fills the official endpoint and model`, async ({page}) => {
    await openSettings(page);
    await page.locator('#model-provider').selectOption(preset.id);
    await expect(page.locator('#model-base-url')).toHaveValue(preset.url);
    await expect(page.locator('#model-model')).toHaveValue(preset.model);
    await expect(page.locator('#model-key-link')).toBeVisible();
    await page.locator('#model-api-key').fill('synthetic-key');
    await page.getByRole('button',{name:'保存并验证',exact:true}).click();
    await expect(page.locator('#model-status')).toContainText('连接正常');
    const saved = await page.evaluate(() => window.modelCalls[0]);
    expect(saved.base_url).toBe(preset.url);
    expect(saved.supports_vision).toBe(false);
  });
}

async function openSettings(page, existing = false) {
  await page.addInitScript(({ existing }) => {
    const profiles = existing ? [{name:'已有配置',base_url:'https://model.example.test/v1',model:'synthetic-model',supports_vision:false}] : [];
    window.modelCalls = [];
    window.modelFailure = null;
    window.pywebview = { api: {
      get_bootstrap: async () => ({profiles,domains:[],workspace:{entity_name:'虚构主体'},catalog_reports:[],capabilities:{desktop:true}}),
      save_model_profile: async value => {
        window.modelCalls.push({operation:'save', ...value});
        const {api_key, ...profile} = value;
        return {ok:true,profile};
      },
      test_model_profile: async name => {
        window.modelCalls.push({operation:'test',name});
        await new Promise(resolve => setTimeout(resolve, 120));
        const saved = window.modelCalls.filter(call => call.operation === 'save').at(-1);
        return window.modelFailure || {ok:true,hostname:new URL(saved.base_url).hostname};
      },
    }};
  }, {existing});
  await page.goto('file://' + process.cwd().replace(/\\/g, '/') + '/web/risk_heatmap.html');
  await page.setViewportSize({width:1280,height:960});
  await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
  await page.getByRole('button',{name:'＋ 添加审计报告'}).click();
  if (existing) await page.locator('#model-settings > summary').click();
}

test('first setup needs only provider and key, then saves current form before testing', async ({page}) => {
  await openSettings(page);
  await expect(page.locator('#model-provider')).toBeVisible();
  await expect(page.locator('#report-step-review')).toBeHidden();
  await page.locator('#model-provider').selectOption('deepseek');
  await page.locator('#model-api-key').fill('synthetic-key');
  await page.getByRole('button',{name:'保存并验证',exact:true}).click();
  await expect(page.locator('#model-status')).toContainText('连接正常');
  const calls = await page.evaluate(() => window.modelCalls);
  expect(calls.map(call => call.operation)).toEqual(['save','test']);
  expect(calls[0].base_url).toBe('https://api.deepseek.com/v1');
  expect(calls[0].model).toBeTruthy();
  expect(calls[1].name).toBe(calls[0].name);
  await expect(page.locator('#model-api-key')).toHaveValue('');
  await expect(page.locator('#model-api-key')).toHaveAttribute('type','password');
  await expect(page.locator('#report-start')).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({path:'output/playwright/model-settings-success.png',fullPage:true});
});

test('editing existing profile fills fields, keeps blank key and exposes failures locally', async ({page}) => {
  await openSettings(page, true);
  await expect(page.locator('#model-model')).toHaveValue('synthetic-model');
  await expect(page.locator('#model-api-key')).toHaveAttribute('placeholder', /留空/);
  await expect(page.locator('#model-status')).toContainText('待验证');
  await expect(page.locator('#report-start')).toBeDisabled();
  await page.locator('#model-model').fill('changed-model');
  await page.evaluate(() => {window.modelFailure={ok:false,code:'MODEL_AUTH_FAILED',message:'密钥无效或没有调用权限，请重新粘贴密钥并检查模型权限。'};});
  await page.getByRole('button',{name:'保存并验证',exact:true}).click();
  await expect(page.locator('#model-status')).toContainText('密钥无效');
  await expect(page.locator('#report-start')).toBeDisabled();
  const calls = await page.evaluate(() => window.modelCalls);
  expect(calls[0].model).toBe('changed-model');
  expect(calls[0].api_key).toBe('');
  await page.evaluate(() => {window.modelFailure=null;});
  await page.getByRole('button',{name:'保存并验证',exact:true}).click();
  await expect(page.locator('#model-status')).toContainText('连接正常');
  await expect(page.locator('#report-status')).not.toContainText('密钥无效');
  await page.locator('#model-model').fill('unverified-model');
  await expect(page.locator('#model-status')).toContainText('修改');
  await expect(page.locator('#report-start')).toBeDisabled();
});

test('empty input and changing providers never reuse a pasted key silently', async ({page}) => {
  await openSettings(page);
  await page.getByRole('button',{name:'保存并验证',exact:true}).click();
  await expect(page.locator('#model-status')).toContainText('服务商');
  expect(await page.evaluate(() => window.modelCalls.length)).toBe(0);
  await page.locator('#model-provider').selectOption('deepseek');
  await page.locator('#model-api-key').fill('synthetic-key');
  await page.locator('#model-provider').selectOption('qwen-cn');
  await expect(page.locator('#model-api-key')).toHaveValue('');
  await expect(page.locator('#model-base-url')).toHaveValue('https://dashscope.aliyuncs.com/compatible-mode/v1');
  await page.getByRole('button',{name:'保存并验证',exact:true}).click();
  await expect(page.locator('#model-status')).toContainText('密钥');
  expect(await page.evaluate(() => window.modelCalls.length)).toBe(0);
});

test('verification freezes editing and suppresses duplicate submissions', async ({page}) => {
  await openSettings(page);
  await page.locator('#model-provider').selectOption('deepseek');
  await page.locator('#model-api-key').fill('synthetic-key');
  await page.evaluate(() => {
    const original = window.pywebview.api.test_model_profile;
    window.pywebview.api.test_model_profile = async name => {
      await new Promise(resolve => { window.releaseVerification = resolve; });
      return original(name);
    };
    const button = document.getElementById('model-save');
    button.dispatchEvent(new Event('click'));
    button.dispatchEvent(new Event('click'));
  });
  await expect(page.locator('#model-status')).toContainText('正在');
  await expect(page.locator('#model-provider')).toBeDisabled();
  await expect(page.locator('#report-model-profile')).toBeDisabled();
  await expect(page.locator('#model-new')).toBeDisabled();
  expect(await page.evaluate(() => window.modelCalls.filter(call => call.operation === 'save').length)).toBe(1);
  await page.waitForFunction(() => typeof window.releaseVerification === 'function');
  await page.evaluate(() => window.releaseVerification());
  await expect(page.locator('#model-status')).toContainText('连接正常');
  await expect(page.locator('#model-provider')).toBeEnabled();
});
