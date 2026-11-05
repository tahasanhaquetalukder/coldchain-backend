import { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Copy, ExternalLink, Printer, X } from 'lucide-react';

/** The label a batch gets taped to: this URL is what a stranger scans, so it is the public origin,
 * never the API host. */
export const checkUrl = (code) => `${window.location.origin}/#/check/${encodeURIComponent(code)}`;

export default function QrModal({ batch, onClose }) {
  const [copied, setCopied] = useState(false);
  const url = checkUrl(batch.code);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 bg-scrim grid place-items-center p-4" onClick={onClose}>
      <div
        id="qr-print"
        className="card w-full max-w-sm text-center"
        role="dialog"
        aria-modal="true"
        aria-label={`QR code for batch ${batch.code}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-lg font-bold">{batch.code}</h3>
          <button className="btn-quiet !px-2 !py-1" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="text-sm text-text-2">
          {batch.vaccine} · expires {batch.expiry}
        </p>
        {/* Never a token: a dark tile is an unreadable tile. Contrast is what a scanner measures, and
            a module that is not darker than its neighbour is not a module. */}
        <div className="mx-auto mt-4 h-56 w-56 grid place-items-center bg-white p-2 rounded-xl">
          <QRCodeSVG value={url} size={216} level="M" includeMargin />
        </div>
        <p className="mt-3 break-all font-mono text-[11px] text-muted">{url}</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <button className="btn-primary flex items-center gap-2" onClick={() => window.print()}>
            <Printer className="h-4 w-4" /> Print label
          </button>
          <button
            className="btn-quiet flex items-center gap-2"
            onClick={() => {
              navigator.clipboard?.writeText(url);
              setCopied(true);
            }}
          >
            <Copy className="h-4 w-4" /> {copied ? 'Copied' : 'Copy link'}
          </button>
          <a className="btn-quiet flex items-center gap-2" href={url} target="_blank" rel="noreferrer">
            <ExternalLink className="h-4 w-4" /> Open check page
          </a>
        </div>
      </div>
    </div>
  );
}
