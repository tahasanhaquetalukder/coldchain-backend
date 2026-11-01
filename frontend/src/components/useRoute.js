import { useEffect, useState } from 'react';

/** Hash routing, because a QR label has to carry a URL that works with no server-side route table
 * and a `file://`-served bundle still needs deep links. */
export const navigate = (path) => {
  window.location.hash = path.startsWith('#') ? path : `#${path}`;
};

export function useHashRoute() {
  const read = () => window.location.hash.replace(/^#\/?/, '');
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
