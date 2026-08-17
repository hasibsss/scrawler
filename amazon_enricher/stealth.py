"""Small set of init-script patches to make the Playwright-controlled Chromium
look less obviously like automation. Not bulletproof, but enough to avoid the
naive bot signals (navigator.webdriver, empty plugins/languages, missing
chrome runtime) that trip the cheapest detection checks.
"""

INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5].map(() => ({ name: 'Chrome PDF Plugin' })),
});

window.chrome = window.chrome || { runtime: {} };

const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : originalQuery(parameters)
  );
}

Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
"""
