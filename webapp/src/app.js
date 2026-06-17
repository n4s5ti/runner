// Vane Relay — browser-only SPA with Vane-like UI.
// Sidebar with chat history, settings panel, search with mode/provider selectors.

import { ChatProvider, useChat, setProxyUrl } from './hooks/useChatRunner.js';
import { listChats, deleteChat, getChat } from './db.js';

const { createElement: h, useState, useRef, useEffect, useCallback } = window.React;

// --- Sidebar ---
function Sidebar({ chats, activeChatId, onSelectChat, onNewChat }) {
  const [collapsed, setCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (collapsed) {
    return h('div', { className: 'vn-sidebar vn-sidebar-collapsed' },
      h('button', { className: 'vn-sidebar-toggle', onClick: () => setCollapsed(false), title: 'Expand sidebar' }, '☰'),
    );
  }

  return h('div', { className: 'vn-sidebar' },
    h('div', { className: 'vn-sidebar-header' },
      h('button', { className: 'vn-btn-icon', onClick: onNewChat, title: 'New chat' }, '+'),
      h('button', { className: 'vn-btn-icon', onClick: () => setSettingsOpen(!settingsOpen), title: 'Settings' }, '⚙'),
      h('button', { className: 'vn-btn-icon', onClick: () => setCollapsed(true), title: 'Collapse' }, '◀'),
    ),
    settingsOpen && h(SettingsPanel, { onClose: () => setSettingsOpen(false) }),
    h('div', { className: 'vn-chat-list' },
      chats.length === 0 && h('div', { className: 'vn-empty' }, 'No chats yet. Start a search above.'),
      chats.map(c => {
        const isHome = c.id === '__home__';
        return h('div', {
          key: c.id,
          className: 'vn-chat-item' + (c.id === activeChatId || (isHome && !activeChatId) ? ' vn-chat-active' : ''),
          onClick: () => onSelectChat(isHome ? null : c.id),
        },
          h('span', { className: 'vn-chat-title' }, isHome ? '🏠 New Chat' : (c.title || 'Untitled').slice(0, 40)),
          !isHome && h('button', {
            className: 'vn-btn-x',
            onClick: (e) => { e.stopPropagation(); deleteChat(c.id).then(() => onNewChat()); },
            title: 'Delete',
          }, '×'),
        );
      }),
    ),
  );
}

// --- Settings ---
function SettingsPanel({ onClose }) {
  const { config, setConfig } = useChat();
  const [proxyUrl, setProxyUrlLocal] = useState(localStorage.getItem('vane_proxy_url') || '');

  return h('div', { className: 'vn-settings' },
    h('div', { className: 'vn-settings-header' },
      h('h3', null, 'Settings'),
      h('button', { className: 'vn-btn-x', onClick: onClose }, '×'),
    ),
    h('label', { className: 'vn-field' },
      h('span', null, 'Edge Proxy URL'),
      h('input', {
        type: 'text', value: proxyUrl,
        placeholder: 'https://vane-relay.YOUR.workers.dev',
        onChange: e => setProxyUrlLocal(e.target.value),
        onBlur: () => { localStorage.setItem('vane_proxy_url', proxyUrl); setProxyUrl(proxyUrl); },
      }),
    ),
    h('label', { className: 'vn-field' },
      h('span', null, 'Default Mode'),
      h('select', { value: config.mode, onChange: e => setConfig({ ...config, mode: e.target.value }) },
        h('option', { value: 'speed' }, 'Speed (1 iter)'),
        h('option', { value: 'balanced' }, 'Balanced (3 iters)'),
        h('option', { value: 'quality' }, 'Quality (5 iters)'),
      ),
    ),
    h('label', { className: 'vn-field' },
      h('span', null, 'Provider'),
      h('select', { value: config.provider, onChange: e => setConfig({ ...config, provider: e.target.value }) },
        h('option', { value: 'ollama' }, 'Ollama (in-runner)'),
        h('option', { value: 'openai' }, 'OpenAI'),
        h('option', { value: 'anthropic' }, 'Anthropic'),
        h('option', { value: 'groq' }, 'Groq'),
      ),
    ),
    h('label', { className: 'vn-field' },
      h('span', null, 'Model'),
      h('input', {
        type: 'text', value: config.model || '',
        placeholder: 'llama3.2:3b',
        onChange: e => setConfig({ ...config, model: e.target.value }),
      }),
    ),
  );
}

// --- ChatWindow ---
function ChatWindow() {
  const { messages, sections, loading, ready, error, config, sendMessage, rewrite, setConfig } = useChat();
  const [query, setQuery] = useState('');
  const [chats, setChats] = useState([{ id: '__home__', title: 'New Chat', createdAt: new Date().toISOString() }]);
  const [activeChatId, setActiveChatId] = useState(null);
  const inputRef = useRef(null);
  const endRef = useRef(null);

  // Load chat list
  const refreshChats = useCallback(async () => {
    try {
      const all = await listChats();
      setChats([{ id: '__home__', title: 'New Chat', createdAt: new Date().toISOString() }, ...all]);
    } catch { /* DB not ready */ }
  }, []);

  useEffect(() => { refreshChats(); }, [refreshChats]);

  // Resolve chatId from URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const cid = params.get('chat');
    if (cid) {
      getChat(cid).then(c => {
        if (c) setActiveChatId(cid);
        else window.history.replaceState(null, '', '/');
      });
    }
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [sections, loading]);

  function handleSubmit(e) {
    e?.preventDefault();
    if (!query.trim() || loading) return;
    sendMessage(query.trim());
    setQuery('');
    refreshChats();
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  }

  function handleSelectChat(cid) {
    if (cid) {
      setActiveChatId(cid);
      window.history.pushState(null, '', `?chat=${cid}`);
    } else {
      setActiveChatId(null);
      window.history.pushState(null, '', window.location.pathname);
    }
  }

  function handleNewChat() {
    setActiveChatId(null);
    window.history.pushState(null, '', window.location.pathname);
  }

  if (!ready) {
    return h('div', { className: 'vn-layout' },
      h(Sidebar, { chats, activeChatId, onSelectChat: handleSelectChat, onNewChat: handleNewChat }),
      h('div', { className: 'vn-main' },
        h('div', { className: 'vn-loading' }, h('div', { className: 'vn-spinner' }), 'Loading...'),
      ),
    );
  }

  function renderMessage(section, i) {
    const msg = section.message;
    return h('div', { key: msg.messageId, className: 'vn-message' },
      h('div', { className: 'vn-query' }, msg.query),
      section.sources?.length > 0 && h('div', { className: 'vn-sources' },
        ...section.sources.flatMap(b => (b.data || []).map((s, j) =>
          h('a', { key: j, className: 'vn-source', href: s.url, target: '_blank', rel: 'noopener' },
            (s.title || s.url || 'Source').slice(0, 60)))),
      ),
      msg.status === 'answering' && loading
        ? h('div', { className: 'vn-loading' }, h('div', { className: 'vn-spinner' }),
            ` Researching (${config.mode} mode, ${config.provider}) — may take 30-120s...`)
        : h('div', { className: 'vn-answer',
            dangerouslySetInnerHTML: { __html: marked.parse(section.parsedText || '') || '' } }),
    );
  }

  return h('div', { className: 'vn-layout' },
    h(Sidebar, { chats, activeChatId, onSelectChat: handleSelectChat, onNewChat: handleNewChat }),
    h('div', { className: 'vn-main' },
      h('form', { className: 'vn-search', onSubmit: handleSubmit },
        h('textarea', {
          ref: inputRef, value: query,
          onChange: e => setQuery(e.target.value),
          onKeyDown: handleKeyDown,
          placeholder: 'Ask Vane anything...',
          disabled: loading,
          autoFocus: true,
        }),
        h('div', { className: 'vn-search-row' },
          h('select', { value: config.mode, onChange: e => setConfig({ ...config, mode: e.target.value }), title: 'Research depth' },
            h('option', { value: 'speed' }, '⚡ Speed'),
            h('option', { value: 'balanced' }, '⚖ Balanced'),
            h('option', { value: 'quality' }, '🔬 Quality'),
          ),
          h('select', { value: config.provider, onChange: e => setConfig({ ...config, provider: e.target.value }), title: 'LLM provider' },
            h('option', { value: 'ollama' }, '🦙 Ollama'),
            h('option', { value: 'openai' }, '🤖 OpenAI'),
            h('option', { value: 'anthropic' }, '🧠 Anthropic'),
            h('option', { value: 'groq' }, '⚡ Groq'),
          ),
          h('button', { type: 'submit', disabled: loading || !query.trim() }, loading ? 'Running...' : 'Search'),
        ),
      ),
      error && h('div', { className: 'vn-error' },
        h('strong', null, 'Error: '), error,
        h('br'),
        h('button', { onClick: () => window.location.reload() }, 'Reload'),
      ),
      sections.length === 0 && !loading && !error &&
        h('div', { className: 'vn-empty-state' },
          h('h2', null, 'Vane Relay'),
          h('p', null, 'Research with SearXNG + Ollama, running on GitHub Actions. No servers to maintain.'),
          h('p', { className: 'vn-hint' }, 'Type a query above to start researching.'),
        ),
      ...sections.map(renderMessage),
      h('div', { ref: endRef }),
    ),
  );
}

// --- Bootstrap ---
const root = window.ReactDOM.createRoot(document.getElementById('root'));
root.render(h(ChatProvider, { chatId: new URLSearchParams(window.location.search).get('chat') || null },
  h(ChatWindow)));
