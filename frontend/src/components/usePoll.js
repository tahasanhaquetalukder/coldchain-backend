import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../api.js';

/** Keep a resource fresh on an interval.
 *
 * The loader is held in a ref, so the interval never fires a callback that closed over an older
 * selection, and only the first attempt shows a loading state: a refresh that blanks the dashboard
 * for half a second is worse than a half-second-old number.
 */
export function usePoll(load, ms = 5000, { paused = false, key = '' } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [booted, setBooted] = useState(false);
  const ref = useRef(load);
  ref.current = load;

  const run = useCallback(async () => {
    try {
      setData(await ref.current());
      setError('');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBooted(true);
    }
  }, []);

  useEffect(() => {
    if (paused) return undefined;
    run();
    const timer = setInterval(run, ms);
    return () => clearInterval(timer);
  }, [run, ms, paused, key]);

  return { data, error, loading: !booted && !data, refresh: run };
}
