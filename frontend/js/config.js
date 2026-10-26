// @ts-check
/** API base URL comes from <meta name="api-base"> (set with `npm run configure` / API_BASE_URL). Empty = same origin. */
export function apiBase() {
  if (typeof document === 'undefined') return '';
  const meta = document.querySelector('meta[name="api-base"]');
  return (meta?.getAttribute('content') ?? '').trim().replace(/\/+$/, '');
}
