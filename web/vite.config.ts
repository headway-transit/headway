/// <reference types="vitest/config" />
import { createReadStream, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin, type Connect } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Dev/preview parity for the self-hosted basemap (handoff 0027).
 *
 * In the deployed stack, nginx serves /basemap/region.pmtiles from the
 * read-only compose mount (deploy/compose/basemap). In development this
 * middleware serves the SAME file from the same directory, with the byte-
 * range support PMTiles requires.
 *
 * RECORDED CHOICE — middleware, not the public/ dir: anything in public/
 * is copied into the build artifact by `vite build`, and the basemap
 * belongs to the DEPLOYMENT (a per-installation, gitignored download),
 * never to the artifact. A symlink into public/ would bake tens of MB of
 * map data into every image; this middleware keeps dev serving the
 * deployment's own file and the artifact clean.
 */
function basemapDevServer(): Plugin {
  const basemapDir = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../deploy/compose/basemap",
  );

  const handler: Connect.NextHandleFunction = (req, res, next) => {
    const url = (req.url ?? "").split("?")[0];
    if (!url.startsWith("/basemap/")) return next();
    // Exactly the one deployed file — no directory-traversal surface.
    if (url !== "/basemap/region.pmtiles") {
      res.statusCode = 404;
      return res.end("not found");
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.statusCode = 405;
      return res.end("method not allowed");
    }
    const file = path.join(basemapDir, "region.pmtiles");
    let size: number;
    try {
      size = statSync(file).size;
    } catch {
      res.statusCode = 404; // absent basemap: an honest 404, like nginx
      return res.end("not found");
    }
    res.setHeader("Accept-Ranges", "bytes");
    res.setHeader("Content-Type", "application/octet-stream");
    res.setHeader("Cache-Control", "no-cache");

    const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? "");
    if (range) {
      const start = Number(range[1]);
      const end =
        range[2] === "" ? size - 1 : Math.min(Number(range[2]), size - 1);
      if (start >= size || start > end) {
        res.statusCode = 416;
        res.setHeader("Content-Range", `bytes */${size}`);
        return res.end();
      }
      res.statusCode = 206;
      res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
      res.setHeader("Content-Length", String(end - start + 1));
      if (req.method === "HEAD") return res.end();
      return createReadStream(file, { start, end }).pipe(res);
    }

    res.statusCode = 200;
    res.setHeader("Content-Length", String(size));
    if (req.method === "HEAD") return res.end();
    return createReadStream(file).pipe(res);
  };

  return {
    name: "headway-basemap-dev-server",
    configureServer(server) {
      server.middlewares.use(handler);
    },
    configurePreviewServer(server) {
      server.middlewares.use(handler);
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), basemapDevServer()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
