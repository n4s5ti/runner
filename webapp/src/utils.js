export function cn(...a){return a.filter(Boolean).join(' ')}
export function formatTimeDifference(d){const n=new Date(),s=Math.floor((n-new Date(d))/1000);if(s<60)return'just now';if(s<3600)return Math.floor(s/60)+'m ago';if(s<86400)return Math.floor(s/3600)+'h ago';return Math.floor(s/86400)+'d ago'}
export function formatChatHistoryAsString(h){return(h||[]).map(([r,c])=>r+': '+c).join('\n')}
