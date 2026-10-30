export interface Revision { id: string; title: string; at: string }
export interface Notice { id: string; title: string; body: string; revisions: Revision[] }
export interface RevisionInput { operationId: string; title: string; body: string }
export type Operation = { state: 'committed'; notice: Notice } | { state: 'pending' | 'absent' };
