/**
 * DesignSyncProvider — preview-only wrapper for the design-sync pipeline.
 * Components like Receipt and Layout render react-router links; previews
 * (and designs built in claude.ai/design) need a router context to exist.
 * MemoryRouter costs nothing and navigates nowhere.
 */
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

export function DesignSyncProvider({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}
