// Replacement for Vane's useChat.tsx.
// Swaps SSE + SQLite for edge proxy dispatch + IndexedDB + localStorage.

import { dispatchResearch, waitForRun, getArtifacts, downloadResult } from '../proxy-client.js';
import {
  saveChat, getChat, listChats, deleteChat,
  saveMessage, getMessages, updateMessageStatus,
} from '../db.js';

function genId() { return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`; }
function nowISO() { return new Date().toISOString(); }

const DEFAULTS = {
  mode: 'balanced',
  provider: 'ollama',
  model: 'llama3.2:3b',
  sources: ['web'],
};

function loadCfg() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem('vane_cfg') || '{}') }; }
  catch { return { ...DEFAULTS }; }
}
function saveCfg(cfg) {
  try { localStorage.setItem('vane_cfg', JSON.stringify(cfg)); } catch {}
}

const ChatCtx = window.React.createContext(null);

export function ChatProvider({ children, chatId: initChatId }) {
  const R = window.React;
  const [messages, setMessages] = R.useState([]);
  const [sections, setSections] = R.useState([]);
  const [loading, setLoading] = R.useState(false);
  const [ready, setReady] = R.useState(false);
  const [error, setError] = R.useState(null);
  const [config, setConfig] = R.useState(loadCfg);
  const chatIdRef = R.useRef(initChatId);
  const historyRef = R.useRef([]);

  R.useEffect(() => {
    (async () => {
      try {
        if (initChatId) {
          const msgs = await getMessages(initChatId);
          setMessages(msgs.map(m => ({ ...m, createdAt: new Date(m.createdAt) })));
          historyRef.current = msgs.map(m => [m.query,
            (m.responseBlocks || []).filter(b => b.type === 'text').map(b => b.data).join('\n') || '']);
        }
      } catch (e) { console.error('Load failed:', e); }
      setReady(true);
    })();
  }, [initChatId]);

  R.useEffect(() => {
    setSections(messages.map(msg => ({
      message: msg,
      parsedText: (msg.responseBlocks || []).filter(b => b.type === 'text').map(b => b.data).join('\n\n'),
      sources: (msg.responseBlocks || []).filter(b => b.type === 'source'),
      status: msg.status,
    })));
  }, [messages]);

  async function sendMessage(query) {
    if (!query?.trim() || loading) return;
    setLoading(true); setError(null);

    const messageId = genId();
    let chatId = chatIdRef.current;

    if (!chatId) {
      chatId = genId();
      chatIdRef.current = chatId;
      await saveChat({ id: chatId, title: query.slice(0, 80), createdAt: nowISO(), sources: '[]', files: '[]' });
      window.history.replaceState(null, '', `?chat=${chatId}`);
    }

    const userMsg = { id: genId(), messageId: genId(), chatId, query, responseBlocks: [], status: 'completed', createdAt: nowISO() };
    const asstMsg = { id: genId(), messageId, chatId, query, responseBlocks: [], status: 'answering', createdAt: nowISO() };
    await saveMessage(userMsg);
    await saveMessage(asstMsg);
    setMessages(prev => [...prev, userMsg, asstMsg]);
    historyRef.current.push([query, '']);

    try {
      const { run_id } = await dispatchResearch({
        query, mode: config.mode, provider: config.provider, model: config.model,
      });
      const conclusion = await waitForRun(run_id, 3000);
      if (conclusion === 'failure') throw new Error('Workflow run failed');

      const artifacts = await getArtifacts(run_id);
      if (!artifacts?.length) throw new Error('No artifacts');
      const result = await downloadResult(artifacts[0].download_url);

      const blocks = [];
      if (result.sources?.length) {
        blocks.push({ id: genId(), type: 'source', data: result.sources });
      }
      blocks.push({ id: genId(), type: 'text', data: result.answer || '' });

      await updateMessageStatus(messageId, 'completed', blocks);
      setMessages(prev => prev.map(m =>
        m.messageId === messageId ? { ...m, status: 'completed', responseBlocks: blocks } : m));
    } catch (e) {
      setError(e.message);
      const errBlocks = [{ id: genId(), type: 'text', data: `**Error:** ${e.message}` }];
      await updateMessageStatus(messageId, 'error', errBlocks);
      setMessages(prev => prev.map(m =>
        m.messageId === messageId ? { ...m, status: 'error', responseBlocks: errBlocks } : m));
    } finally {
      setLoading(false);
    }
  }

  const rewrite = (messageId) => {
    const msg = messages.find(m => m.messageId === messageId);
    if (msg) sendMessage(msg.query);
  };

  const ctx = { messages, sections, loading, ready, error, config, sendMessage, rewrite,
    setConfig: (c) => { saveCfg(c); setConfig(c); },
    historyRef, chatIdRef };

  return R.createElement(ChatCtx.Provider, { value: ctx }, children);
}

export function useChat() {
  return window.React.useContext(ChatCtx);
}
