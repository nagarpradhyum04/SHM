import { Billboard, Html, Line } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import type { Component, Defect, Device, Vec3 } from "@/api/types";
import { defectAnchor, frustumCorners } from "@/lib/geometry";
import { CONNECTION_COLOR, PRIORITY_COLOR } from "@/lib/priority";
import { useUI } from "@/store/ui";

/** Keeps markers legible at any zoom level by scaling with camera distance. */
function ScreenScaled({ position, children, base = 55, min = 0.6, max = 9 }: { position: Vec3; children: ReactNode; base?: number; min?: number; max?: number }) {
  const ref = useRef<THREE.Group>(null);
  const { camera } = useThree();
  const v = useMemo(() => new THREE.Vector3(...position), [position]);
  useFrame(() => {
    if (!ref.current) return;
    const s = THREE.MathUtils.clamp(camera.position.distanceTo(v) / base, min, max);
    ref.current.scale.setScalar(s);
  });
  return <group ref={ref} position={position}>{children}</group>;
}

function PulseRing({ color, enabled }: { color: string; enabled: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (!ref.current || !enabled) return;
    const t = (clock.elapsedTime % 1.6) / 1.6;
    ref.current.scale.setScalar(1 + t * 1.8);
    (ref.current.material as THREE.MeshBasicMaterial).opacity = 0.8 * (1 - t);
  });
  if (!enabled) return null;
  return (
    <Billboard>
      <mesh ref={ref} raycast={() => null}>
        <ringGeometry args={[0.9, 1.05, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.8} depthWrite={false} />
      </mesh>
    </Billboard>
  );
}

const NEW_WINDOW_MS = 72 * 3600 * 1000;

export function DefectMarkers({ defects, components }: { defects: Defect[]; components: Map<string, Component> }) {
  const selection = useUI((s) => s.selection);
  const select = useUI((s) => s.select);
  const layers = useUI((s) => s.layers);
  const reducedMotion = useUI((s) => s.reducedMotion);
  if (!layers.defects) return null;
  const now = Date.now();
  return (
    <group>
      {defects.map((d) => {
        const comp = d.component_id ? components.get(d.component_id) : null;
        const a = defectAnchor(d, comp);
        if (!a) return null;
        const color = PRIORITY_COLOR[d.priority];
        const selected = selection?.kind === "defect" && selection.id === d.id;
        const closed = ["repaired", "closed", "false_positive"].includes(d.review_status);
        const isNew = d.review_status === "new" && now - new Date(d.observed_at).getTime() < NEW_WINDOW_MS;
        const compTop: Vec3 | null = a.kind === "component" && comp?.bbox ? [a.position[0], comp.bbox.max[1], a.position[2]] : null;
        return (
          <group key={d.id}>
            {compTop && <Line points={[compTop, a.position]} color={color} lineWidth={1} dashed dashSize={0.4} gapSize={0.3} transparent opacity={0.8} />}
            {d.overlay?.polyline && d.overlay.polyline.length > 1 && <Line points={d.overlay.polyline} color={color} lineWidth={2.5} />}
            <ScreenScaled position={a.position}>
              <group
                onClick={(e) => {
                  e.stopPropagation();
                  select({ kind: "defect", id: d.id });
                }}
                onPointerOver={() => (document.body.style.cursor = "pointer")}
                onPointerOut={() => (document.body.style.cursor = "")}
              >
                {a.kind === "surface" ? (
                  <mesh>
                    <sphereGeometry args={[0.45, 16, 12]} />
                    <meshBasicMaterial color={color} transparent opacity={closed ? 0.35 : 1} />
                  </mesh>
                ) : (
                  <mesh rotation={[0, Math.PI / 4, 0]}>
                    <octahedronGeometry args={[0.6]} />
                    <meshBasicMaterial color={color} transparent opacity={closed ? 0.35 : 1} />
                  </mesh>
                )}
                {/* uncertainty halo for approximate / component-level locations */}
                {a.approximate && (
                  <Billboard>
                    <mesh raycast={() => null}>
                      <ringGeometry args={[0.85, 0.95, 24, 1, 0, Math.PI * 2]} />
                      <meshBasicMaterial color={color} transparent opacity={0.5} depthWrite={false} />
                    </mesh>
                  </Billboard>
                )}
                {selected && (
                  <Billboard>
                    <mesh raycast={() => null}>
                      <ringGeometry args={[1.2, 1.4, 32]} />
                      <meshBasicMaterial color="#ffffff" />
                    </mesh>
                  </Billboard>
                )}
                <PulseRing color={color} enabled={isNew && !reducedMotion && !closed} />
              </group>
              {(layers.labels || selected) && (
                <Html position={[0, 1.6, 0]} center zIndexRange={[30, 20]} style={{ pointerEvents: "none" }}>
                  <div className="whitespace-nowrap rounded px-1 font-mono text-[10px]" style={{ color, background: "rgba(3,6,13,.75)", border: `1px solid ${color}55` }}>
                    {d.id}{a.kind === "component" ? " · component-level" : a.approximate ? " · approx." : ""}
                  </div>
                </Html>
              )}
            </ScreenScaled>
          </group>
        );
      })}
    </group>
  );
}

