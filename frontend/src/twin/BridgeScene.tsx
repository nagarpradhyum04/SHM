import { CameraControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Suspense, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { Component, Defect, Device, Priority } from "@/api/types";
import { BRIDGE_RADIUS, BRIDGE_TARGET, focusDirection, viewPosition } from "@/lib/geometry";
import { useUI } from "@/store/ui";
import { BridgeModel, ComponentLabels } from "./BridgeModel";
import { Decor } from "./Decor";
import { CameraCoverage, DefectMarkers, DeviceMarkers } from "./Markers";

/** Distance at which a sphere of the given radius fits the viewport (accounts for aspect ratio). */
function fitDistance(radius: number, cam: THREE.PerspectiveCamera): number {
  const vfov = (cam.fov * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * cam.aspect);
  return radius / Math.sin(Math.min(vfov, hfov) / 2);
}

function CameraRig() {
  const ref = useRef<CameraControls>(null);
  const cam = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const cmd = useUI((s) => s.cameraCommand);
  const reducedMotion = useUI((s) => s.reducedMotion);

  const framed = (view: "front" | "side" | "top" | "perspective", scale = 1) => {
    const d = fitDistance(BRIDGE_RADIUS * scale, cam);
    const p = viewPosition(view, [0, 0, 0], 1);
    const n = Math.hypot(...p);
    return [BRIDGE_TARGET[0] + (p[0] / n) * d, BRIDGE_TARGET[1] + (p[1] / n) * d, BRIDGE_TARGET[2] + (p[2] / n) * d] as const;
  };

  useEffect(() => {
    const c = ref.current;
    if (!c || size.width === 0) return;
    const p = framed("perspective", 0.66);
    c.setLookAt(p[0], p[1], p[2], ...BRIDGE_TARGET, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const c = ref.current;
    if (!c || !cmd) return;
    const animate = !reducedMotion;
    if (cmd.type === "reset" || cmd.type === "fit") {
      const p = framed("perspective", cmd.type === "fit" ? 0.6 : 0.66);
      c.setLookAt(p[0], p[1], p[2], ...BRIDGE_TARGET, animate);
    } else if (cmd.type === "view") {
      const p = framed(cmd.view, cmd.view === "top" ? 0.75 : 0.6);
      c.setLookAt(p[0], p[1], p[2], ...BRIDGE_TARGET, animate);
    } else if (cmd.type === "focus") {
      const pos = new THREE.Vector3();
      const tgt = new THREE.Vector3();
      c.getPosition(pos);
      c.getTarget(tgt);
      const cur = pos.sub(tgt).normalize();
      const dir = new THREE.Vector3(...focusDirection([cur.x, cur.y, cur.z], cmd.normal)).multiplyScalar(cmd.radius * 1.6);
      const t = cmd.target;
      c.setLookAt(t[0] + dir.x, t[1] + dir.y, t[2] + dir.z, t[0], t[1], t[2], animate);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cmd, reducedMotion]);

  return <CameraControls ref={ref} makeDefault minDistance={4} maxDistance={1400} maxPolarAngle={Math.PI * 0.495} smoothTime={0.45} />;
}

export interface SceneData {
  components: Component[];
  componentMap: Map<string, Component>;
  devices: Device[];
  defects: Defect[];
  heat: Map<string, { score: number; top: Priority }> | null;
}

export default function BridgeScene({ components, componentMap, devices, defects, heat }: SceneData) {
  const wireframe = useUI((s) => s.layers.wireframe);
  const select = useUI((s) => s.select);
  const pickMode = useUI((s) => s.pickMode);
  const renderable = useMemo(() => components.filter((c) => c.geometry && c.geometry.type !== "group"), [components]);
  return (
    <Canvas
      camera={{ fov: 40, near: 0.5, far: 6000, position: [-200, 140, 260] }}
      dpr={[1, 2]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onPointerMissed={(e) => e.type === "click" && !pickMode && select(null)}
      style={{ cursor: pickMode ? "crosshair" : "default" }}
      data-testid="bridge-canvas"
    >
      <color attach="background" args={["#040812"]} />
      <fog attach="fog" args={["#040812", 500, 1700]} />
      <hemisphereLight args={["#cdeeff", "#0b1220", 0.9]} />
      <directionalLight position={[-180, 260, 160]} intensity={2.1} color="#e6f4ff" />
      <directionalLight position={[220, 120, -200]} intensity={0.5} color="#38bdf8" />
      <ambientLight intensity={0.15} />
      <Suspense fallback={null}>
        <Decor wireframe={wireframe} />
        <BridgeModel components={renderable} all={components} heat={heat} />
        <ComponentLabels components={components} />
        <DeviceMarkers devices={devices} />
        <CameraCoverage devices={devices} />
        <DefectMarkers defects={defects} components={componentMap} />
      </Suspense>
      <CameraRig />
    </Canvas>
  );
}
