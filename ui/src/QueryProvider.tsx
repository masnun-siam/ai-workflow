import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { toast } from './components';

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: { quiet?: boolean };
  }
}

export function makeQueryClient() {
  return new QueryClient({
    mutationCache: new MutationCache({
      // A failed write always says why; a call that renders the error itself passes meta {quiet: true}.
      onError: (e, _v, _c, m) => {
        if (!m.meta?.quiet) toast.error(e instanceof Error ? e.message : 'Something went wrong');
      },
    }),
    defaultOptions: { queries: { retry: 1, staleTime: 2000, refetchOnWindowFocus: true } },
  });
}

export function QueryProvider({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [qc] = useState(() => client ?? makeQueryClient());
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
