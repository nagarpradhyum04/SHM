import { Edges, Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { memo, useCallback, useMemo } from "react";
import * as THREE from "three";
import type { Component, Priority, Vec3 } from "@/api/types";
import { len, mid, quatFromY, sub } from "@/lib/geometry";
import { PRIORITY_COLOR } from "@/lib/priority";
import { useUI } from "@/store/ui";

const MATERIALS: Record<string, { color: string; metalness: number; roughness: number }> = {
  concrete: { color: "#7c8798", metalness: 0.05, roughness: 0.85 },
  steel: { color: "#9fb0c4", metalness: 0.7, roughness: 0.35 },
  steel_strand: { color: "#cfdced", metalness: 0.8, roughness: 0.25 },
  steel_elastomer: { color: "#56657a", metalness: 0.5, roughness: 0.5 },
};

const SELECT_COLOR = new THREE.Color("#22d3ee");
const HOVER_COLOR = new THREE.Color("#67e8f9");

interface MeshProps {
  c: Component;
  selected: boolean;
  related: boolean;
  hovered: boolean;
  heat?: { score: number; top: Priority };
  wireframe: boolean;
  boundaries: boolean;
  onPick: (e: ThreeEvent<MouseEvent>, c: Component) => void;
  onHover: (id: string | null) => void;
}

/** Transform for a geometry descriptor: position, quaternion, and box/cylinder args. */
export function meshTransform(c: Component): { position: Vec3; quaternion: [number, number, number, number]; kind: "box" | "cyl"; args: number[] } | null {
  const g = c.geometry;
  if (!g || g.type === "group") return null;
  if (g.type === "box") return { position: [c.model_x, c.model_y, c.model_z], quaternion: [0, 0, 0, 1], kind: "box", args: g.size };
  const length = len(sub(g.end, g.start));
  const q = quatFromY(g.start, g.end);
  if (g.type === "beam") return { position: mid(g.start, g.end), quaternion: q, kind: "box", args: [g.section[0], length, g.section[1]] };
  return { position: mid(g.start, g.end), quaternion: q, kind: "cyl", args: [g.radius, g.radius, length, 6, 1] };
}

const ComponentMesh = memo(function ComponentMesh({ c, selected, related, hovered, heat, wireframe, boundaries, onPick, onHover }: MeshProps) {
  const t = useMemo(() => meshTransform(c), [c]);
  const base = MATERIALS[c.material ?? "concrete"] ?? MATERIALS.concrete;
  if (!t) return null;
  const heatColor = heat ? new THREE.Color(PRIORITY_COLOR[heat.top]) : null;
  const emissive = selected ? SELECT_COLOR : hovered ? HOVER_COLOR : heatColor ?? (related ? SELECT_COLOR : new THREE.Color(0, 0, 0));
  const emissiveIntensity = selected ? 0.55 : hovered ? 0.3 : heatColor ? Math.min(0.25 + heat!.score * 0.08, 0.85) : related ? 0.4 : 0;
  const isCable = c.component_type === "stay_cable";
  return (
    <mesh
      name={c.mesh_ref ?? c.id}
      userData={{ componentId: c.id }}
      position={t.position}
      quaternion={t.quaternion}
      onClick={(e) => onPick(e, c)}
      onPointerOver={(e) => {
        e.stopPropagation();
        onHover(c.id);
      }}
      onPointerOut={() => onHover(null)}
    >
      {t.kind === "box" ? <boxGeometry args={t.args as [number, number, number]} /> : <cylinderGeometry args={t.args as [number, number, number, number, number]} />}
      <meshStandardMaterial
        color={wireframe ? "#0e7490" : base.color}
        metalness={base.metalness}
        roughness={base.roughness}
        emissive={emissive}
        emissiveIntensity={emissiveIntensity}
        wireframe={wireframe}
        transparent={wireframe}
        opacity={wireframe ? 0.55 : 1}
      />
      {boundaries && !isCable && <Edges threshold={20} color={selected ? "#a5f3fc" : "#22d3ee"} />}
    </mesh>
  );
});

export function BridgeModel({ components, all, heat }: { components: Component[]; all: Component[]; heat: Map<string, { score: number; top: Priority }> | null }) {
  const selection = useUI((s) => s.selection);
  const hoverId = useUI((s) => s.hoverId);
  const layers = useUI((s) => s.layers);
  const select = useUI((s) => s.select);
  const setHover = useUI((s) => s.setHover);
  const pickMode = useUI((s) => s.pickMode);
  const setPick = useUI((s) => s.setPick);

  const selectedId = selection?.kind === "component" ? selection.id : null;
  // children of a selected group are highlighted too
  const relatedIds = useMemo(() => {
    const out = new Set<string>();
    if (!selectedId) return out;
    const frontier = [selectedId];
    while (frontier.length) {
      const id = frontier.pop()!;
      for (const c of all) if (c.parent_id === id && !out.has(c.id)) { out.add(c.id); frontier.push(c.id); }
    }
    return out;
  }, [selectedId, all]);

  const onPick = useCallback((e: ThreeEvent<MouseEvent>, c: Component) => {
    e.stopPropagation();
    if (e.delta > 5) return; // a drag, not a click
    if (pickMode && e.face) {
      const n = e.face.normal.clone().transformDirection(e.object.matrixWorld).normalize();
      setPick({ point: [e.point.x, e.point.y, e.point.z].map((v) => +v.toFixed(3)) as Vec3, normal: [n.x, n.y, n.z].map((v) => +v.toFixed(3)) as Vec3, componentId: c.id });
      return;
    }
    select({ kind: "component", id: c.id });
  }, [pickMode, select, setPick]);

  if (!layers.model) return null;
  return (
    <group>
      {components.map((c) => (
        <ComponentMesh
          key={c.id}
          c={c}
          selected={selectedId === c.id}
          related={relatedIds.has(c.id)}
          hovered={hoverId === c.id}
          heat={layers.heatmap ? heat?.get(c.id) : undefined}
          wireframe={layers.wireframe}
          boundaries={layers.boundaries}
          onPick={onPick}
          onHover={setHover}
        />
      ))}
    </group>
  );
}

const LABELLED_TYPES = new Set(["pylon", "pier", "abutment"]);

export function ComponentLabels({ components }: { components: Component[] }) {
  const selection = useUI((s) => s.selection);
  const hoverId = useUI((s) => s.hoverId);
  const layers = useUI((s) => s.layers);
  const items = useMemo(() => {
    const byParent = new Map<string, Component[]>();
    components.forEach((c) => c.parent_id && byParent.set(c.parent_id, [...(byParent.get(c.parent_id) ?? []), c]));
    const groupTop = (id: string): Vec3 | null => {
      const kids = (byParent.get(id) ?? []).filter((k) => k.bbox);
      if (!kids.length) return null;
      const xs = kids.map((k) => (k.bbox!.min[0] + k.bbox!.max[0]) / 2);
      const top = Math.max(...kids.map((k) => k.bbox!.max[1]));
      return [xs.reduce((a, b) => a + b, 0) / xs.length, top + 6, 0];
    };
    return components
      .filter((c) => LABELLED_TYPES.has(c.component_type))
      .map((c) => ({ c, pos: c.bbox ? ([(c.bbox.min[0] + c.bbox.max[0]) / 2, c.bbox.max[1] + 5, 0] as Vec3) : groupTop(c.id) }))
      .filter((x) => x.pos);
  }, [components]);
  const focusId = selection?.kind === "component" ? selection.id : hoverId;
  const focus = focusId ? components.find((c) => c.id === focusId) : null;
  if (!layers.labels) return null;
  return (
    <>
      {items.map(({ c, pos }) => (
        <Html key={c.id} position={pos!} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
          <div className="whitespace-nowrap rounded border border-accent/30 bg-ink-950/70 px-1 font-mono text-[9px] text-accent-soft">{c.id}</div>
        </Html>
      ))}
      {focus && focus.bbox && (
        <Html position={[(focus.bbox.min[0] + focus.bbox.max[0]) / 2, focus.bbox.max[1] + 2, (focus.bbox.min[2] + focus.bbox.max[2]) / 2]} center zIndexRange={[20, 10]} style={{ pointerEvents: "none" }}>
          <div className="whitespace-nowrap rounded border border-accent/60 bg-ink-950/90 px-2 py-1 text-[11px] text-white shadow-glow">
            <div className="font-medium">{focus.name}</div>
            <div className="font-mono text-[10px] text-accent-soft">{focus.id} · {focus.component_type.replace(/_/g, " ")}</div>
          </div>
        </Html>
      )}
    </>
  );
}
