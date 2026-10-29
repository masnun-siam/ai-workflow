import type { Anchor } from '../lib/anchor';

export interface PublicPrd { title: string; status: string; text: string; updated_at: string }
export interface PublicComment { id: string; author: string; by_owner: boolean; body: string; at: string }
export interface PublicThread { id: string; anchor: Anchor; resolved: boolean; comments: PublicComment[] }
