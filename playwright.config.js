const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  use: { channel: 'chrome', headless: true },
});
