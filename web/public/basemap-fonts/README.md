# Vendored basemap glyphs (handoff 0027)

`Noto Sans Regular/` holds the complete PBF glyph set (256 range files,
`0-255.pbf` … `65280-65535.pbf`) for the **Noto Sans Regular** typeface,
copied verbatim from [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets)
(generated there with MapLibre's font-maker). The map style requests them
as `/basemap-fonts/{fontstack}/{range}.pbf` — **same origin, always**: label
rendering never contacts an outside glyph server (the zero-external-requests
rule extends to fonts).

License: **SIL Open Font License 1.1** (`OFL.txt`, copied alongside —
Copyright 2022 The Noto Project Authors, https://github.com/notofonts).
OFL is a permissive font license; bundling and redistribution with software
are expressly permitted. Recorded in the web/README.md dependency table.

Recorded scope decision: only the Regular stack is vendored (6.9 MB). The
Protomaps themes also reference Noto Sans Medium and Italic; every basemap
label layer is rewritten at runtime to use Regular so no request for an
unvendored stack can ever fire. That is a typography trade (no bold/italic
street labels), never a data trade. Sprites (POI icons) are not vendored in
v0 — the POI layer is dropped and the limitation is stated in the map
legend.
