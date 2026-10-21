// AVA entry point. Every page registers its own route.
import { refreshMe, render } from './core.js';
import './public.js';
import './office.js';
import './work.js';
import './inspect.js';
import { toggleAgent } from './agent.js';
document.getElementById('fab').onclick = toggleAgent;

(async () => {
  try { await refreshMe(); } catch (_) { /* offline or signed out */ }
  render();
  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('/sw.js').catch(() => {});
})();
