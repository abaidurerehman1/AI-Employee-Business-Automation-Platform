(function () {
  const script = document.currentScript;
  const site = script && script.dataset.site;
  if (!site) return;
  const base = new URL(script.src);
  const url = new URL('/widget.html', base.origin);
  url.searchParams.set('site', site);
  if (script.dataset.api) url.searchParams.set('api', script.dataset.api);
  const frame = document.createElement('iframe');
  frame.title = 'Customer support chat';
  frame.src = url.toString();
  frame.style.cssText = 'position:fixed;right:16px;bottom:16px;width:min(390px,calc(100vw - 32px));height:min(660px,calc(100dvh - 32px));border:0;z-index:2147483000;background:transparent;';
  window.addEventListener('message', function (event) {
    if (event.source !== frame.contentWindow || event.origin !== base.origin || event.data?.type !== 'ai-employee-widget-size') return;
    frame.style.width = event.data.collapsed ? '150px' : 'min(390px,calc(100vw - 32px))';
    frame.style.height = event.data.collapsed ? '60px' : 'min(660px,calc(100dvh - 32px))';
  });
  document.body.appendChild(frame);
})();
