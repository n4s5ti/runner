// IndexedDB persistence for chats and messages via Dexie.js.
// Replaces Vane's Drizzle/SQLite server-side DB.

class ChatsDB {
  constructor() {
    this.db = new window.Dexie('VaneChats');
    this.db.version(1).stores({
      chats: 'id, createdAt',
      messages: 'id, chatId, messageId, createdAt',
    });
    this.chats = this.db.table('chats');
    this.messages = this.db.table('messages');
  }
}

const db = new ChatsDB();

export function saveChat(chat) { return db.chats.put(chat); }
export function getChat(id) { return db.chats.get(id); }
export function listChats() { return db.chats.orderBy('createdAt').reverse().toArray(); }
export async function deleteChat(id) {
  await db.chats.delete(id);
  await db.messages.where('chatId').equals(id).delete();
}
export function saveMessage(msg) { return db.messages.put(msg); }
export function getMessages(chatId) {
  return db.messages.where('chatId').equals(chatId).sortBy('createdAt');
}
export function getMessageByMessageId(messageId) {
  return db.messages.where('messageId').equals(messageId).first();
}
export function updateMessageStatus(messageId, status, responseBlocks) {
  return db.messages.where('messageId').equals(messageId).modify({ status, responseBlocks });
}
