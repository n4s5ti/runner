// Vane type definitions — structural stubs for browser-only use.
// These match the Shapes used by Vane React components.

export const Block = {}; // { id: string, type: string, data: any }

export const SourceBlock = {}; // { id: string, type: 'source', data: Array<{ title: string, url: string, snippet?: string, engine?: string }> }

export const TextBlock = {}; // { id: string, type: 'text', data: string }

export const ResearchBlock = {}; // { id: string, type: 'research', data: { subSteps: ResearchBlockSubStep[] } }

export const ResearchBlockSubStep = {}; // { id: string, type: 'reasoning'|'searching'|'search_results'|'reading'|'upload_searching'|'upload_search_results', ... }

export const SearchSources = {}; // 'web' | 'discussions' | 'academic'

export const ChatTurnMessage = {}; // { role: string, content: string }

export const Chunk = {}; // { type: string, data: any, blockId?: string }

export const Widget = {}; // { widgetType: string, params: Record<string, any> }
