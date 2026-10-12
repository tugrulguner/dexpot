function enableHomepageCodeKeyboardScrolling() {
  document.querySelectorAll('main .sl-markdown-content pre').forEach((pre) => {
    if (pre.scrollWidth > pre.clientWidth) pre.tabIndex = 0;
  });
}

let homepageCodeObserver;

function watchHomepageCodeKeyboardScrolling() {
  homepageCodeObserver?.disconnect();
  enableHomepageCodeKeyboardScrolling();
  const content = document.querySelector('main .sl-markdown-content');
  if (!content) return;

  const observer = homepageCodeObserver ??= new ResizeObserver(enableHomepageCodeKeyboardScrolling);
  observer.observe(content);
  content.querySelectorAll('pre').forEach((pre) => observer.observe(pre));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', watchHomepageCodeKeyboardScrolling, { once: true });
} else {
  watchHomepageCodeKeyboardScrolling();
}
document.addEventListener('astro:page-load', watchHomepageCodeKeyboardScrolling);
document.fonts?.ready.then(enableHomepageCodeKeyboardScrolling);
window.addEventListener('resize', enableHomepageCodeKeyboardScrolling);
