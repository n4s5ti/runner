// Shim: replaces next/link with plain anchor + SPA navigation
import { createElement as h } from 'react';
export default function Link({ href, children, className, ...props }) {
  const handleClick = (e) => {
    e.preventDefault();
    window.history.pushState({}, '', href);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };
  return h('a', { href, className, onClick: handleClick, ...props }, children);
}