function CameraGlyph({ color }: { color: string }) {
  return (
    <group>
      <mesh>
        <boxGeometry args={[0.9, 0.6, 1.1]} />
        <meshStandardMaterial color="#0f172a" emissive={color} emissiveIntensity={0.6} />
      </mesh>
      <mesh position={[0, 0, -0.75]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.25, 0.32, 0.4, 12]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} />
      </mesh>
    </group>
  );
}

export function DeviceMarkers({ devices }: { devices: Device[] }) {
  const selection = useUI((s) => s.selection);
  const hoverId = useUI((s) => s.hoverId);
  const setHover = useUI((s) => s.setHover);
  const select = useUI((s) => s.select);
  const layers = useUI((s) => s.layers);
  if (!layers.devices) return null;
  return (
    <group>
      {devices.map((dv) => {
        const status = dv.connection?.status ?? "never_connected";
        const color = CONNECTION_COLOR[status] ?? "#64748b";
        const selected = selection?.kind === "device" && selection.id === dv.id;
        const rot = new THREE.Euler((dv.pitch_deg * Math.PI) / 180, (dv.yaw_deg * Math.PI) / 180, (dv.roll_deg * Math.PI) / 180, "YXZ");
        return (
          <ScreenScaled key={dv.id} position={[dv.model_x, dv.model_y, dv.model_z]} base={60}>
            <group
              onClick={(e) => {
                e.stopPropagation();
                select({ kind: "device", id: dv.id });
              }}
              onPointerOver={(e) => {
                e.stopPropagation();
                document.body.style.cursor = "pointer";
                setHover(dv.id);
              }}
              onPointerOut={() => {
                document.body.style.cursor = "";
                setHover(null);
              }}
            >
              {dv.device_type === "camera" ? (
                <group rotation={rot}><CameraGlyph color={color} /></group>
              ) : (
                <mesh>
                  <icosahedronGeometry args={[0.45, 0]} />
                  <meshStandardMaterial color="#0f172a" emissive={color} emissiveIntensity={0.9} flatShading />
                </mesh>
              )}
              <Billboard>
                <mesh raycast={() => null}>
                  <ringGeometry args={[0.8, 0.88, 4]} />
                  <meshBasicMaterial color={selected ? "#ffffff" : color} transparent opacity={selected ? 1 : 0.6} />
                </mesh>
              </Billboard>
            </group>
            {(selected || hoverId === dv.id || (layers.labels && dv.component_id === hoverId)) && (
              <Html position={[0, -1.3, 0]} center zIndexRange={[30, 20]} style={{ pointerEvents: "none" }}>
                <div className="whitespace-nowrap rounded border border-accent/30 bg-ink-950/80 px-1 font-mono text-[10px] text-accent-soft">
                  {dv.id}{dv.connection?.is_simulated ? " · SIM" : ""}
                </div>
              </Html>
            )}
          </ScreenScaled>
        );
      })}
    </group>
  );
}

export function CameraCoverage({ devices }: { devices: Device[] }) {
  const layers = useUI((s) => s.layers);
  const selection = useUI((s) => s.selection);
  if (!layers.coverage && selection?.kind !== "device") return null;
  const cams = devices.filter((d) => d.device_type === "camera" && d.fov_deg && (layers.coverage || d.id === selection?.id));
  return (
    <group>
      {cams.map((c) => {
        const o: Vec3 = [c.model_x, c.model_y, c.model_z];
        const k = frustumCorners(c, 28);
        const pts: Vec3[] = [o, k[0], o, k[1], o, k[2], o, k[3], k[0], k[1], k[2], k[3], k[0]];
        return (
          <group key={c.id}>
            <Line points={pts} color="#22d3ee" lineWidth={1} transparent opacity={0.65} />
          </group>
        );
      })}
    </group>
  );
}
