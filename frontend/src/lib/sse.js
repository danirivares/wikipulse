/**
 * Lightweight deduplicated EventSource client.
 * Skips callbacks when consecutive JSON payloads are byte-identical.
 */
export function subscribeSSE(url, onMessage) {
  let lastRaw = "";
  const es = new EventSource(url);

  es.onmessage = (event) => {
    if (event.data === lastRaw) return;
    try {
      const parsed = JSON.parse(event.data);
      lastRaw = event.data;
      onMessage(parsed);
    } catch {
      // Ignore malformed SSE frames.
    }
  };

  es.onerror = () => {
    console.warn(`SSE connection lost (${url}); browser will retry`);
  };

  return () => es.close();
}
