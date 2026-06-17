// Shim: replaces next/error with a simple error display
import { createElement as h } from 'react';
export default function NextError({ statusCode }) {
  return h('div', { className: 'vane-error' },
    h('h2', null, statusCode === 404 ? 'Page Not Found' : `Error ${statusCode}`),
    h('p', null, statusCode === 404 ? 'The page you are looking for does not exist.' : 'An unexpected error occurred.'),
  );
}
