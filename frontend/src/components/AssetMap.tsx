import "leaflet/dist/leaflet.css";
import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import type { Asset } from "@/api/types";

/** Geographic overview. Only assets with recorded WGS84 coordinates are drawn. */
export default function AssetMap({ assets, selected, tileUrl }: { assets: Asset[]; selected: string; tileUrl: string }) {
  const located = assets.filter((a) => a.latitude !== null && a.longitude !== null);
  const sel = located.find((a) => a.id === selected) ?? located[0];
  return (
    <MapContainer center={[sel.latitude!, sel.longitude!]} zoom={14} style={{ height: 320 }} className="rounded-b-lg">
      <TileLayer url={tileUrl} attribution={import.meta.env.VITE_MAP_ATTRIBUTION ?? ""} />
      {located.map((a) => (
        <CircleMarker key={a.id} center={[a.latitude!, a.longitude!]} radius={a.id === selected ? 10 : 7} pathOptions={{ color: "#22d3ee" }}>
          <Tooltip>{a.name}</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
