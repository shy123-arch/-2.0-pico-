/**
 * Vite plugin: serve data/ folder and generate index for Load (no bridge).
 * - GET /data-index.json → list of { name, folder } for .npz files
 * - GET /data/{folder}/{name}.npz → raw file
 */
import { readdirSync, statSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

function scanDataDir(dataDir) {
  const result = [];
  const trackingRe = /-tracking-\d+$/;
  try {
    for (const sub of readdirSync(dataDir)) {
      const subPath = join(dataDir, sub);
      if (!statSync(subPath).isDirectory()) continue;
      for (const f of readdirSync(subPath)) {
        if (!f.endsWith('.npz')) continue;
        const stem = f.replace(/\.npz$/, '');
        if (sub === 'eval' && trackingRe.test(stem)) continue;
        result.push({ name: stem, folder: sub });
      }
    }
  } catch (e) {
    console.warn('[vite-plugin-serve-data]', e.message);
  }
  return result;
}

export function serveDataPlugin() {
  const dataDir = join(process.cwd(), 'data');
  return {
    name: 'serve-data',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/data-index.json' || req.url === '/data-index.json?') {
          const list = scanDataDir(dataDir);
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Access-Control-Allow-Origin', '*');
          res.end(JSON.stringify(list));
          return;
        }
        if (req.url?.startsWith('/data/')) {
          const path = req.url.slice(6);
          if (path.includes('..')) {
            res.statusCode = 403;
            res.end();
            return;
          }
          const filePath = join(dataDir, path);
          try {
            const buf = readFileSync(filePath);
            res.setHeader('Content-Type', 'application/octet-stream');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(buf);
          } catch (e) {
            res.statusCode = 404;
            res.end();
          }
          return;
        }
        next();
      });
    },
  };
}
