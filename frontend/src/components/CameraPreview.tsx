import { useState } from "react";
import type { Device } from "@/api/types";
import { Notice } from "./ui";

/** Live MJPEG preview served by the camera agent (reachable only from machines that can reach the agent). */
export function CameraPreview({ d }: { d: Device }) {
  const [failed, setFailed] = useState(false);
  if (!d.stream_url) return <Notice>No live preview registered. Start the camera agent (<code className="mono">python -m edge.camera_agent</code>); it reports its preview URL.</Notice>;
  if (failed) return <Notice tone="warn">Live preview at <span className="mono">{d.stream_url}</span> is not reachable from this browser (agent stopped, or bound to another machine).</Notice>;
  return (
    <figure className="overflow-hidden rounded-md border border-white/10 bg-black">
      <img src={d.stream_url} alt={`Live view ${d.id}`} className="block w-full" onError={() => setFailed(true)} />
      <figcaption className="px-2 py-1 text-[10px] text-slate-400">LIVE · {d.stream_url}</figcaption>
    </figure>
  );
}
