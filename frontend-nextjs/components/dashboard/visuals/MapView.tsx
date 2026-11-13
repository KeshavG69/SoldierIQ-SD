"use client";

// MapLibre view for an intelligence map payload. Loaded client-side only
// (next/dynamic, ssr:false) because maplibre-gl needs the DOM.
import React, { useCallback, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { MapFeature, MapPayload } from "@/types";
import { LAYER_ICON, SEVERITY_COLOR, iconSvg } from "./intelStyle";

// OpenFreeMap: free vector basemap, no API key. Swap for self-hosted PMTiles
// for offline / air-gapped deployments.
const STYLE_DARK = "https://tiles.openfreemap.org/styles/dark";
const STYLE_LIGHT = "https://tiles.openfreemap.org/styles/positron";

interface MapViewProps {
  payload: MapPayload;
  hiddenLayers: Set<string>;
  selectedId: string | null;
  onSelect: (feature: MapFeature | null) => void;
  expanded?: boolean;
}

function circlePolygon(lat: number, lon: number, radiusKm: number, steps = 48): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    const dLat = (radiusKm / 111.32) * Math.cos(a);
    const dLon = (radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180))) * Math.sin(a);
    out.push([lon + dLon, lat + dLat]);
  }
  return out;
}

export default function MapView({ payload, hiddenLayers, selectedId, onSelect, expanded }: MapViewProps) {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Map<string, { marker: maplibregl.Marker; root: HTMLDivElement; el: HTMLButtonElement; feature: MapFeature }>>(new Map());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Build the map once per mounted container (ref callback, no effect needed).
  const containerRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) {
        mapRef.current?.remove();
        mapRef.current = null;
        markersRef.current.clear();
        return;
      }
      const dark = document.documentElement.classList.contains("dark");
      const map = new maplibregl.Map({
        container: node,
        style: dark ? STYLE_DARK : STYLE_LIGHT,
        center: [20, 25],
        zoom: 1.4,
        attributionControl: { compact: true },
        // Inside the scrolling chat, need ctrl/two fingers to move the map; full screen moves freely.
        cooperativeGestures: !expanded,
        dragRotate: false,
      });
      map.touchZoomRotate.disableRotation();
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      mapRef.current = map;

      // Fit to the requested region, else to the features. Re-run after load: the
      // container can still be settling (dynamic import, card layout) at construction.
      const fit = () => {
        map.resize();
        const pts = payload.features.map((f) => [f.lon, f.lat] as [number, number]);
        if (payload.bbox) {
          const [w, s, e, n] = payload.bbox;
          map.fitBounds([[w, s], [e, n]], { padding: 16, duration: 0 });
        } else if (pts.length > 1) {
          const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
          pts.forEach((p) => b.extend(p));
          map.fitBounds(b, { padding: 32, maxZoom: 6, duration: 0 });
        }
      };
      fit();
      map.once("load", () => {
        fit();
        // The compact attribution opens expanded on narrow screens and covers the map; start it closed.
        node.querySelector(".maplibregl-ctrl-attrib.maplibregl-compact-show")?.classList.remove("maplibregl-compact-show");
      });

      map.on("load", () => {
        // Hotspot radii as faint rings under the icons.
        const rings = payload.features
          .filter((f) => f.layer === "hotspots" && f.radius_km)
          .map((f) => ({
            type: "Feature" as const,
            properties: { color: SEVERITY_COLOR[f.severity] || "#B2AA7D", layer: f.layer },
            geometry: { type: "Polygon" as const, coordinates: [circlePolygon(f.lat, f.lon, f.radius_km!)] },
          }));
        map.addSource("hotspot-rings", { type: "geojson", data: { type: "FeatureCollection", features: rings } });
        map.addLayer({ id: "hotspot-fill", type: "fill", source: "hotspot-rings", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.08 } });
        map.addLayer({ id: "hotspot-line", type: "line", source: "hotspot-rings", paint: { "line-color": ["get", "color"], "line-opacity": 0.5, "line-width": 1, "line-dasharray": [2, 2] } });
      });

      map.on("click", (e) => {
        if ((e.originalEvent.target as HTMLElement)?.closest?.("[data-intel-marker]")) return;
        onSelectRef.current(null);
      });

      // Tappable icon markers. MapLibre positions the root element with a CSS transform,
      // so styling and the selection highlight live on the inner button.
      payload.features.forEach((f) => {
        const color = SEVERITY_COLOR[f.severity] || "#B2AA7D";
        const root = document.createElement("div");
        const el = document.createElement("button");
        el.type = "button";
        el.dataset.intelMarker = f.id;
        el.setAttribute("aria-label", f.title);
        el.title = f.title;
        el.style.cssText = `width:30px;height:30px;border-radius:9999px;display:flex;align-items:center;justify-content:center;background:rgba(11,15,14,.82);border:1.5px solid ${color};box-shadow:0 1px 4px rgba(0,0,0,.45);cursor:pointer;padding:0;touch-action:manipulation;transition:transform .12s ease;`;
        el.innerHTML = iconSvg(LAYER_ICON[f.layer] || "hotspot", color, 16, f.heading ?? null);
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          onSelectRef.current(f);
        });
        root.appendChild(el);
        const marker = new maplibregl.Marker({ element: root }).setLngLat([f.lon, f.lat]).addTo(map);
        markersRef.current.set(f.id, { marker, root, el, feature: f });
      });
    },
    // The payload and mode define the map; a change remounts it via the key in the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // Apply layer visibility and selection highlight on every render (cheap DOM writes).
  markersRef.current.forEach(({ root, el, feature }) => {
    root.style.display = hiddenLayers.has(feature.layer) ? "none" : "";
    el.style.transform = feature.id === selectedId ? "scale(1.35)" : "";
    root.style.zIndex = feature.id === selectedId ? "5" : "";
  });
  const map = mapRef.current;
  if (map?.getLayer?.("hotspot-fill")) {
    const vis = hiddenLayers.has("hotspots") ? "none" : "visible";
    map.setLayoutProperty("hotspot-fill", "visibility", vis);
    map.setLayoutProperty("hotspot-line", "visibility", vis);
  }

  // maplibre-gl.css sets `position: relative` on the map element, so it needs a sized wrapper.
  return (
    <div className="absolute inset-0">
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
