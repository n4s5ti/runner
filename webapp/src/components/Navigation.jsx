// Shim: replaces next/navigation with browser-native equivalents
export function useParams() {
  const segs = window.location.pathname.split('/').filter(Boolean);
  return { chatId: segs[1] || null };
}
export function useSearchParams() {
  return new URLSearchParams(window.location.search);
}
export function useSelectedLayoutSegments() {
  return window.location.pathname.split('/').filter(Boolean);
}
export function useRouter() {
  return {
    push: (url) => {
      window.history.pushState({}, '', url);
      window.dispatchEvent(new PopStateEvent('popstate'));
    },
    replace: (url) => {
      window.history.replaceState({}, '', url);
      window.dispatchEvent(new PopStateEvent('popstate'));
    },
  };
}
