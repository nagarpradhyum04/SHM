/**
 * Renders an uploaded GLB structural model and maps its objects to registered components.
 *
 * Mapping: the backend registers components with mesh_ref "gltf-node:<index>". GLTFLoader records
 * which glTF node produced each three.js object (parser.associations), so every mesh is resolved to
 * the nearest registered node (itself or an ancestor). Node names are never relied on.
 */
import { useGLTF } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";
import type { Component, Priority, Vec3 } from "@/api/types";
import { PRIORITY_COLOR } from "@/lib/priority";
import { useUI } from "@/store/ui";

const SELECT = new THREE.Color("#22d3ee");
const HOVER = new THREE.Color("#67e8f9");
const BLACK = new THREE.Color(0, 0, 0);

export function nodeIndexFromMeshRef(ref: string | null): number | null {
  const m = /^gltf-node:(\d+)$/.exec(ref ?? "");
  return m ? Number(m[1]) : null;
}

interface Props {
  url: string;
  components: Component[];
  heat: Map<string, { score: number; top: Priority }> | null;
}

export function GltfModel({ url, components, heat }: Props) {
  // No Draco/meshopt decoders: they would be fetched from a CDN. The backend rejects such files.
  const gltf = useGLTF(url, false, false);
  const selection = useUI((s) => s.selection);
  const hoverId = useUI((s) => s.hoverId);
  const layers = useUI((s) => s.layers);
  const select = useUI((s) => s.select);
  const setHover = useUI((s) => s.setHover);
  const pickMode = useUI((s) => s.pickMode);
  const setPick = useUI((s) => s.setPick);

  const nodeToComponent = useMemo(() => {
    const m = new Map<number, string>();
    components.forEach((c) => {
      const i = nodeIndexFromMeshRef(c.mesh_ref);
      if (i !== null) m.set(i, c.id);
    });
    return m;
  }, [components]);

  // Clone the scene so materials can be modified per mesh without touching the cached original.
  const { scene, meshes } = useMemo(() => {
    const assoc = (gltf.parser as unknown as { associations: Map<THREE.Object3D, { nodes?: number }> }).associations;
    const nodeOf = new Map<THREE.Object3D, number>();
    gltf.scene.traverse((o) => {
      const a = assoc.get(o);
      if (a?.nodes !== undefined) nodeOf.set(o, a.nodes);
    });
    const clone = gltf.scene.clone(true);
    const list: THREE.Mesh[] = [];
    // clone() preserves traversal order, so walk both trees in parallel to carry node indices over.
    const src: THREE.Object3D[] = [];
    gltf.scene.traverse((o) => src.push(o));
    let k = 0;
    clone.traverse((o) => {
      const original = src[k++];
      const idx = nodeOf.get(original);
      if (idx !== undefined) o.userData.gltfNode = idx;
      if ((o as THREE.Mesh).isMesh) {
        const mesh = o as THREE.Mesh;
        mesh.material = Array.isArray(mesh.material) ? mesh.material.map((m) => m.clone()) : (mesh.material as THREE.Material).clone();
        list.push(mesh);
      }
    });
    return { scene: clone, meshes: list };
  }, [gltf]);

  // Resolve each mesh to the nearest registered component (self or ancestor).
  useEffect(() => {
    for (const mesh of meshes) {
      let o: THREE.Object3D | null = mesh;
      let cid: string | undefined;
      while (o && !cid) {
        if (o.userData.gltfNode !== undefined) cid = nodeToComponent.get(o.userData.gltfNode);
        o = o.parent;
      }
      mesh.userData.componentId = cid;
    }
  }, [meshes, nodeToComponent]);

  // Selection / hover / heat / wireframe styling.
  useEffect(() => {
    const selectedId = selection?.kind === "component" ? selection.id : null;
    const related = new Set<string>();
    if (selectedId) {
      const frontier = [selectedId];
      while (frontier.length) {
        const id = frontier.pop()!;
        components.forEach((c) => c.parent_id === id && !related.has(c.id) && (related.add(c.id), frontier.push(c.id)));
      }
    }
    for (const mesh of meshes) {
      const cid = mesh.userData.componentId as string | undefined;
      const h = layers.heatmap && cid ? heat?.get(cid) : undefined;
      const mats = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) as THREE.MeshStandardMaterial[];
      for (const m of mats) {
        m.wireframe = layers.wireframe;
        if (!("emissive" in m)) continue;
        if (cid && cid === selectedId) {
          m.emissive.copy(SELECT);
          m.emissiveIntensity = 0.55;
        } else if (cid && cid === hoverId) {
          m.emissive.copy(HOVER);
          m.emissiveIntensity = 0.3;
        } else if (h) {
          m.emissive.set(PRIORITY_COLOR[h.top]);
          m.emissiveIntensity = Math.min(0.25 + h.score * 0.08, 0.85);
        } else if (cid && related.has(cid)) {
          m.emissive.copy(SELECT);
          m.emissiveIntensity = 0.35;
        } else {
          m.emissive.copy(BLACK);
          m.emissiveIntensity = 0;
        }
      }
    }
  }, [meshes, selection, hoverId, heat, layers.heatmap, layers.wireframe, components]);

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (e.delta > 5) return;
    const cid = e.object.userData.componentId as string | undefined;
    if (pickMode && e.face && cid) {
      const n = e.face.normal.clone().transformDirection(e.object.matrixWorld).normalize();
      setPick({ point: [e.point.x, e.point.y, e.point.z].map((v) => +v.toFixed(3)) as Vec3, normal: [n.x, n.y, n.z].map((v) => +v.toFixed(3)) as Vec3, componentId: cid });
      return;
    }
    if (cid) select({ kind: "component", id: cid });
  };

  if (!layers.model) return null;
  return (
    <primitive
      object={scene}
      onClick={onClick}
      onPointerOver={(e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation();
        setHover((e.object.userData.componentId as string) ?? null);
      }}
      onPointerOut={() => setHover(null)}
    />
  );
}
