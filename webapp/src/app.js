// Vane Relay — browser-only SPA using GH Actions backend.
// Loads React from CDN, renders ChatWindow with ChatProvider.

import { ChatProvider, useChat } from './hooks/useChatRunner.js';

const { createElement: h, useState, useRef, useEffect } = window.React;

// --- ChatWindow component ---
function ChatWindow() {
  const { messages, sections, loading, ready, error, config, sendMessage, rewrite, setConfig } = useChat();
  const [query, setQuery] = useState('');
  const inputRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [sections, loading]);

  function handleSubmit(e) {
    e?.preventDefault();
    if (!query.trim() || loading) return;
    sendMessage(query.trim());
    setQuery('');
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  }

  if (!ready) return h('div', { className: 'vane-loading' }, h('div', { className: 'vane-spinner' }), 'Loading...');

  function renderMessage(section, i) {
    const msg = section.message;
    return h('div', { key: msg.messageId, className: 'vane-message' },
      h('div', { className: 'vane-query' }, msg.query),
      section.sources?.length > 0 && h('div', { className: 'vane-sources' },
        ...section.sources.flatMap(b => (b.data || []).map((s, j) =>
          h('a', { key: j, className: 'vane-source', href: s.url, target: '_blank', rel: 'noopener' },
            s.title?.slice(0, 50) || s.url?.slice(0, 50) || 'Source'))),
      ),
      msg.status === 'answering' && loading
        ? h('div', { className: 'vane-loading' }, h('div', { className: 'vane-spinner' }), 'Researching... (may take 30-120s)')
        : h('div', { className: 'vane-answer',
            dangerouslySetInnerHTML: { __html: window.marked.parse(section.parsedText || '') || '' } }),
    );
  }

  return h('div', { className: 'vane-container' },
    h('form', { className: 'vane-search', onSubmit: handleSubmit },
      h('textarea', {
        ref: inputRef, value: query,
        onChange: e => setQuery(e.target.value),
        onKeyDown: handleKeyDown,
        placeholder: 'Ask Vane anything...',
        disabled: loading,
        autoFocus: true,
      }),
      h('div', { className: 'vane-search-row' },
        h('select', { value: config.mode, onChange: e => setConfig({ ...config, mode: e.target.value }) },
          h('option', { value: 'speed' }, 'Speed'),
          h('option', { value: 'balanced' }, 'Balanced'),
          h('option', { value: 'quality' }, 'Quality'),
        ),
        h('select', { value: config.provider, onChange: e => setConfig({ ...config, provider: e.target.value }) },
          h('option', { value: 'ollama' }, 'Ollama (local)'),
          h('option', { value: 'openai' }, 'OpenAI'),
          h('option', { value: 'anthropic' }, 'Anthropic'),
          h('option', { value: 'groq' }, 'Groq'),
        ),
        h('button', { type: 'submit', disabled: loading || !query.trim() }, 'Search'),
      ),
    ),
    error && h('div', { className: 'vane-error' },
      error,
      h('button', { onClick: () => { window.location.reload(); } }, 'Try Again'),
    ),
    ...sections.map(renderMessage),
    loading && sections.length === 0 &&
      h('div', { className: 'vane-loading' },
        h('div', { className: 'vane-spinner' }), 'Dispatching research...'),
    h('div', { ref: endRef }),
  );
}

// --- Bootstrap ---
const root = window.ReactDOM.createRoot(document.getElementById('root'));
function App() {
  const params = new URLSearchParams(window.location.search);
  const chatId = params.get('chat') || null;
  return h(ChatProvider, { chatId }, h(ChatWindow));
}
root.render(h(App));
