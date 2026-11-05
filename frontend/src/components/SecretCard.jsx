import { useState } from 'react';
import { Copy, KeyRound } from 'lucide-react';

/** The only screen that ever shows a node secret, and the only text a node ever needs.
 *
 * The server stores the key but has no route that returns it again, so this panel is the moment the
 * operator writes it down or loses the node.
 */
export default function SecretCard({ secret, onDismiss }) {
  const [copied, setCopied] = useState('');
  const lines = `#define DEVICE_ID   "${secret.device_id}"\n#define HMAC_KEY      "${secret.hmac_key}"`;

  const copy = (text, what) => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => setCopied(what), () => setCopied(''));
  };

  return (
    <div className="card border-2 !border-primary">
      <p className="font-bold text-primary flex items-center gap-2">
        <KeyRound className="h-4 w-4" />
        {secret.rotated
          ? `New key issued for ${secret.device_id} - the old one is dead`
          : `${secret.device_id} is registered`}
        <span className="font-normal text-text-2">· write these into cc_config.h</span>
      </p>
      <pre className="mt-3 rounded-xl bg-surface-2 border border-border text-text p-4 text-xs leading-6 overflow-x-auto">
        {lines}
      </pre>
      <div className="mt-3 flex flex-wrap gap-2 items-center">
        <button className="btn-quiet" onClick={() => copy(lines, 'both lines')}>
          <Copy className="inline h-3.5 w-3.5 mr-1" />
          copy both lines
        </button>
        <button className="btn-quiet font-mono" onClick={() => copy(secret.hmac_key, 'key only')}>
          <Copy className="inline h-3.5 w-3.5 mr-1" />
          copy key only
        </button>
        {copied && <span className="text-xs text-safe-strong">copied {copied}</span>}
      </div>
      <p className="mt-3 text-xs text-danger-strong">
        This is the only time the server shows it. The node signs with this key alone - the shared fleet
        key is refused for it. If the node is reflashed or the key is lost, rotate it and paste the new
        pair; there is no way to read this one again.
      </p>
      <button className="mt-3 text-xs underline text-text-2" onClick={onDismiss}>
        I have written it down
      </button>
    </div>
  );
}
