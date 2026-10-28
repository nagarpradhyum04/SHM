/** Non-interactive scenery: water, banks, deck furniture and a holographic grid. Not part of the component registry. */
import { Grid } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

const noRaycast = () => null;

function Instanced({ positions, geometry, color, emissive }: { positions: [number, number, number][]; geometry: THREE.BufferGeometry; color: string; emissive?: string }) {
  const mesh = useMemo(() => {
    const m = new THREE.InstancedMesh(geometry, new THREE.MeshStandardMaterial({ color, emissive: emissive ?? "#000", emissiveIntensity: emissive ? 1.2 : 0, roughness: 0.6 }), positions.length);
    const o = new THREE.Object3D();
    positions.forEach((p, i) => {
      o.position.set(...p);
      o.updateMatrix();
      m.setMatrixAt(i, o.matrix);
    });
    m.raycast = noRaycast;
    return m;
  }, [positions, geometry, color, emissive]);
  return <primitive object={mesh} />;
}

export function Decor({ wireframe }: { wireframe: boolean }) {
  const lampPositions = useMemo(() => {
    const out: [number, number, number][] = [];
    for (let x = -187.5; x <= 187.5; x += 25) out.push([x, 33.2, 11.6], [x, 33.2, -11.6]);
    return out;
  }, []);
  const lampHeads = useMemo(() => lampPositions.map(([x, , z]) => [x, 36.4, z * 0.93] as [number, number, number]), [lampPositions]);
  const dashes = useMemo(() => {
    const out: [number, number, number][] = [];
    for (let x = -196; x <= 196; x += 8) out.push([x, 30.02, -4], [x, 30.02, 4]);
    return out;
  }, []);
  const poleGeo = useMemo(() => new THREE.CylinderGeometry(0.12, 0.16, 6.4, 6), []);
  const headGeo = useMemo(() => new THREE.BoxGeometry(0.9, 0.25, 0.5), []);
  const dashGeo = useMemo(() => new THREE.BoxGeometry(3, 0.02, 0.18), []);

  return (
    <group>
      {/* Water */}
      <mesh rotation-x={-Math.PI / 2} position={[0, 1.5, 0]} raycast={noRaycast} receiveShadow>
        <planeGeometry args={[2400, 1600]} />
        <meshStandardMaterial color="#061223" metalness={0.55} roughness={0.55} transparent opacity={wireframe ? 0.35 : 0.95} />
      </mesh>
      <Grid position={[0, 1.6, 0]} args={[2400, 1600]} cellSize={10} cellThickness={0.5} cellColor="#0e3a4f" sectionSize={50}
        sectionThickness={1} sectionColor="#155e75" fadeDistance={900} fadeStrength={1.5} infiniteGrid={false} raycast={noRaycast} />
      {/* River banks / approach embankments */}
      {[-1, 1].map((s) => (
        <group key={s}>
          <mesh position={[s * 330, 12.5, 0]} raycast={noRaycast}>
            <boxGeometry args={[250, 25, 320]} />
            <meshStandardMaterial color="#111b2c" roughness={0.95} wireframe={wireframe} />
          </mesh>
          <mesh position={[s * 330, 27, 0]} raycast={noRaycast}>
            <boxGeometry args={[250, 4, 24]} />
            <meshStandardMaterial color="#1b2638" roughness={0.9} wireframe={wireframe} />
          </mesh>
          <mesh position={[s * 330, 29.05, 0]} raycast={noRaycast}>
            <boxGeometry args={[250, 0.1, 22]} />
            <meshStandardMaterial color="#20293a" roughness={0.95} />
          </mesh>
        </group>
      ))}
      {!wireframe && (
        <>
          {/* Parapets */}
          {[-1, 1].map((s) => (
            <mesh key={s} position={[0, 30.6, s * 11.85]} raycast={noRaycast}>
              <boxGeometry args={[400, 1.2, 0.3]} />
              <meshStandardMaterial color="#5d6b7f" roughness={0.7} />
            </mesh>
          ))}
          <mesh position={[0, 30.45, 0]} raycast={noRaycast}>
            <boxGeometry args={[400, 0.9, 0.6]} />
            <meshStandardMaterial color="#4b586b" roughness={0.7} />
          </mesh>
          <Instanced positions={dashes} geometry={dashGeo} color="#cbd5e1" />
          <Instanced positions={lampPositions} geometry={poleGeo} color="#64748b" />
          <Instanced positions={lampHeads} geometry={headGeo} color="#fef9c3" emissive="#fde68a" />
        </>
      )}
    </group>
  );
}
