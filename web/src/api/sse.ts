/** Server-sent events client with reconnect and exponential backoff (API.md section 6). */

export const TOPICS = ["hello", "sessions", "inbox", "products", "dispatch", "usage", "toast"] as const;
export type Topic = (typeof TOPICS)[number];

export type EventSourceLike = {
  addEventListener(type: string, fn: (ev: MessageEvent) => void): void;
  onerror: ((ev: Event) => void) | null;
  onopen: ((ev: Event) => void) | null;
  close(): void;
  readyState: number;
};

export type SseOptions = {
  url?: string;
  /** Called for every named event with its parsed JSON payload. */
  onEvent: (topic: Topic, data: unknown) => void;
  /** Called on every `hello` (connect or resync): the UI refetches everything visible. */
  onHello?: (data: { version: string; boot_id: string; resync: boolean }) => void;
  onStatus?: (connected: boolean) => void;
  create?: (url: string) => EventSourceLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (id: unknown) => void;
  random?: () => number;
  minDelayMs?: number;
  maxDelayMs?: number;
};

/** Delay before reconnect attempt `attempt` (0-based): doubles from min up to max, with up to 25% jitter. */
export function backoffDelay(attempt: number, min = 1000, max = 30000, random = Math.random): number {
  const base = Math.min(max, min * 2 ** Math.min(attempt, 20));
  return Math.round(base * (1 + 0.25 * random()));
}

const CLOSED = 2;

/** Opens the stream and keeps it open. Returns a function that stops it. */
export function connectEvents(opts: SseOptions): () => void {
  const url = opts.url ?? "/api/events";
  const create = opts.create ?? ((u) => new EventSource(u) as unknown as EventSourceLike);
  const setTimer = opts.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimer ?? ((id) => clearTimeout(id as ReturnType<typeof setTimeout>));
  let es: EventSourceLike | null = null;
  let timer: unknown = null;
  let attempt = 0;
  let stopped = false;

  const open = () => {
    timer = null;
    const cur = create(url);
    es = cur;
    for (const topic of TOPICS) {
      cur.addEventListener(topic, (ev) => {
        let data: unknown = null;
        try {
          data = JSON.parse(ev.data);
        } catch {
          /* a malformed payload is passed on as null */
        }
        if (topic === "hello") {
          attempt = 0; // the server answered: the next failure starts the backoff again
          opts.onStatus?.(true);
          opts.onHello?.(data as { version: string; boot_id: string; resync: boolean });
        }
        opts.onEvent(topic, data);
      });
    }
    cur.onerror = () => {
      if (stopped || es !== cur) return;
      opts.onStatus?.(false);
      cur.close(); // take over reconnecting so the delay is ours, not the browser's
      es = null;
      schedule();
    };
  };

  const schedule = () => {
    if (stopped || timer !== null) return;
    const delay = backoffDelay(attempt++, opts.minDelayMs, opts.maxDelayMs, opts.random);
    timer = setTimer(open, delay);
  };

  open();
  return () => {
    stopped = true;
    if (timer !== null) clearTimer(timer);
    if (es && es.readyState !== CLOSED) es.close();
    es = null;
  };
}
